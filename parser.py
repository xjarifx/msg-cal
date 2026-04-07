import json
import logging
import os
from typing import Any, Dict, List, Optional
from urllib import error, request


LOGGER = logging.getLogger(__name__)
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "google/gemini-2.0-flash-exp:free"


def _extract_json_object(payload: str) -> Optional[Dict[str, Any]]:
    payload = payload.strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        start = payload.find("{")
        end = payload.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(payload[start : end + 1])
        except json.JSONDecodeError:
            return None


def _call_openrouter(messages: List[Dict[str, str]], api_key: str) -> Optional[Dict[str, Any]]:
    body = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(body).encode("utf-8")
    req = request.Request(
        OPENROUTER_ENDPOINT,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (error.URLError, error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        LOGGER.exception("OpenRouter request failed: %s", exc)
        return None

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        LOGGER.error("Unexpected OpenRouter payload: %s", payload)
        return None

    parsed = _extract_json_object(content)
    if parsed is None:
        LOGGER.error("Malformed JSON from OpenRouter: %s", content)
    return parsed


def parse_notice(message_text: str, today_iso: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    key = api_key or os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise ValueError("OPENROUTER_API_KEY is missing")

    messages = [
        {
            "role": "system",
            "content": (
                "You extract academic notice data from Telegram messages. "
                "Return only raw valid JSON, with no markdown, no code fences, and no extra text. "
                "Support Bangla and English. Resolve relative dates against the provided today's date. "
                "Never guess missing fields. Use null when absent. "
                "If the message is not an academic event/notice, return {\"is_event\": false}."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Today's date: {today_iso}\n"
                "Extract this Telegram message into JSON with exactly these fields:\n"
                "{\"is_event\": true, \"title\": string|null, \"date\": \"YYYY-MM-DD\"|null, "
                "\"time\": \"HH:MM\"|null, \"location\": string|null, \"syllabus\": string|null, "
                "\"description\": string|null}\n"
                f"Message:\n{message_text}"
            ),
        },
    ]

    parsed = _call_openrouter(messages, key)
    if not parsed:
        return {"is_event": False}

    return {
        "is_event": bool(parsed.get("is_event")),
        "title": parsed.get("title"),
        "date": parsed.get("date"),
        "time": parsed.get("time"),
        "location": parsed.get("location"),
        "syllabus": parsed.get("syllabus"),
        "description": parsed.get("description"),
    }


def match_existing_event(
    new_event: Dict[str, Any],
    recent_events: List[Dict[str, Any]],
    today_iso: str,
    api_key: Optional[str] = None,
) -> Optional[int]:
    if not recent_events:
        return None

    key = api_key or os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise ValueError("OPENROUTER_API_KEY is missing")

    event_summaries = [
        {
            "id": event["id"],
            "title": event["title"],
            "date": event.get("date"),
            "time": event.get("time"),
            "location": event.get("location"),
            "syllabus": event.get("syllabus"),
            "status": event.get("status"),
            "description": event.get("description"),
        }
        for event in recent_events
    ]

    messages = [
        {
            "role": "system",
            "content": (
                "You determine whether a newly parsed academic notice is a new event or an update "
                "to an existing event. Match by topic similarity, subject, and date proximity. "
                "Return only raw valid JSON with no markdown or extra text. "
                "Use exactly this schema: {\"match\": null} or {\"match\": integer}."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Today's date: {today_iso}\n"
                f"New parsed event:\n{json.dumps(new_event, ensure_ascii=False)}\n"
                f"Recent events:\n{json.dumps(event_summaries, ensure_ascii=False)}"
            ),
        },
    ]

    parsed = _call_openrouter(messages, key)
    if not parsed:
        return None

    match_id = parsed.get("match")
    return int(match_id) if isinstance(match_id, int) else None
