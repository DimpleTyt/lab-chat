"""Password hashing, cookie sessions and the `current_user` dependency."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import secrets
import time

from fastapi import HTTPException, Request, Response

from . import db
from .config import settings

log = logging.getLogger(__name__)

COOKIE_NAME = "sid"
SESSION_TTL = 60 * 60  # idle timeout: one hour without any activity
SESSION_RENEW_AFTER = 60  # refresh the deadline at most once a minute
COOKIE_TTL = 7 * 24 * 60 * 60  # the browser keeps the cookie; the server enforces the idle hour

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64
SCRYPT_MAXMEM = 64 * 1024 * 1024


# --------------------------------------------------------------------------- #
# Password hashing: scrypt$n$r$p$salt_b64$hash_b64
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=SCRYPT_MAXMEM,
    )
    return "scrypt${}${}${}${}${}".format(
        SCRYPT_N,
        SCRYPT_R,
        SCRYPT_P,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str | None) -> bool:
    if not password or not stored:
        return False
    try:
        algo, n_s, r_s, p_s, salt_s, hash_s = stored.split("$")
        if algo != "scrypt":
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        # Guard against absurd parameters from a corrupted row.
        if not (2**10 <= n <= 2**20) or not (1 <= r <= 32) or not (1 <= p <= 16):
            return False
        salt = base64.b64decode(salt_s.encode("ascii"), validate=True)
        expected = base64.b64decode(hash_s.encode("ascii"), validate=True)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
            maxmem=256 * 1024 * 1024,
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, binascii.Error):
        return False


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #
def _session_id(token: str) -> str:
    """Store only a digest of the cookie value, never the token itself."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now,))
    db.execute(
        "INSERT INTO auth_sessions (id, user_id, expires_at) VALUES (?, ?, ?)",
        (_session_id(token), user_id, now + SESSION_TTL),
    )
    return token


def destroy_session(token: str | None) -> None:
    if token:
        db.execute("DELETE FROM auth_sessions WHERE id = ?", (_session_id(token),))


def user_from_token(token: str | None) -> dict | None:
    if not token:
        return None
    return db.get(
        """
        SELECT u.id, u.username, u.display_name, s.expires_at
        FROM auth_sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.id = ? AND s.expires_at > ?
        """,
        (_session_id(token), int(time.time())),
    )


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_TTL,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")


def unauthorized(message: str = "Требуется вход") -> HTTPException:
    return HTTPException(status_code=401, detail={"code": "unauthorized", "message": message})


def current_user(request: Request, response: Response) -> dict:
    """FastAPI dependency: authenticated user or 401. Slides the session while active."""
    token = request.cookies.get(COOKIE_NAME)
    user = user_from_token(token)
    if not user:
        raise unauthorized()
    now = int(time.time())
    expires_at = int(user.pop("expires_at", 0) or 0)
    if token and expires_at - now < SESSION_TTL - SESSION_RENEW_AFTER:
        db.execute(
            "UPDATE auth_sessions SET expires_at = ? WHERE id = ?",
            (now + SESSION_TTL, _session_id(token)),
        )
        set_session_cookie(response, token)
    return user


def find_user(username: str) -> dict | None:
    return db.get("SELECT * FROM users WHERE username = ?", (username,))
