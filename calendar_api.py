import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_timezone() -> str:
    return os.getenv("CALENDAR_TIMEZONE", "Asia/Dhaka")


def get_calendar_service():
    creds = None
    token_path = "token.json"
    credentials_path = "credentials.json"

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def missing_fields(event_data: Dict[str, Any]) -> List[str]:
    missing = []
    if not event_data.get("time"):
        missing.append("time")
    if not event_data.get("syllabus"):
        missing.append("syllabus")
    if not event_data.get("location"):
        missing.append("location")
    return missing


def status_for_event(event_data: Dict[str, Any]) -> str:
    if not event_data.get("date"):
        return "pending"
    if missing_fields(event_data):
        return "partial"
    return "confirmed"


def calendar_title(event_data: Dict[str, Any]) -> str:
    title = event_data["title"].strip()
    if event_data["status"] == "partial" and "[incomplete]" not in title:
        return f"{title} [incomplete]"
    return title.replace(" [incomplete]", "")


def build_description(event_data: Dict[str, Any]) -> str:
    parts: List[str] = []
    if event_data.get("description"):
        parts.append(str(event_data["description"]).strip())
    if event_data.get("syllabus"):
        parts.append(f"Syllabus: {event_data['syllabus']}")

    if event_data["status"] == "partial":
        missing = ", ".join(missing_fields(event_data))
        parts.append(f"Missing fields: {missing}")

    fragments = event_data.get("raw_fragments") or []
    if fragments:
        source_lines = "\n".join(f"- {fragment}" for fragment in fragments)
        parts.append(f"Source fragments:\n{source_lines}")

    return "\n\n".join(parts).strip()


def build_event_body(event_data: Dict[str, Any]) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "summary": calendar_title(event_data),
        "description": build_description(event_data),
    }

    if event_data.get("location"):
        body["location"] = event_data["location"]

    timezone = _get_timezone()
    date_value = event_data["date"]
    time_value = event_data.get("time")
    if time_value:
        start_dt = datetime.strptime(f"{date_value} {time_value}", "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(hours=1)
        body["start"] = {"dateTime": start_dt.isoformat(), "timeZone": timezone}
        body["end"] = {"dateTime": end_dt.isoformat(), "timeZone": timezone}
    else:
        next_day = (
            datetime.strptime(date_value, "%Y-%m-%d") + timedelta(days=1)
        ).date().isoformat()
        body["start"] = {"date": date_value}
        body["end"] = {"date": next_day}

    return body


def create_calendar_event(event_data: Dict[str, Any], calendar_id: Optional[str] = None) -> str:
    service = get_calendar_service()
    calendar = calendar_id or os.getenv("GOOGLE_CALENDAR_ID")
    if not calendar:
        raise ValueError("GOOGLE_CALENDAR_ID is missing")
    created = (
        service.events()
        .insert(calendarId=calendar, body=build_event_body(event_data))
        .execute()
    )
    return created["id"]


def diff_event_fields(previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    changed: Dict[str, Any] = {}

    if calendar_title(previous) != calendar_title(current):
        changed["summary"] = calendar_title(current)

    previous_description = build_description(previous)
    current_description = build_description(current)
    if previous_description != current_description:
        changed["description"] = current_description

    if (previous.get("location") or "") != (current.get("location") or ""):
        changed["location"] = current.get("location") or ""

    previous_time = previous.get("time")
    current_time = current.get("time")
    previous_date = previous.get("date")
    current_date = current.get("date")
    if previous_time != current_time or previous_date != current_date:
        body = build_event_body(current)
        changed["start"] = body["start"]
        changed["end"] = body["end"]

    return changed


def patch_calendar_event(
    calendar_event_id: str,
    previous_event: Dict[str, Any],
    current_event: Dict[str, Any],
    calendar_id: Optional[str] = None,
) -> None:
    patch_body = diff_event_fields(previous_event, current_event)
    if not patch_body:
        return

    service = get_calendar_service()
    calendar = calendar_id or os.getenv("GOOGLE_CALENDAR_ID")
    if not calendar:
        raise ValueError("GOOGLE_CALENDAR_ID is missing")

    service.events().patch(
        calendarId=calendar,
        eventId=calendar_event_id,
        body=patch_body,
    ).execute()
