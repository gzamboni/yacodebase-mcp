from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .store import _data_dir


def _db_path() -> Path:
    return _data_dir() / "knowledge.db"


def _conn() -> sqlite3.Connection:
    _data_dir().mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_db_path()))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS decisions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            title     TEXT NOT NULL,
            body      TEXT NOT NULL,
            category  TEXT NOT NULL DEFAULT 'general',
            status    TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notes (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            content   TEXT NOT NULL,
            scope     TEXT NOT NULL DEFAULT 'project',
            reference TEXT,
            created_at TEXT NOT NULL
        );
    """)
    con.commit()
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_decision(title: str, body: str, category: str = "general") -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO decisions (title, body, category, status, created_at) VALUES (?,?,?,?,?)",
            (title, body, category, "active", _now()),
        )
        return cur.lastrowid


def search_decisions(query: str = "", category: str = "") -> list[dict]:
    sql = "SELECT * FROM decisions WHERE 1=1"
    params: list = []
    if query:
        sql += " AND (title LIKE ? OR body LIKE ?)"
        params += [f"%{query}%", f"%{query}%"]
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY created_at DESC"
    with _conn() as con:
        rows = con.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def update_decision(decision_id: int, status: str) -> bool:
    with _conn() as con:
        cur = con.execute("UPDATE decisions SET status=? WHERE id=?", (status, decision_id))
        return cur.rowcount > 0


def add_note(content: str, scope: str = "project", reference: str | None = None) -> int:
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO notes (content, scope, reference, created_at) VALUES (?,?,?,?)",
            (content, scope, reference, _now()),
        )
        return cur.lastrowid


def get_notes(scope: str = "") -> list[dict]:
    sql = "SELECT * FROM notes"
    params: list = []
    if scope:
        sql += " WHERE scope = ?"
        params.append(scope)
    sql += " ORDER BY created_at DESC"
    with _conn() as con:
        rows = con.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
