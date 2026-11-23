"""Create or update a lab-chat user.

Usage:
    python tools/create_user.py <username> [display_name]

The password is asked twice with getpass and stored as scrypt in data/app.db.
Running the script again with the same username updates the password.
"""
from __future__ import annotations

import getpass
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import auth, db  # noqa: E402

MIN_PASSWORD = 3


def upsert_user(username: str, password: str, display_name: str | None = None) -> tuple[str, bool]:
    """Create or update a user. Returns (user_id, created)."""
    username = (username or "").strip()
    if not username:
        raise ValueError("username must not be empty")
    if not password:
        raise ValueError("password must not be empty")
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"password must be at least {MIN_PASSWORD} characters")

    db.init_db()
    row = db.get("SELECT id, display_name FROM users WHERE username = ?", (username,))
    pass_hash = auth.hash_password(password)

    if row:
        name = display_name if display_name is not None else row.get("display_name") or username
        db.execute(
            "UPDATE users SET pass_hash = ?, display_name = ? WHERE id = ?",
            (pass_hash, name, row["id"]),
        )
        return row["id"], False

    user_id = uuid.uuid4().hex
    db.execute(
        "INSERT INTO users (id, username, pass_hash, display_name) VALUES (?, ?, ?, ?)",
        (user_id, username, pass_hash, display_name or username),
    )
    return user_id, True


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    username = argv[1]
    display_name = argv[2] if len(argv) > 2 else None

    password = getpass.getpass("Пароль: ")
    repeat = getpass.getpass("Повторите пароль: ")
    if password != repeat:
        print("Пароли не совпадают.", file=sys.stderr)
        return 1
    try:
        user_id, created = upsert_user(username, password, display_name)
    except ValueError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    verb = "Создан" if created else "Обновлён"
    print(f"{verb} пользователь: {username} (id {user_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
