# Telegram bot setup

Krok za krokem:

1. Vytvoř bota přes BotFather
- V Telegramu otevři `@BotFather`.
- Pošli `/newbot`.
- Zadej název a uživatelské jméno.
- Zkopíruj token.

2. Zjisti svoje Telegram user ID
- V Telegramu napiš botovi `@userinfobot` a zkopíruj `Id`.

3. Zjisti chat ID pro notifikace
- Napiš svému botovi libovolnou zprávu.
- Získej `chat_id` pomocí API:
```
curl "https://api.telegram.org/bot<TELEGRAM_TOKEN>/getUpdates"
```
- V odpovědi najdi `message.chat.id`.

4. Nastav `.env` ve workspace
```
TELEGRAM_TOKEN=123456:ABCDEF...
ALLOWED_USERS=123456789
AIDE_DEFAULT_CHAT_ID=123456789
AIDE_TELEGRAM_ENABLED=1
```

Poznámky:
- `ALLOWED_USERS`: seznam user ID oddělených čárkou.
- `AIDE_DEFAULT_CHAT_ID` je cíl pro notifikace (DM nebo kanál).

5. Spusť bota
```
./scripts/run.sh /path/to/workspace
```

Troubleshooting:
- `bot.log` v `data/logs/`.
