# Telegram to Google Calendar Automation

This project monitors a Telegram group using your own Telegram account through `Telethon`, extracts academic notices with OpenRouter AI, tracks them in PostgreSQL, and creates or updates matching Google Calendar events.

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

## Before You Run This

This app is not ready to run from a fresh clone unless you supply the required local secrets and OAuth files yourself.

You need all of these before normal operation:

- `.env` with valid Telegram, OpenRouter, PostgreSQL, and Google Calendar values
- `credentials.json` from Google OAuth client setup
- access to the target Telegram group from the Telegram account in `TELEGRAM_PHONE`
- a reachable PostgreSQL database

What the app creates later:

- `telegram_user_session.session` after Telegram login
- `token.json` after Google OAuth succeeds
- the `events` table inside your PostgreSQL database

If `credentials.json` is missing, Telegram monitoring can still start, but Google Calendar creation and patching will fail when the app first tries to sync an event.

## Features

- Uses a Telegram user session with `Telethon`, not a bot.
- Works even when you cannot add a bot to the target group, as long as your Telegram account can read that group.
- Parses Bangla and English academic notices through OpenRouter using `google/gemini-2.0-flash-exp:free`.
- Maintains an event lifecycle in PostgreSQL: `pending`, `partial`, `confirmed`.
- Creates Google Calendar events only when enough data exists.
- Patches existing Google Calendar events as missing details arrive.
- Sends private digest notifications for pending and partial events.
- Supports `/start`, `/pending`, and `/all` commands from your own notification chat.
- Logs failures to `failed_notices.log` without crashing the app.

## 1. Get Telegram API Credentials

This is different from a bot token.

1. Go to https://my.telegram.org/
2. Sign in with your Telegram account.
3. Open `API development tools`.
4. Create an application.
5. Copy your `api_id` and `api_hash`.
6. Put them into `.env` as `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`.

## 2. Choose the Telegram Account the App Will Use

1. Use the phone number of the Telegram account that already has access to the academic group.
2. Put that number into `.env` as `TELEGRAM_PHONE` in international format.
   Example: `+8801XXXXXXXXX`
3. On first run, the app will ask for the login code sent by Telegram.
4. If your account has two-step verification, it will also ask for the password.
5. The session is then saved locally in `telegram_user_session.session`.

## 3. Find the Source Group ID

List your Telegram chats:

```bash
python3 main.py --list-chats
```

Resolve a specific group by name, username, or link:

```bash
python3 main.py --resolve-chat "My Academic Group"
```

Then either:

- put the numeric ID into `.env` as `SOURCE_CHAT_ID`, or
- put the exact group name into `.env` as `SOURCE_CHAT_NAME`

## 4. Choose the Notification Chat

Set `NOTIFY_CHAT_ID` to the Telegram chat where the app should send digests and where it should accept `/start`, `/pending`, and `/all`.

Common choices:

- Your own user ID
- Your Saved Messages chat ID
- A private chat you control

## 5. Enable Google Calendar API and Download `credentials.json`

1. Go to Google Cloud Console: https://console.cloud.google.com/
2. Create a new project or select an existing one.
3. Open `APIs & Services` -> `Library`.
4. Search for `Google Calendar API` and enable it.
5. Open `APIs & Services` -> `OAuth consent screen`.
6. Configure the consent screen.
7. Open `APIs & Services` -> `Credentials`.
8. Click `Create Credentials` -> `OAuth client ID`.
9. Choose `Desktop app`.
10. Download the JSON file and save it in this project as `credentials.json`.

This file is required by the current implementation in `calendar_api.py`. Without it, the app cannot complete Google OAuth and cannot write to Google Calendar.

## 6. Create or Choose a Google Calendar

1. Open Google Calendar.
2. Create a dedicated calendar or use an existing one.
3. Open calendar settings.
4. Copy the `Calendar ID`.
5. Put that value into `GOOGLE_CALENDAR_ID` in `.env`.

## 7. Get an OpenRouter API Key

1. Go to https://openrouter.ai/
2. Sign in or create an account.
3. Create an API key.
4. Put that value into `OPENROUTER_API_KEY` in `.env`.

## 8. Configure PostgreSQL

