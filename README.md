# Telegram to Google Calendar Automation

This project monitors a Telegram academic group, extracts event details from messages with OpenRouter AI, tracks each notice in PostgreSQL, and creates or updates matching Google Calendar events.

## Project Structure

```text
project/
├── main.py
├── parser.py
├── calendar_api.py
├── database.py
├── notifier.py
├── .env
├── .env.example
├── credentials.json
├── requirements.txt
└── README.md
```

## Features

- Polls Telegram with `python-telegram-bot` in polling mode.
- Parses Bangla and English academic notices through OpenRouter using `google/gemini-2.0-flash-exp:free`.
- Maintains an event lifecycle in PostgreSQL: `pending`, `partial`, `confirmed`.
- Creates Google Calendar events only when enough data exists.
- Patches existing Google Calendar events as missing details arrive.
- Sends private digest notifications for pending and partial events.
- Logs failures to `failed_notices.log` without crashing the bot.

## 1. Create a Telegram Bot

1. Open Telegram and start a chat with `@BotFather`.
2. Run `/newbot`.
3. Follow the prompts to choose a bot name and username.
4. Copy the bot token BotFather gives you.
5. Put that value into `TELEGRAM_BOT_TOKEN` in `.env`.

## 2. Add the Bot to Your Academic Group

1. Add the bot to the target Telegram group.
2. Disable privacy mode with `@BotFather` if you want the bot to read normal group messages:
   Run `/setprivacy`, choose your bot, then select `Disable`.
3. Send `/start` inside the group.
4. The bot will reply with the current chat ID. Use that if you need to verify the bot is seeing the correct group.

## 3. Get Your Personal Telegram User ID

1. Send `/start` to the bot in a private chat.
2. The reply includes your Telegram user ID.
3. Put that value into `NOTIFY_CHAT_ID` in `.env`.

## 4. Enable Google Calendar API and Download `credentials.json`

1. Go to Google Cloud Console: https://console.cloud.google.com/
2. Create a new project or select an existing one.
3. Open `APIs & Services` -> `Library`.
4. Search for `Google Calendar API` and enable it.
5. Open `APIs & Services` -> `OAuth consent screen`.
6. Configure the consent screen.
   For personal use, `External` is fine.
7. Open `APIs & Services` -> `Credentials`.
8. Click `Create Credentials` -> `OAuth client ID`.
9. Choose `Desktop app`.
10. Download the JSON file and save it in this project as `credentials.json`.

## 5. Create or Choose a Google Calendar

1. Open Google Calendar.
2. Create a dedicated calendar or use an existing one.
3. Open calendar settings.
4. Copy the `Calendar ID`.
5. Put that value into `GOOGLE_CALENDAR_ID` in `.env`.

## 6. Get an OpenRouter API Key

1. Go to https://openrouter.ai/
2. Sign in or create an account.
3. Create an API key.
4. Put that value into `OPENROUTER_API_KEY` in `.env`.

## 7. Fill in `.env`

Copy `.env.example` if needed, then fill in:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
OPENROUTER_API_KEY=your_openrouter_key
GOOGLE_CALENDAR_ID=your_calendar_id
NOTIFY_CHAT_ID=your_telegram_user_id
DATABASE_URL=postgresql://username:password@host:5432/database_name
CALENDAR_TIMEZONE=Asia/Dhaka
```

## 8. Create the PostgreSQL Database

1. Provision a PostgreSQL database locally or on your hosting provider.
2. Copy the connection string.
3. Set it as `DATABASE_URL` in `.env`.
4. The app creates the `events` table automatically on startup.

## 9. Install Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 10. First Run

1. Start the bot:

```bash
python3 main.py
```

2. On the first Google Calendar action, a browser window will open for Google OAuth.
3. Finish the login and consent flow.
4. The app will save `token.json` locally.
5. Future runs reuse `token.json` and do not ask again unless the token is revoked.

## 11. Commands

- `/start` shows the current chat ID and your user ID.
- `/pending` shows all pending and partial notices.
- `/all` shows all tracked events from the last 30 days.

## Event Lifecycle

- `pending`: no date found yet. Stored in PostgreSQL only. No calendar event is created.
- `partial`: date exists, but at least one of `time`, `syllabus`, or `location` is still missing. A calendar event is created with `[incomplete]` in the title and a description note listing missing fields.
- `confirmed`: all required fields are present. The calendar event is patched into its final clean form.

Status only moves forward. Existing known fields are never overwritten by later fragments.

## How Message Processing Works

1. A Telegram group message arrives.
2. The bot sends the text and today's date to OpenRouter.
3. The AI returns raw JSON or `{"is_event": false}`.
4. If it is an event, the bot asks OpenRouter whether the message matches one of the latest 50 stored events.
5. If no match exists, a new row is inserted into PostgreSQL.
6. If a match exists, only missing fields are filled in and the raw fragment is appended.
7. Calendar events are created or patched based on status promotion.
8. A private digest is sent to `NOTIFY_CHAT_ID` if any pending or partial events remain.

## Running 24/7 on Railway or Render

Free hosting changes often, so verify the current limits before deploying.

### Railway

1. Push this project to GitHub.
2. Create a new Railway project from the repo.
3. Add all `.env` values in Railway variables, including `DATABASE_URL` from Railway Postgres.
4. Upload `credentials.json`.
5. Attach a PostgreSQL service and confirm `DATABASE_URL` is available.
6. Run the bot once in a persistent environment so Google OAuth can generate `token.json`.
7. Keep `token.json` on persistent storage. Without persistence, OAuth will repeat after restarts.
8. Set the start command to:

```bash
python3 main.py
```

### Render

1. Push the project to GitHub.
2. Create a new Background Worker.
3. Set the build command to:

```bash
pip install -r requirements.txt
```

4. Set the start command to:

```bash
python3 main.py
```

5. Provision a Render Postgres instance and set `DATABASE_URL`.
6. Add your environment variables.
7. Upload or mount `credentials.json`.
8. Make sure `token.json` persists across redeploys.

## Notes

- Do not commit `.env`, `credentials.json`, `token.json`, or `failed_notices.log`.
- The bot uses polling, so it does not need a public webhook URL.
- Timed events default to one hour.
- If only a date is known, the bot creates an all-day event.
