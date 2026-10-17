"""SQLite persistence with independent connections and idempotent tool writes."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
                    session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                    email TEXT NOT NULL, name TEXT NOT NULL, message TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
                    session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('feedback','unanswered_question')),
                    question TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
                    session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                    event_type TEXT NOT NULL, payload_json TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def event(self, session_id, turn_id, event_type, payload):
        with self.connect() as db:
            db.execute(
                "INSERT INTO events(created_at,session_id,turn_id,event_type,payload_json) VALUES (?,?,?,?,?)",
                (utc_now(), session_id, turn_id, event_type, json.dumps(payload, ensure_ascii=False)),
            )

    def save_lead(self, session_id, turn_id, key, email, name, message):
        with self.connect() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO leads(created_at,session_id,turn_id,email,name,message,idempotency_key) VALUES (?,?,?,?,?,?,?)",
                (utc_now(), session_id, turn_id, email, name, message, key),
            )
            row = db.execute("SELECT id FROM leads WHERE idempotency_key=?", (key,)).fetchone()
            return {"success": True, "record_id": row["id"], "duplicate": cursor.rowcount == 0}

    def save_feedback(self, session_id, turn_id, key, kind, question):
        with self.connect() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO feedback(created_at,session_id,turn_id,kind,question,idempotency_key) VALUES (?,?,?,?,?,?)",
                (utc_now(), session_id, turn_id, kind, question, key),
            )
            row = db.execute("SELECT id FROM feedback WHERE idempotency_key=?", (key,)).fetchone()
            return {"success": True, "record_id": row["id"], "duplicate": cursor.rowcount == 0}

    def records(self, table, limit=50):
        # Fixed allowlist: never interpolate a user-provided table name.
        if table not in {"leads", "feedback", "events"}:
            raise ValueError("Unknown table")
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,)
            )]
