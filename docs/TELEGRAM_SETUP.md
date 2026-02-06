# Telegram bot setup

Step by step:

1. Create a bot via BotFather
- Open `@BotFather` in Telegram.
- Send `/newbot`.
- Enter a name and username.
- Copy the token.

2. Get your Telegram user ID
- In Telegram, message the bot `@userinfobot` and copy the `Id`.

3. Get the chat ID for notifications
- Send any message to your bot.
- Get the `chat_id` via API:
```
curl "https://api.telegram.org/bot<TELEGRAM_TOKEN>/getUpdates"
```
- Find `message.chat.id` in the response.

4. Configure `.env` in your workspace
```
TELEGRAM_TOKEN=123456:ABCDEF...
ALLOWED_USERS=123456789
AIDE_DEFAULT_CHAT_ID=123456789
AIDE_TELEGRAM_ENABLED=1
```

Notes:
- `ALLOWED_USERS`: comma-separated list of user IDs.
- `AIDE_DEFAULT_CHAT_ID` is the target for notifications (DM or channel).

5. Start the bot
```
./scripts/run.sh /path/to/workspace
```

Troubleshooting:
- Check `bot.log` in `data/logs/`.
