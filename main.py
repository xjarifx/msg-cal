import argparse
import asyncio
import logging
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError

from calendar_api import create_calendar_event, patch_calendar_event, status_for_event
from database import Database
from notifier import build_all_events_digest, build_digest
from parser import match_existing_event, parse_notice


LOG_PATH = Path("failed_notices.log")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def log_failure(message_text: str, error_text: str) -> None:
    timestamp = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    with LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(
            f"[{timestamp}]\nMESSAGE: {message_text}\nERROR: {error_text}\n\n"
        )


def monotonic_status(previous: str, current: str) -> str:
    order = {"pending": 0, "partial": 1, "confirmed": 2}
    return current if order[current] >= order[previous] else previous


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is missing")
    return value


def optional_int_env(name: str) -> Optional[int]:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    return int(value)


def optional_env(name: str) -> Optional[str]:
    value = os.getenv(name, "").strip()
    return value or None


def merged_event(existing: Dict[str, Any], parsed: Dict[str, Any], raw_message: str) -> Dict[str, Any]:
    merged = deepcopy(existing)
    for field in ("title", "date", "time", "location", "syllabus", "description"):
        if not merged.get(field) and parsed.get(field):
            merged[field] = parsed[field]
    fragments: List[str] = list(existing.get("raw_fragments") or [])
    fragments.append(raw_message)
    merged["raw_fragments"] = fragments
    merged["status"] = monotonic_status(existing["status"], status_for_event(merged))
    return merged


async def send_text(client: TelegramClient, chat_id: int, text: str) -> None:
    try:
        await client.send_message(entity=chat_id, message=text)
    except Exception as exc:
        logging.exception("Failed to send Telegram message to %s: %s", chat_id, exc)


async def maybe_send_digest(client: TelegramClient, db: Database, notify_chat_id: Optional[int]) -> None:
    if notify_chat_id is None:
        return
    try:
        events_list = db.get_pending_or_partial_events()
    except Exception as exc:
        logging.exception("Failed to fetch digest events: %s", exc)
        return
    await send_text(client, notify_chat_id, build_digest(events_list))


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Telegram academic notice to Google Calendar sync")
    parser.add_argument("--list-chats", action="store_true", help="List available Telegram chats and their IDs")
    parser.add_argument("--resolve-chat", help="Resolve a chat name, username, or link to its Telegram ID")
    return parser


async def authenticate_client(client: TelegramClient) -> None:
    await client.connect()
    if await client.is_user_authorized():
        return

    phone = required_env("TELEGRAM_PHONE")
    await client.send_code_request(phone)
    code = input("Enter the Telegram login code: ").strip()
    try:
        await client.sign_in(phone=phone, code=code)
    except SessionPasswordNeededError:
        password = input("Enter your Telegram 2FA password: ").strip()
        await client.sign_in(password=password)


async def list_chats(client: TelegramClient) -> None:
    async for dialog in client.iter_dialogs():
        print(f"{dialog.id}\t{dialog.name}")


async def resolve_chat(client: TelegramClient, target: str) -> None:
    entity = await client.get_entity(target)
    title = getattr(entity, "title", None) or getattr(entity, "username", None) or str(entity.id)
    print(f"{entity.id}\t{title}")


async def resolve_source_chat_id(client: TelegramClient) -> int:
    source_chat_id = optional_int_env("SOURCE_CHAT_ID")
    if source_chat_id is not None:
        return source_chat_id

    source_chat_name = optional_env("SOURCE_CHAT_NAME")
    if not source_chat_name:
        raise ValueError(
            "SOURCE_CHAT_ID or SOURCE_CHAT_NAME is required. "
            "Run `python3 main.py --list-chats` if you need help."
        )

    matches = []
    async for dialog in client.iter_dialogs():
        if dialog.name == source_chat_name:
            matches.append((dialog.id, dialog.name))

    if len(matches) == 1:
        logging.info("Resolved SOURCE_CHAT_NAME '%s' to chat ID %s", source_chat_name, matches[0][0])
        return int(matches[0][0])

    if len(matches) > 1:
        raise ValueError(
            f"Multiple chats matched SOURCE_CHAT_NAME '{source_chat_name}'. "
            "Use SOURCE_CHAT_ID instead."
        )

    entity = await client.get_entity(source_chat_name)
    title = getattr(entity, "title", None) or getattr(entity, "username", None) or str(entity.id)
    logging.info("Resolved SOURCE_CHAT_NAME '%s' to chat ID %s (%s)", source_chat_name, entity.id, title)
    return int(entity.id)


async def reply_to_command(client: TelegramClient, db: Database, chat_id: int, command_text: str) -> None:
    command = command_text.strip().split()[0].lower()
    if command == "/start":
        me = await client.get_me()
        await send_text(client, chat_id, f"Current chat ID: {chat_id}\nYour user ID: {me.id}")
        return
    if command == "/pending":
        try:
            events_list = db.get_pending_or_partial_events()
        except Exception as exc:
            logging.exception("Failed to load pending events: %s", exc)
            await send_text(client, chat_id, "Failed to load pending events.")
            return
        await send_text(client, chat_id, build_digest(events_list))
        return
    if command == "/all":
        try:
            events_list = db.get_recent_events(days=30)
        except Exception as exc:
            logging.exception("Failed to load recent events: %s", exc)
            await send_text(client, chat_id, "Failed to load recent events.")
            return
        await send_text(client, chat_id, build_all_events_digest(events_list))


