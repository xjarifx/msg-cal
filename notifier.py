from datetime import datetime
from typing import Dict, List


def _format_date(event: Dict) -> str:
    date_value = event.get("date")
    if not date_value:
        return "date not set"
    try:
        dt = datetime.strptime(date_value, "%Y-%m-%d")
        return dt.strftime("%b %d")
    except ValueError:
        return date_value


def build_digest(events: List[Dict]) -> str:
    if not events:
        return "No pending or partial academic notices."

    lines = ["📋 Pending notices:"]
    for event in events:
        if event["status"] == "pending":
            lines.append(f"- {event['title']} — date not set")
            continue

        missing = []
        if not event.get("syllabus"):
            missing.append("syllabus TBA")
        if not event.get("time"):
            missing.append("time TBA")
        if not event.get("location"):
            missing.append("location TBA")

        detail = " · ".join([_format_date(event)] + missing)
        lines.append(f"- {event['title']} — {detail}")

    return "\n".join(lines)


def build_all_events_digest(events: List[Dict]) -> str:
    if not events:
        return "No events found in the last 30 days."

    lines = ["All tracked events from the last 30 days:"]
    for event in events:
        date_part = _format_date(event)
        time_part = event.get("time") or "all-day/TBA"
        lines.append(
            f"- #{event['id']} [{event['status']}] {event['title']} — {date_part} · {time_part}"
        )
    return "\n".join(lines)
