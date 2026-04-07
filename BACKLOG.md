# Backlog

## Current Status

The codebase has been migrated from a Telegram bot flow to a `Telethon` user-session flow. Core docs and config examples were updated, but the project has not been fully validated end-to-end with real credentials in this workspace.

## Remaining Work

- Run a real startup test with valid `.env`, `credentials.json`, Telegram login, PostgreSQL, and OpenRouter access.
- Verify that `SOURCE_CHAT_ID` and `NOTIFY_CHAT_ID` behave correctly with the intended Telegram account and chats.
- Confirm Google Calendar OAuth works on the actual deployment target and that `token.json` persists.
- Validate event parsing and event matching quality against real academic group messages.
- Add a startup self-check mode or command to validate required env vars and required files before entering monitor mode.
- Add automated tests for event merging, status transitions, digest formatting, and database normalization.
- Decide whether browser-based Google OAuth is acceptable long term or whether the app should move to another auth strategy.
- Review deployment instructions after choosing the real hosting target and persistence model.

## Known Constraints

- The app requires manual creation of `credentials.json`.
- The app depends on persistent local/session files: `telegram_user_session.session` and `token.json`.
- OpenRouter access is required for notice parsing and event matching.
- The current workflow is interactive on first Telegram login.