async def process_notice_message(
    client: TelegramClient,
    db: Database,
    message_text: str,
    notify_chat_id: Optional[int],
) -> None:
    today_iso = datetime.now().date().isoformat()

    try:
        parsed = parse_notice(message_text=message_text, today_iso=today_iso)
        if not parsed.get("is_event") or not parsed.get("title"):
            return

        try:
            recent_events = db.get_last_events(limit=50)
        except Exception as exc:
            logging.exception("Failed to fetch recent events: %s", exc)
            recent_events = []

        match_id = match_existing_event(
            new_event=parsed,
            recent_events=recent_events,
            today_iso=today_iso,
        )

        if match_id is None:
            event_record = {
                "calendar_event_id": None,
                "title": parsed["title"],
                "date": parsed.get("date"),
                "time": parsed.get("time"),
                "location": parsed.get("location"),
                "syllabus": parsed.get("syllabus"),
                "description": parsed.get("description"),
                "raw_fragments": [message_text],
            }
            event_record["status"] = status_for_event(event_record)

            if event_record["status"] in ("partial", "confirmed"):
                try:
                    event_record["calendar_event_id"] = create_calendar_event(event_record)
                except Exception as exc:
                    logging.exception("Calendar creation failed: %s", exc)
                    log_failure(message_text, f"Calendar creation failed: {exc}")

            try:
                db.insert_event(event_record, raw_message=message_text)
            except Exception as exc:
                logging.exception("DB insert failed: %s", exc)
                log_failure(message_text, f"DB insert failed: {exc}")
        else:
            try:
                existing = db.get_event(match_id)
            except Exception as exc:
                logging.exception("DB fetch failed for matched event %s: %s", match_id, exc)
                existing = None

            if not existing:
                return

            previous = deepcopy(existing)
            current = merged_event(existing, parsed, message_text)

            if not previous.get("calendar_event_id") and current["status"] in ("partial", "confirmed"):
                try:
                    current["calendar_event_id"] = create_calendar_event(current)
                except Exception as exc:
                    logging.exception("Calendar creation on promotion failed: %s", exc)
                    log_failure(message_text, f"Calendar creation on promotion failed: {exc}")
            elif previous.get("calendar_event_id") and current["status"] in ("partial", "confirmed"):
                try:
                    patch_calendar_event(previous["calendar_event_id"], previous, current)
                except Exception as exc:
                    logging.exception("Calendar patch failed: %s", exc)
                    log_failure(message_text, f"Calendar patch failed: {exc}")

            try:
                db.update_event(
                    event_id=match_id,
                    updated_fields={
                        "calendar_event_id": current.get("calendar_event_id"),
                        "title": current["title"],
                        "date": current.get("date"),
                        "time": current.get("time"),
                        "location": current.get("location"),
                        "syllabus": current.get("syllabus"),
                        "description": current.get("description"),
                        "status": current["status"],
                    },
                    raw_fragments=current["raw_fragments"],
                )
            except Exception as exc:
                logging.exception("DB update failed: %s", exc)
                log_failure(message_text, f"DB update failed: {exc}")

        await maybe_send_digest(client, db, notify_chat_id)
    except Exception as exc:
        logging.exception("Notice processing failed: %s", exc)
        log_failure(message_text, str(exc))


async def run_monitor(client: TelegramClient, db: Database, source_chat_id: int, notify_chat_id: Optional[int]) -> None:
    logging.info("Monitoring source chat ID %s", source_chat_id)

    @client.on(events.NewMessage(chats=source_chat_id))
    async def source_chat_handler(event):
        if event.out:
            return
        message_text = event.raw_text or ""
        if not message_text.strip():
            return
        await process_notice_message(client, db, message_text, notify_chat_id)

    if notify_chat_id is not None:
        @client.on(events.NewMessage(chats=notify_chat_id, pattern=r"^/(start|pending|all)\b"))
        async def notify_chat_commands(event):
            await reply_to_command(client, db, notify_chat_id, event.raw_text or "")

    await client.run_until_disconnected()


async def async_main(args: argparse.Namespace) -> None:
    load_dotenv()
    setup_logging()

    api_id = int(required_env("TELEGRAM_API_ID"))
    api_hash = required_env("TELEGRAM_API_HASH")
    session_name = os.getenv("TELEGRAM_SESSION_NAME", "telegram_user_session").strip() or "telegram_user_session"

    client = TelegramClient(session_name, api_id, api_hash)
    await authenticate_client(client)

    if args.list_chats:
        await list_chats(client)
        await client.disconnect()
        return

    if args.resolve_chat:
        await resolve_chat(client, args.resolve_chat)
        await client.disconnect()
        return

    db = Database(required_env("DATABASE_URL"))
    try:
        db.initialize()
    except Exception as exc:
        logging.exception("Database initialization failed: %s", exc)
        raise

    source_chat_id = await resolve_source_chat_id(client)
    notify_chat_id = optional_int_env("NOTIFY_CHAT_ID")
    await run_monitor(client, db, source_chat_id, notify_chat_id)


def main() -> None:
    args = build_cli().parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
