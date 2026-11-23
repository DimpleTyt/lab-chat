"""FastAPI application: auth, intake, plan navigation, SSE chat."""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import auth, compiler_service, db, intake as intake_parser, llm
from .compiler_service import CompileError
from .config import ROOT, settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("lab-chat")

WEB_DIR = ROOT / "web"
ASSETS_DIR = ROOT / "content" / "assets"
CLI_FILE = ROOT / "cli" / "labchat.py"

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class LoginIn(BaseModel):
    username: str
    password: str


class IntakeIn(BaseModel):
    text: str


class ConfirmIn(BaseModel):
    variant: dict = Field(default_factory=dict)


class ChatIn(BaseModel):
    text: str
    client_msg_id: str | None = None


class NextIn(BaseModel):
    client_msg_id: str | None = None


class JumpIn(BaseModel):
    to: int | str | None = None


class VariantIn(BaseModel):
    variant: dict = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _now() -> int:
    return int(time.time())


def _json_dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_load(raw, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _progress(idx: int, total: int, can_advance: bool) -> dict:
    return {"idx": idx, "total": total, "can_advance": bool(can_advance) and total > 0}


def _ensure_chat(user_id: str) -> dict:
    row = db.get("SELECT * FROM chats WHERE user_id = ?", (user_id,))
    if row:
        return row
    db.execute(
        """
        INSERT OR IGNORE INTO chats
            (user_id, variant, sources, unknown, plan, current_idx,
             can_advance, phase, updated_at)
        VALUES (?, NULL, NULL, NULL, NULL, 0, 0, 'intake', ?)
        """,
        (user_id, _now()),
    )
    row = db.get("SELECT * FROM chats WHERE user_id = ?", (user_id,))
    if not row:
        raise HTTPException(500, detail={"code": "db_error", "message": "не удалось создать чат"})
    return row


CHAT_COLUMNS = {
    "variant", "sources", "unknown", "plan",
    "current_idx", "can_advance", "phase",
    "intake_text", "anchor_id",
}


def _update_chat(user_id: str, **fields) -> None:
    pairs: list[str] = []
    values: list = []
    for key, value in fields.items():
        if key not in CHAT_COLUMNS:
            continue
        pairs.append(f"{key} = ?")
        values.append(value)
    if not pairs:
        return
    pairs.append("updated_at = ?")
    values.append(_now())
    values.append(user_id)
    db.execute(f"UPDATE chats SET {', '.join(pairs)} WHERE user_id = ?", values)


def _save_message(user_id: str, role: str, kind: str | None, content: str, step_num: int | None) -> None:
    db.execute(
        """
        INSERT INTO messages (id, user_id, role, kind, content, step_num, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (uuid.uuid4().hex, user_id, role, kind, content, step_num, _now()),
    )


def _history(user_id: str, limit: int = 8) -> list[dict]:
    rows = db.all(
        "SELECT role, content FROM messages WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    )
    return [
        {"role": row["role"], "content": row["content"]}
        for row in reversed(rows)
        if row["role"] in {"user", "assistant"} and row["content"]
    ]


def _mark_seen(user_id: str, client_msg_id: str | None) -> bool:
    """False when this (user, client_msg_id) pair was already processed."""
    if not client_msg_id:
        return True
    try:
        db.execute(
            "INSERT INTO seen (user_id, client_msg_id) VALUES (?, ?)",
            (user_id, client_msg_id),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {_json_dump(data)}\n\n"


def _compile_or_400(variant: dict | None, preserve: set[str] | None = None):
    try:
        return compiler_service.compile_variant(variant, preserve)
    except CompileError as exc:
        raise HTTPException(
            400, detail={"code": "compile_error", "message": str(exc)}
        ) from exc


VARIANT_PATHS: tuple[tuple[str, ...], ...] = (
    ("domain",),
    ("workgroup",),
    ("admin_password",),
    ("storage", "raid_level"),
    ("storage", "disks"),
    ("storage", "mount"),
    ("storage", "md"),
    ("nfs", "clients"),
    ("ntp", "server"),
    ("ntp", "stratum"),
    ("docker", "port"),
    ("modules",),
) + tuple(("hosts", name) for name in intake_parser.HOST_NAMES)


def _dig(data, path: tuple[str, ...]):
    node = data
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _canon(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value).strip()


def _variant_changes(previous: dict | None, incoming: dict | None) -> dict:
    """Fields the user edited by hand (incoming differs from stored variant)."""
    changes: dict = {}
    if not isinstance(incoming, dict):
        return changes
    for path in VARIANT_PATHS:
        new_value = _dig(incoming, path)
        if new_value is None:
            continue
        old_value = _dig(previous or {}, path)
        if _canon(new_value) != _canon(old_value):
            changes[".".join(path)] = new_value
    return changes


def _apply_user_sources(sources, changes: dict, normalized: dict | None = None) -> list[dict]:
    if isinstance(sources, dict):
        sources = intake_parser.source_entries(sources)

    def current_value(key: str, fallback):
        if not isinstance(normalized, dict):
            return fallback
        value = _dig(normalized, tuple(key.split(".")))
        return fallback if value is None else value

    result: list[dict] = []
    seen: set[str] = set()
    for item in sources or []:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not key:
            continue
        origin = "user" if key in changes else item.get("source", "exam")
        result.append({
            **item,
            "value": current_value(key, item.get("value")),
            "source": origin,
        })
        seen.add(key)
    for key, value in changes.items():
        if key not in seen:
            result.append({
                "key": key,
                "label": intake_parser.source_label(key),
                "value": current_value(key, value),
                "source": "user",
            })
    return intake_parser.add_method_sources(result, normalized)


def _step_response(user_id: str, plan: list[dict], idx: int, can_advance: bool) -> dict:
    return {
        "step": compiler_service.step_payload(plan, idx),
        "progress": _progress(idx, len(plan), can_advance),
    }


def _save_intake(user_id: str, result: dict, text: str = "") -> None:
    chat = _ensure_chat(user_id)
    old_plan = compiler_service.plan_from_json(chat["plan"])
    stored = int(chat["current_idx"] or 0)
    anchor = old_plan[stored - 1].get("id") if 1 <= stored <= len(old_plan) else None
    _update_chat(
        user_id,
        variant=_json_dump(result["variant"]),
        sources=_json_dump(result["sources"]),
        unknown=_json_dump(result["unknown"]),
        plan=None,
        current_idx=0,
        can_advance=0,
        phase="confirm",
        intake_text=text,
        anchor_id=anchor,
    )


def _intake_stream(user_id: str, text: str) -> StreamingResponse:
    chat = _ensure_chat(user_id)
    base = _json_load(chat["variant"], {}) or {}
    result = intake_parser.parse_assignment(text, base)
    _save_intake(user_id, result, text)
    _save_message(user_id, "user", "edit_variant", text, 0)

    meta = {"intent": "edit_variant", "step_num": 0, "model": llm.model_for()}
    done = {
        "phase": "confirm",
        "can_advance": False,
        "progress": _progress(0, 0, False),
        "variant": result["variant"],
        "sources": result["sources"],
        "unknown": result["unknown"],
        "warnings": result["warnings"],
    }

    def generate() -> Iterator[str]:
        yield _sse("meta", meta)
        yield _sse("done", done)

    log.info("intake user=%s sources=%s", user_id, len(result["sources"]))
    return StreamingResponse(generate(), media_type="text/event-stream", headers=SSE_HEADERS)


def _chat_events(user: dict, chat: dict, plan: list[dict], text: str) -> Iterator[str]:
    user_id = user["id"]
    idx = int(chat["current_idx"] or 0)
    total = len(plan)
    context = compiler_service.step_context(plan, idx)
    raw_step = plan[idx - 1] if 1 <= idx <= total else None

    try:
        decision = llm.classify(text, context=context)
    except Exception:  # noqa: BLE001 - the chat must stay alive
        log.exception("classifier crashed")
        decision = {"intent": "question", "target": None}

    intent = decision.get("intent") or "question"
    target = decision.get("target")
    log.info("chat user=%s intent=%s target=%s idx=%s", user_id, intent, target, idx)

    # ---- navigation intents: no model call ----------------------------- #
    if intent in {"advance", "jump", "restart"}:
        if intent == "advance":
            new_idx = 1 if idx < 1 else min(idx + 1, total)
        elif intent == "restart":
            new_idx = 1
        else:
            new_idx = compiler_service.find_index(plan, target)
            if new_idx is None:
                _save_message(user_id, "user", intent, text, idx)
                yield _sse("meta", {"intent": intent, "step_num": idx, "model": llm.model_for()})
                yield _sse("delta", {
                    "text": f"Не нашёл шаг «{target}». Укажите номер от 1 до {total} или id вида 2.3."
                })
                yield _sse("done", {
                    "can_advance": True,
                    "progress": _progress(idx, total, True),
                })
                return

        _update_chat(user_id, current_idx=new_idx, can_advance=1)
        _save_message(user_id, "user", intent, text, idx)
        yield _sse("meta", {"intent": intent, "step_num": new_idx, "model": llm.model_for()})
        yield _sse("step", compiler_service.step_payload(plan, new_idx) or {})
        yield _sse("done", {
            "can_advance": True,
            "progress": _progress(new_idx, total, True),
        })
        return

    # ---- variant edit: ask for a new assignment ------------------------ #
    if intent == "edit_variant":
        _update_chat(user_id, phase="intake")
        _save_message(user_id, "user", intent, text, idx)
        yield _sse("meta", {"intent": intent, "step_num": idx, "model": llm.model_for()})
        yield _sse("delta", {
            "text": "Пришлите новое задание одним сообщением — я пересоберу карточку."
        })
        yield _sse("done", {
            "phase": "intake",
            "can_advance": False,
            "progress": _progress(idx, total, False),
        })
        return

    # ---- question / error / off_topic: stream the model, step stays ---- #
    model = llm.model_for(intent)
    yield _sse("meta", {"intent": intent, "step_num": idx, "model": model})
    _save_message(user_id, "user", intent, text, idx)

    pieces: list[str] = []
    try:
        for piece in llm.answer_stream(
            text,
            intent,
            context=context,
            step=raw_step,
            history=_history(user_id),
        ):
            if not piece:
                continue
            pieces.append(piece)
            yield _sse("delta", {"text": piece})
    except Exception:  # noqa: BLE001
        log.exception("answer stream crashed")
        if not pieces:
            fallback = "Модель временно недоступна, повторите запрос."
            pieces.append(fallback)
            yield _sse("delta", {"text": fallback})

    answer = "".join(pieces).strip()
    if answer:
        _save_message(user_id, "assistant", intent, answer, idx)
    yield _sse("done", {
        "can_advance": True,
        "progress": _progress(idx, total, True),
    })


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    log.info("db ready: %s", settings.db_path)
    log.info("llm mode: %s", "mock" if settings.mock_llm else settings.model_main)
    yield


app = FastAPI(title="lab-chat", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - started) * 1000
    log.info("%s %s -> %s (%.0f ms)", request.method, request.url.path, response.status_code, elapsed)
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("code") or "http_error")
        message = str(detail.get("message") or code)
    else:
        code = "http_error" if exc.status_code != 404 else "not_found"
        message = str(detail)
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=exc.status_code,
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        {"error": {"code": "bad_request", "message": "Некорректное тело запроса"}},
        status_code=400,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        {"error": {"code": "internal", "message": "Внутренняя ошибка сервера"}},
        status_code=500,
    )


# ------------------------------- auth -------------------------------------- #
@app.post("/api/login")
def login(payload: LoginIn, response: Response):
    username = payload.username.strip()
    row = auth.find_user(username)
    if not row or not auth.verify_password(payload.password, row.get("pass_hash")):
        raise HTTPException(
            401, detail={"code": "bad_credentials", "message": "Неверный логин или пароль"}
        )
    token = auth.create_session(row["id"])
    auth.set_session_cookie(response, token)
    log.info("login ok user=%s", row["username"])
    return {
        "user": {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
        }
    }


@app.post("/api/logout")
def logout(request: Request, response: Response):
    auth.destroy_session(request.cookies.get(auth.COOKIE_NAME))
    auth.clear_session_cookie(response)
    response.status_code = 204
    return response


# ------------------------------ state -------------------------------------- #
@app.get("/api/state")
def get_state(user: dict = Depends(auth.current_user)):
    chat = _ensure_chat(user["id"])
    plan = compiler_service.plan_from_json(chat["plan"])
    idx = int(chat["current_idx"] or 0)
    return {
        "user": user,
        "phase": chat["phase"] or "intake",
        "variant": _json_load(chat["variant"], None),
        "sources": _json_load(chat["sources"], {}),
        "unknown": _json_load(chat["unknown"], []),
        "intake_text": chat["intake_text"] or "",
        "progress": _progress(idx, len(plan), bool(chat["can_advance"])),
        "step": compiler_service.step_payload(plan, idx),
    }


# ----------------------------- intake -------------------------------------- #
@app.post("/api/intake")
def intake(payload: IntakeIn, user: dict = Depends(auth.current_user)):
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(400, detail={"code": "empty_text", "message": "Пустой текст задания"})
    chat = _ensure_chat(user["id"])
    base = _json_load(chat["variant"], {}) or {}
    result = intake_parser.parse_assignment(text, base)
    _save_intake(user["id"], result, text)
    _save_message(user["id"], "user", "intake", text, 0)
    log.info("intake user=%s sources=%s", user["id"], len(result["sources"]))
    return result


@app.post("/api/intake/confirm")
def intake_confirm(payload: ConfirmIn, user: dict = Depends(auth.current_user)):
    chat = _ensure_chat(user["id"])
    previous = _json_load(chat["variant"], {}) or {}
    changes = _variant_changes(previous, payload.variant)
    preserve = {"storage.mount"} if "storage.mount" in changes else set()
    plan, normalized = _compile_or_400(payload.variant, preserve)

    # Re-confirming the same variant must not throw the user back to step 1
    # (double click, reload, second tab). A real change keeps the current step
    # when its id still exists in the new plan.
    old_plan = compiler_service.plan_from_json(chat["plan"])
    stored = int(chat["current_idx"] or 0)
    anchor_id = chat["anchor_id"] or None
    if 1 <= stored <= len(old_plan):
        anchor_id = old_plan[stored - 1].get("id")

    same_plan = bool(plan) and chat["phase"] == "chat" and not changes and 1 <= stored <= len(plan)
    if same_plan:
        idx = min(stored, len(plan))
    elif plan and anchor_id:
        idx = next(
            (position for position, step in enumerate(plan, start=1) if step.get("id") == anchor_id),
            1,
        )
    else:
        idx = 1 if plan else 0
    can_advance = 1 if plan else 0
    sources = _apply_user_sources(_json_load(chat["sources"], []), changes, normalized)
    _update_chat(
        user["id"],
        variant=_json_dump(normalized),
        sources=_json_dump(sources),
        plan=compiler_service.plan_to_json(plan),
        current_idx=idx,
        can_advance=can_advance,
        phase="chat",
        anchor_id=None,
    )
    if changes:
        log.info("confirm user=%s steps=%s idx=%s manual=%s", user["id"], len(plan), idx, sorted(changes))
    else:
        log.info("confirm user=%s steps=%s idx=%s", user["id"], len(plan), idx)
    return _step_response(user["id"], plan, idx, bool(can_advance))


# ------------------------------ chat --------------------------------------- #
@app.post("/api/chat")
def chat(payload: ChatIn, user: dict = Depends(auth.current_user)):
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(400, detail={"code": "empty_text", "message": "Пустое сообщение"})
    client_msg_id = (payload.client_msg_id or "").strip() or None
    if not _mark_seen(user["id"], client_msg_id):
        raise HTTPException(
            409, detail={"code": "duplicate", "message": "Это сообщение уже обработано"}
        )

    chat_row = _ensure_chat(user["id"])
    plan = compiler_service.plan_from_json(chat_row["plan"])
    if chat_row["phase"] != "chat" or not plan:
        return _intake_stream(user["id"], text)
    return StreamingResponse(
        _chat_events(user, chat_row, plan, text),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# --------------------------- navigation ------------------------------------ #
@app.post("/api/next")
def next_step(payload: NextIn, user: dict = Depends(auth.current_user)):
    if not _mark_seen(user["id"], payload.client_msg_id):
        raise HTTPException(
            409, detail={"code": "duplicate", "message": "Это сообщение уже обработано"}
        )
    chat_row = _ensure_chat(user["id"])
    plan = compiler_service.plan_from_json(chat_row["plan"])
    if not plan or not chat_row["can_advance"]:
        raise HTTPException(409, detail={"code": "not_ready", "message": "План ещё не готов"})

    idx = int(chat_row["current_idx"] or 0)
    new_idx = 1 if idx < 1 else min(idx + 1, len(plan))
    _update_chat(user["id"], current_idx=new_idx, can_advance=1, phase="chat")
    return _step_response(user["id"], plan, new_idx, True)


@app.post("/api/jump")
def jump(payload: JumpIn, user: dict = Depends(auth.current_user)):
    chat_row = _ensure_chat(user["id"])
    plan = compiler_service.plan_from_json(chat_row["plan"])
    if not plan or not chat_row["can_advance"]:
        raise HTTPException(409, detail={"code": "not_ready", "message": "План ещё не готов"})
    new_idx = compiler_service.find_index(plan, payload.to)
    if new_idx is None:
        raise HTTPException(
            400,
            detail={
                "code": "bad_target",
                "message": f"Шаг не найден, допустимо 1..{len(plan)} или id вида 2.3",
            },
        )
    _update_chat(user["id"], current_idx=new_idx, can_advance=1, phase="chat")
    return _step_response(user["id"], plan, new_idx, True)


@app.post("/api/restart")
def restart(user: dict = Depends(auth.current_user)):
    chat_row = _ensure_chat(user["id"])
    plan = compiler_service.plan_from_json(chat_row["plan"])
    if not plan:
        raise HTTPException(409, detail={"code": "not_ready", "message": "План ещё не готов"})
    _update_chat(user["id"], current_idx=1, can_advance=1, phase="chat")
    return _step_response(user["id"], plan, 1, True)


@app.post("/api/variant")
def set_variant(payload: VariantIn, user: dict = Depends(auth.current_user)):
    chat = _ensure_chat(user["id"])
    previous = _json_load(chat["variant"], {}) or {}
    changes = _variant_changes(previous, payload.variant)
    preserve = {"storage.mount"} if "storage.mount" in changes else set()
    plan, normalized = _compile_or_400(payload.variant, preserve)
    idx = 1 if plan else 0
    can_advance = 1 if plan else 0
    sources = _apply_user_sources(_json_load(chat["sources"], []), changes, normalized)
    _update_chat(
        user["id"],
        variant=_json_dump(normalized),
        sources=_json_dump(sources),
        plan=compiler_service.plan_to_json(plan),
        current_idx=idx,
        can_advance=can_advance,
        phase="chat",
    )
    log.info("variant user=%s steps=%s", user["id"], len(plan))
    return _step_response(user["id"], plan, idx, bool(can_advance))


# ------------------------------ static ------------------------------------- #
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/download/labchat.py")
def download_cli():
    if not CLI_FILE.exists():
        return JSONResponse(status_code=404, content={"error": {"code": "not_found"}})
    return FileResponse(CLI_FILE, media_type="text/x-python", filename="labchat.py")


@app.get("/download/labchat-offline.py")
def download_cli_offline():
    offline = ROOT / "cli" / "labchat-offline.py"
    if not offline.exists():
        return JSONResponse(status_code=404, content={"error": {"code": "not_found"}})
    return FileResponse(offline, media_type="text/x-python", filename="labchat-offline.py")


@app.get("/")
def index():
    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse(
        {
            "service": "lab-chat",
            "status": "ok",
            "message": "web/index.html ещё не создан, API работает",
        }
    )


if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

# Mounted last: exact /api routes above always win over this catch-all.
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
