import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


DEFAULT_DB_PATH = "events.db"


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def normalize_event_row(row: sqlite3.Row) -> Dict[str, Any]:
    event = dict(row)
    raw_fragments = event.get("raw_fragments") or "[]"
    try:
        event["raw_fragments"] = json.loads(raw_fragments)
    except json.JSONDecodeError:
        event["raw_fragments"] = []
    return event


class Database:
    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    calendar_event_id TEXT,
                    title TEXT NOT NULL,
                    date TEXT,
                    time TEXT,
                    location TEXT,
                    syllabus TEXT,
                    description TEXT,
                    status TEXT DEFAULT 'pending',
                    raw_fragments TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.commit()

    def get_last_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM events
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [normalize_event_row(row) for row in rows]

    def get_event(self, event_id: int) -> Optional[Dict[str, Any]]:
        with closing(self.connect()) as conn:
            row = conn.execute(
                "SELECT * FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()
        return normalize_event_row(row) if row else None

    def insert_event(self, event_data: Dict[str, Any], raw_message: str) -> int:
        timestamp = utc_now_iso()
        raw_fragments = json.dumps([raw_message], ensure_ascii=False)
        with closing(self.connect()) as conn:
            cursor = conn.execute(
                """
                INSERT INTO events (
                    calendar_event_id, title, date, time, location, syllabus,
                    description, status, raw_fragments, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_data.get("calendar_event_id"),
                    event_data["title"],
                    event_data.get("date"),
                    event_data.get("time"),
                    event_data.get("location"),
                    event_data.get("syllabus"),
                    event_data.get("description"),
                    event_data["status"],
                    raw_fragments,
                    timestamp,
                    timestamp,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_event(
        self,
        event_id: int,
        updated_fields: Dict[str, Any],
        raw_fragments: Optional[List[str]] = None,
    ) -> None:
        fields = dict(updated_fields)
        if raw_fragments is not None:
            fields["raw_fragments"] = json.dumps(raw_fragments, ensure_ascii=False)
        fields["updated_at"] = utc_now_iso()

        set_clause = ", ".join(f"{column} = ?" for column in fields)
        values = list(fields.values()) + [event_id]

        with closing(self.connect()) as conn:
            conn.execute(
                f"UPDATE events SET {set_clause} WHERE id = ?",
                values,
            )
            conn.commit()

    def get_pending_or_partial_events(self) -> List[Dict[str, Any]]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM events
                WHERE status IN ('pending', 'partial')
                ORDER BY COALESCE(date, substr(created_at, 1, 10)) ASC, id ASC
                """
            ).fetchall()
        return [normalize_event_row(row) for row in rows]

    def get_recent_events(self, days: int = 30) -> List[Dict[str, Any]]:
        cutoff = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM events
                WHERE (date IS NOT NULL AND date >= ?)
                   OR (date IS NULL AND substr(created_at, 1, 10) >= ?)
                ORDER BY COALESCE(date, substr(created_at, 1, 10)) DESC, id DESC
                """,
                (cutoff, cutoff),
            ).fetchall()
        return [normalize_event_row(row) for row in rows]