1. Provision a PostgreSQL database locally or on your hosting provider.
2. Copy the connection string.
3. Set it as `DATABASE_URL` in `.env`.
4. The app creates the `events` table automatically on startup.

## 9. Fill in `.env`

```env
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_telegram_api_hash
TELEGRAM_PHONE=+8801XXXXXXXXX
TELEGRAM_SESSION_NAME=telegram_user_session
OPENROUTER_API_KEY=your_openrouter_key
GOOGLE_CALENDAR_ID=your_calendar_id
SOURCE_CHAT_NAME=My Academic Group
SOURCE_CHAT_ID=-1001234567890
NOTIFY_CHAT_ID=123456789
DATABASE_URL=postgresql://username:password@host:5432/database_name
CALENDAR_TIMEZONE=Asia/Dhaka
```

## 10. Install Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 11. First Run

List chats first if you do not know the group ID yet:

```bash
python3 main.py --list-chats
```

Start monitoring:

```bash
python3 main.py
```

Do not skip the Google setup if you expect calendar sync to work. The app does not auto-create `credentials.json`, and it does not fall back to any other Google authentication method.

What happens on first run:

1. The app logs in to Telegram using your user account.
2. Telegram sends a login code to your app.
3. You enter the code in the terminal.
4. If needed, you enter your two-step verification password.
5. The session is saved locally for later runs.
6. On the first Google Calendar action, a browser window opens for Google OAuth.
7. The app saves `token.json` locally after successful Google login.

If you run this on a remote server without a practical browser-based OAuth flow, you will need to solve that deployment detail first or change the authentication approach in code.

## 12. Commands

Send these from the chat whose ID matches `NOTIFY_CHAT_ID`:

- `/start` shows the current chat ID and your Telegram user ID.
- `/pending` shows all pending and partial notices.
- `/all` shows all tracked events from the last 30 days.

## Fresh Database Behavior

- A brand-new PostgreSQL database is fine.
- On startup, the app creates the `events` table automatically if it does not already exist.
- You do not need to create any table manually.

## Which Telegram Chat Is Monitored

- The app processes only messages from the configured source chat.
- It first uses `SOURCE_CHAT_ID` if provided.
- Otherwise it tries to resolve `SOURCE_CHAT_NAME` automatically.
- All other chats are ignored.
- Filtering is done by numeric chat ID, not by display name.
- If multiple chats have the same exact name, use `SOURCE_CHAT_ID` to avoid ambiguity.

## Event Lifecycle

- `pending`: no date found yet. Stored in PostgreSQL only. No calendar event is created.
- `partial`: date exists, but at least one of `time`, `syllabus`, or `location` is still missing. A calendar event is created with `[incomplete]` in the title and a description note listing missing fields.
- `confirmed`: all required fields are present. The calendar event is patched into its final clean form.

Status only moves forward. Existing known fields are never overwritten by later fragments.

## How Message Processing Works

1. A new message arrives in the configured source chat.
2. The app sends the text and today's date to OpenRouter.
3. The AI returns raw JSON or `{"is_event": false}`.
4. If it is an event, the app asks OpenRouter whether the message matches one of the latest 50 stored events.
5. If no match exists, a new row is inserted into PostgreSQL.
6. If a match exists, only missing fields are filled in and the raw fragment is appended.
7. Calendar events are created or patched based on status promotion.
8. A private digest is sent to `NOTIFY_CHAT_ID` if any pending or partial events remain.

## Running 24/7 on Railway or Render

Free hosting policies change often, so verify current limits before deployment.

### Railway

1. Push this project to GitHub.
2. Create a new Railway project from the repo.
3. Add all `.env` values in Railway variables, including `DATABASE_URL`.
4. Upload `credentials.json`.
5. Make sure the Telegram session file and `token.json` persist across restarts.
6. Start the worker with:

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

5. Provision Postgres and set `DATABASE_URL`.
6. Upload or mount `credentials.json`.
7. Make sure the Telegram session file and `token.json` persist across redeploys.

## Notes

- Do not commit `.env`, `credentials.json`, `token.json`, `telegram_user_session.session`, or `failed_notices.log`.
- This app does not use a Telegram bot token.
- `credentials.json` is a manual prerequisite. It is not generated by the app.
- Timed events default to one hour.
- If only a date is known, the app creates an all-day event.
