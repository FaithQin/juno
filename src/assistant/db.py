"""SQLite state.

The sync must never create a duplicate, so it remembers two things:

  item_links  one row per Canvas item (assignment or quiz) → the Todoist task
              that represents it, plus the due date Canvas reported last time
              (so a *Canvas-side* change is detectable without touching what
              you may have edited in Todoist).
  tasks       one row per Todoist task the sync knows about: whether the sync
              created it ("managed") or adopted a hand-made one, and the batch
              key so new quizzes can join an existing weekly task.

Plain sqlite3 from the standard library; no ORM. Everything is small.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS item_links (
    kind        TEXT    NOT NULL,          -- 'assignment' | 'quiz'
    canvas_id   INTEGER NOT NULL,
    course_id   INTEGER,
    task_id     TEXT    NOT NULL,
    adopted     INTEGER NOT NULL DEFAULT 0, -- 1 = task existed before the sync saw it
    name        TEXT,
    due_at      TEXT,                       -- Canvas due date at last sync, ISO UTC
    submitted   INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT    NOT NULL,
    PRIMARY KEY (kind, canvas_id)
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id     TEXT PRIMARY KEY,
    batch_key   TEXT,
    managed     INTEGER NOT NULL DEFAULT 0, -- 1 = created by the sync
    content     TEXT,
    description TEXT,
    due_at      TEXT,
    completed   INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_batch_key ON tasks(batch_key);
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job         TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    ok          INTEGER,
    summary     TEXT
);

-- phase 2: chat, memory, nudges, undo
CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    deleted_at  TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    payload         BLOB NOT NULL          -- pydantic-ai ModelMessage list as JSON
);
CREATE INDEX IF NOT EXISTS messages_conv ON messages(conversation_id, created_at);
CREATE TABLE IF NOT EXISTS nudges_sent (
    key         TEXT PRIMARY KEY,           -- "<task_id>:24h" etc.
    sent_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snoozes (
    task_id     TEXT PRIMARY KEY,
    at          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    payload     TEXT NOT NULL,              -- JSON, enough to reverse the action
    created_at  TEXT NOT NULL,
    undone_at   TEXT
);
CREATE TABLE IF NOT EXISTS kv (
    key         TEXT PRIMARY KEY,
    value       TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ItemLink:
    kind: str
    canvas_id: int
    course_id: int | None
    task_id: str
    adopted: bool
    name: str | None
    due_at: str | None
    submitted: bool

    @property
    def key(self) -> tuple[str, int]:
        return (self.kind, self.canvas_id)


@dataclass
class Fact:
    id: int
    text: str
    created_at: str


@dataclass
class Action:
    id: int
    kind: str
    payload: dict
    created_at: str


@dataclass
class TaskRow:
    task_id: str
    batch_key: str | None
    managed: bool
    content: str | None
    description: str | None
    due_at: str | None
    completed: bool


class Store:
    """One connection per thread. pydantic-ai runs tools on worker threads and
    APScheduler runs sync jobs on a pool, and sqlite3 connections must not
    cross threads. WAL mode lets readers and a writer coexist."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._local = threading.local()
        with self.conn:
            self.conn.executescript(SCHEMA)

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=5)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    # -- reads ---------------------------------------------------------------

    def links(self) -> dict[tuple[str, int], ItemLink]:
        rows = self.conn.execute("SELECT * FROM item_links").fetchall()
        out: dict[tuple[str, int], ItemLink] = {}
        for r in rows:
            link = ItemLink(
                kind=r["kind"], canvas_id=r["canvas_id"], course_id=r["course_id"],
                task_id=r["task_id"], adopted=bool(r["adopted"]), name=r["name"],
                due_at=r["due_at"], submitted=bool(r["submitted"]),
            )
            out[link.key] = link
        return out

    def tasks(self) -> dict[str, TaskRow]:
        rows = self.conn.execute("SELECT * FROM tasks").fetchall()
        return {
            r["task_id"]: TaskRow(
                task_id=r["task_id"], batch_key=r["batch_key"], managed=bool(r["managed"]),
                content=r["content"], description=r["description"], due_at=r["due_at"],
                completed=bool(r["completed"]),
            )
            for r in rows
        }

    # -- writes --------------------------------------------------------------

    def link(self, kind: str, canvas_id: int, course_id: int | None, task_id: str, *,
             adopted: bool, name: str | None, due_at: str | None, submitted: bool) -> None:
        self.conn.execute(
            """INSERT INTO item_links (kind, canvas_id, course_id, task_id, adopted, name, due_at, submitted, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(kind, canvas_id) DO UPDATE SET
                 task_id=excluded.task_id, name=excluded.name, due_at=excluded.due_at,
                 submitted=excluded.submitted, updated_at=excluded.updated_at""",
            (kind, canvas_id, course_id, task_id, int(adopted), name, due_at, int(submitted), _now()),
        )
        self.conn.commit()

    def upsert_task(self, task_id: str, *, batch_key: str | None, managed: bool, content: str | None,
                    description: str | None, due_at: str | None, completed: bool) -> None:
        self.conn.execute(
            """INSERT INTO tasks (task_id, batch_key, managed, content, description, due_at, completed, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(task_id) DO UPDATE SET
                 batch_key=COALESCE(excluded.batch_key, tasks.batch_key),
                 content=excluded.content, description=excluded.description,
                 due_at=excluded.due_at, completed=excluded.completed, updated_at=excluded.updated_at""",
            (task_id, batch_key, int(managed), content, description, due_at, int(completed), _now()),
        )
        self.conn.commit()

    def start_run(self, job: str) -> int:
        cur = self.conn.execute("INSERT INTO runs (job, started_at) VALUES (?, ?)", (job, _now()))
        self.conn.commit()
        return int(cur.lastrowid)

    def last_run(self, job: str) -> tuple[datetime, bool] | None:
        r = self.conn.execute(
            "SELECT finished_at, ok FROM runs WHERE job=? AND finished_at IS NOT NULL ORDER BY id DESC LIMIT 1", (job,)
        ).fetchone()
        return (datetime.fromisoformat(r["finished_at"]), bool(r["ok"])) if r else None

    def finish_run(self, run_id: int, ok: bool, summary: str) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, ok=?, summary=? WHERE id=?",
            (_now(), int(ok), summary, run_id),
        )
        self.conn.commit()

    # -- phase 2: facts memory ----------------------------------------------

    def remember(self, text: str, *, now: datetime | None = None) -> int:
        at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        cur = self.conn.execute("INSERT INTO facts (text, created_at) VALUES (?, ?)", (text.strip(), at))
        self.conn.commit()
        return int(cur.lastrowid)

    def facts(self) -> list[Fact]:
        rows = self.conn.execute(
            "SELECT id, text, created_at FROM facts WHERE deleted_at IS NULL ORDER BY id"
        ).fetchall()
        return [Fact(r["id"], r["text"], r["created_at"]) for r in rows]

    def find_facts(self, query: str) -> list[Fact]:
        q = f"%{query.strip().lower()}%"
        rows = self.conn.execute(
            "SELECT id, text, created_at FROM facts WHERE deleted_at IS NULL AND lower(text) LIKE ? ORDER BY id", (q,)
        ).fetchall()
        return [Fact(r["id"], r["text"], r["created_at"]) for r in rows]

    def forget(self, fact_id: int) -> None:
        self.conn.execute("UPDATE facts SET deleted_at=? WHERE id=?", (_now(), fact_id))
        self.conn.commit()

    # -- phase 2: conversation history --------------------------------------

    def save_messages(self, conversation_id: str, payload: bytes, *, at: datetime | None = None) -> None:
        stamp = (at or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        self.conn.execute(
            "INSERT INTO messages (conversation_id, created_at, payload) VALUES (?, ?, ?)",
            (conversation_id, stamp, payload),
        )
        self.conn.commit()

    def load_messages(self, conversation_id: str, *, since: datetime) -> list[bytes]:
        rows = self.conn.execute(
            "SELECT payload FROM messages WHERE conversation_id=? AND created_at>=? ORDER BY id",
            (conversation_id, since.isoformat(timespec="seconds")),
        ).fetchall()
        return [bytes(r["payload"]) for r in rows]

    # -- phase 2: nudges and snoozes ----------------------------------------

    def sent_nudges(self) -> set[str]:
        return {r["key"] for r in self.conn.execute("SELECT key FROM nudges_sent").fetchall()}

    def mark_nudge(self, key: str, *, at: datetime | None = None) -> None:
        stamp = (at or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        self.conn.execute("INSERT OR IGNORE INTO nudges_sent (key, sent_at) VALUES (?, ?)", (key, stamp))
        self.conn.commit()

    def snoozes(self) -> dict[str, datetime]:
        rows = self.conn.execute("SELECT task_id, at FROM snoozes").fetchall()
        return {r["task_id"]: datetime.fromisoformat(r["at"]) for r in rows}

    def set_snooze(self, task_id: str, at: datetime) -> None:
        self.conn.execute(
            "INSERT INTO snoozes (task_id, at) VALUES (?, ?) ON CONFLICT(task_id) DO UPDATE SET at=excluded.at",
            (task_id, at.isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def clear_snooze(self, task_id: str) -> None:
        self.conn.execute("DELETE FROM snoozes WHERE task_id=?", (task_id,))
        self.conn.commit()

    # -- phase 2: undo log ---------------------------------------------------

    def log_action(self, kind: str, payload: dict, *, at: datetime | None = None) -> int:
        stamp = (at or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        cur = self.conn.execute(
            "INSERT INTO actions (kind, payload, created_at) VALUES (?, ?, ?)", (kind, json.dumps(payload), stamp)
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def last_undoable(self) -> Action | None:
        r = self.conn.execute(
            "SELECT id, kind, payload, created_at FROM actions WHERE undone_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return Action(r["id"], r["kind"], json.loads(r["payload"]), r["created_at"]) if r else None

    def mark_undone(self, action_id: int) -> None:
        self.conn.execute("UPDATE actions SET undone_at=? WHERE id=?", (_now(), action_id))
        self.conn.commit()

    # -- phase 2: key/value ---------------------------------------------------

    def kv_get(self, key: str) -> str | None:
        r = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return r["value"] if r else None

    def kv_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value)
        )
        self.conn.commit()
