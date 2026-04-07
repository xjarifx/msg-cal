import logging
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatType
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

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


async def maybe_send_digest(application: Application, db: Database) -> None:
    notify_chat_id = os.getenv("NOTIFY_CHAT_ID")
    if not notify_chat_id:
        return
    try:
        events = db.get_pending_or_partial_events()
    except Exception as exc:
        logging.exception("Failed to fetch digest events: %s", exc)
        return
    try:
        await application.bot.send_message(chat_id=notify_chat_id, text=build_digest(events))
    except Exception as exc:
        logging.exception("Failed to send digest: %s", exc)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user
    lines = [f"Current chat ID: {chat.id}"]
    if user:
        lines.append(f"Your user ID: {user.id}")
    await update.effective_message.reply_text("\n".join(lines))


async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    try:
        events = db.get_pending_or_partial_events()
    except Exception as exc:
        logging.exception("Failed to load pending events: %s", exc)
        await update.effective_message.reply_text("Failed to load pending events.")
        return
    await update.effective_message.reply_text(build_digest(events))


async def all_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    try:
        events = db.get_recent_events(days=30)
    except Exception as exc:
        logging.exception("Failed to load recent events: %s", exc)
        await update.effective_message.reply_text("Failed to load recent events.")
        return
    await update.effective_message.reply_text(build_all_events_digest(events))


async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    message = update.effective_message
    chat = update.effective_chat
    message_text = message.text or message.caption or ""
    today_iso = datetime.now().date().isoformat()

    if not message_text.strip():
        return
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    try:
        parsed = parse_notice(message_text=message_text, today_iso=today_iso)
        if not parsed.get("is_event"):
            return
        if not parsed.get("title"):
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
            }
            event_record["raw_fragments"] = [message_text]
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

        await maybe_send_digest(context.application, db)
    except Exception as exc:
        logging.exception("Notice processing failed: %s", exc)
        log_failure(message_text, str(exc))


def main() -> None:
    load_dotenv()
    setup_logging()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing")

    db = Database(os.getenv("DATABASE_URL", ""))
    try:
        db.initialize()
    except Exception as exc:
        logging.exception("Database initialization failed: %s", exc)
        raise

    application = Application.builder().token(token).build()
    application.bot_data["db"] = db

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("pending", pending_command))
    application.add_handler(CommandHandler("all", all_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, process_message)
    )

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
