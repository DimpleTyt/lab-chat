"""SQLite access layer (stdlib sqlite3, no ORM)."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable, Iterator

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    pass_hash TEXT NOT NULL,
    display_name TEXT
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS chats (
    user_id TEXT PRIMARY KEY,
    variant TEXT,
    sources TEXT,
    unknown TEXT,
    plan TEXT,
    current_idx INTEGER DEFAULT 0,
    can_advance INTEGER DEFAULT 0,
    phase TEXT DEFAULT 'intake',
    updated_at INTEGER
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    kind TEXT,
    content TEXT NOT NULL,
    step_num INTEGER,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS seen (
    user_id TEXT NOT NULL,
    client_msg_id TEXT NOT NULL,
    PRIMARY KEY (user_id, client_msg_id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON auth_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_messages_user_time ON messages(user_id, created_at);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """One short-lived connection per operation. WAL handles concurrency."""
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.db_path), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.executescript(SCHEMA)


def get(sql: str, params: Iterable[Any] = ()) -> dict | None:
    with connect() as conn:
        row = conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row is not None else None


def all(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with connect() as conn:
        cursor = conn.execute(sql, tuple(params))
        return cursor.rowcount


def insert(sql: str, params: Iterable[Any] = ()) -> int:
    with connect() as conn:
        cursor = conn.execute(sql, tuple(params))
        return int(cursor.lastrowid or 0)
