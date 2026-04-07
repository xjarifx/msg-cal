import json
from contextlib import closing
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import psycopg
from psycopg.rows import dict_row


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def normalize_event_row(row: Dict[str, Any]) -> Dict[str, Any]:
    event = dict(row)
    raw_fragments = event.get("raw_fragments") or []
    if isinstance(raw_fragments, str):
        try:
            raw_fragments = json.loads(raw_fragments)
        except json.JSONDecodeError:
            raw_fragments = []
    event["raw_fragments"] = raw_fragments
    return event


class Database:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is missing")
        self.database_url = database_url

    def connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def initialize(self) -> None:
        with closing(self.connect()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        id BIGSERIAL PRIMARY KEY,
                        calendar_event_id TEXT,
                        title TEXT NOT NULL,
                        date TEXT,
                        time TEXT,
                        location TEXT,
                        syllabus TEXT,
                        description TEXT,
                        status TEXT DEFAULT 'pending',
                        raw_fragments JSONB,
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
            conn.commit()

    def get_last_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with closing(self.connect()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM events
                    ORDER BY updated_at DESC, id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
        return [normalize_event_row(row) for row in rows]

    def get_event(self, event_id: int) -> Optional[Dict[str, Any]]:
        with closing(self.connect()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM events WHERE id = %s", (event_id,))
                row = cur.fetchone()
        return normalize_event_row(row) if row else None

    def insert_event(self, event_data: Dict[str, Any], raw_message: str) -> int:
        timestamp = utc_now_iso()
        with closing(self.connect()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO events (
                        calendar_event_id, title, date, time, location, syllabus,
                        description, status, raw_fragments, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
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
                        json.dumps([raw_message], ensure_ascii=False),
                        timestamp,
                        timestamp,
                    ),
                )
                event_id = cur.fetchone()["id"]
            conn.commit()
        return int(event_id)

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

        columns = list(fields.keys())
        set_clause = ", ".join(f"{column} = %s" for column in columns)
        values = [fields[column] for column in columns] + [event_id]

        with closing(self.connect()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE events SET {set_clause} WHERE id = %s",
                    values,
                )
            conn.commit()

    def get_pending_or_partial_events(self) -> List[Dict[str, Any]]:
        with closing(self.connect()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM events
                    WHERE status IN ('pending', 'partial')
                    ORDER BY COALESCE(date, substr(created_at, 1, 10)) ASC, id ASC
                    """
                )
                rows = cur.fetchall()
        return [normalize_event_row(row) for row in rows]

    def get_recent_events(self, days: int = 30) -> List[Dict[str, Any]]:
        cutoff = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
        with closing(self.connect()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM events
                    WHERE (date IS NOT NULL AND date >= %s)
                       OR (date IS NULL AND substr(created_at, 1, 10) >= %s)
                    ORDER BY COALESCE(date, substr(created_at, 1, 10)) DESC, id DESC
                    """,
                    (cutoff, cutoff),
                )
                rows = cur.fetchall()
        return [normalize_event_row(row) for row in rows]
