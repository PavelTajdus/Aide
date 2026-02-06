# Slack bot setup (Socket Mode)

Krok za krokem:

1. Vytvoř Slack app
- Otevři Slack API Apps.
- Klikni "Create New App" -> "From scratch".
- Zvol název a workspace.

2. Zapni Socket Mode
- V App settings zapni "Socket Mode".
- Vytvoř App-Level Token s oprávněním `connections:write`.
- Zkopíruj token (začínající `xapp-...`).

3. Nastav OAuth scopes pro bota
- V "OAuth & Permissions" přidej Bot Token Scopes:
  - `app_mentions:read`
  - `chat:write`
  - `im:history`
  - `im:write`
  - `files:read`
  - `channels:history` (nutné pro `AIDE_SLACK_AUTO_THREAD`)
  - `groups:history` (nutné pro auto-thread v privátních kanálech)

4. Zapni Event Subscriptions
- Zapni "Event Subscriptions".
- Přidej Bot Events:
  - `app_mention`
  - `message.im`
  - `message.channels` (nutné pro `AIDE_SLACK_AUTO_THREAD`)
  - `message.groups` (nutné pro auto-thread v privátních kanálech)
Poznámka: Pokud Slack UI vyžaduje Request URL, použij vlastní veřejný endpoint pro ověření. Při Socket Mode se eventy doručují přes WebSocket.

5. Nainstaluj app do workspace
- V "OAuth & Permissions" klikni "Install to Workspace".
- Zkopíruj Bot User OAuth Token (začínající `xoxb-...`).

6. Přidej bota do kanálu
- V kanálu napiš `/invite @your-bot-name`.

7. Zjisti svoje Slack user ID
- Klikni na svůj profil vpravo nahoře.
- Zvol "Profil".
- Klikni na tři tečky a zvol "Copy member ID".

7. Nastav `.env` ve workspace
```
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
AIDE_SLACK_ENABLED=1
AIDE_SLACK_ALLOWED_USERS=UXXXXXXX
AIDE_SLACK_DEFAULT_TARGET=UXXXXXXX
AIDE_SLACK_AUTO_THREAD=1
AIDE_NOTIFY_PROVIDER=slack
```
Poznámky:
- `AIDE_SLACK_ALLOWED_USERS`: seznam Slack user ID oddělených čárkou.
- `AIDE_SLACK_DEFAULT_TARGET`: `U...` pro DM, nebo `C.../G...` pro kanál.
- Pokud chceš vynutit cíl, použij `AIDE_SLACK_DEFAULT_TARGET_TYPE=dm|channel`.
- `AIDE_SLACK_AUTO_THREAD`: `1` = bot automaticky odpovídá ve vláknech bez nutnosti @zmínky (výchozí: `0`). Vyžaduje přidat event subscriptions `message.channels`/`message.groups` a scopes `channels:history`/`groups:history`.

8. Spusť bota
```
./scripts/run.sh /path/to/workspace
```

Troubleshooting:
- `slack.log` v `data/logs/`.
- Oprávnění chybně? Zkus znovu nainstalovat app (po změně scopes).
