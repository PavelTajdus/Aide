# Aide — MVP Engine

## Rychlý start

1. Inicializace workspace:
```
./scripts/init.sh ~/aide-workspace
```

2. Nastav `TELEGRAM_TOKEN`, `ALLOWED_USERS`, `AIDE_DEFAULT_CHAT_ID` ve `~/aide-workspace/.env`.
   - Pro Slack: `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `AIDE_SLACK_ALLOWED_USERS`, `AIDE_SLACK_DEFAULT_TARGET`, `AIDE_SLACK_ENABLED=1`.
   - Pro notifikace do Slacku: `AIDE_NOTIFY_PROVIDER=slack`.

3. Spuštění:
```
./scripts/run.sh ~/aide-workspace
```

## Integrace

- Slack setup: [docs/SLACK_SETUP.md](docs/SLACK_SETUP.md)
- Telegram setup: [docs/TELEGRAM_SETUP.md](docs/TELEGRAM_SETUP.md)

## Instalace na VPS (Linux)

Nejjednodušší varianta je spustit instalační skript (všechno nastaví za tebe):
```
sudo ./scripts/install_vps.sh
```

Ručně (pokud chceš):

1. Nainstaluj Git, Python 3, pip a venv:
```
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv python3-full
```

2. Nainstaluj Claude Code CLI a přihlas se (vyžaduje předplatné).
   - https://claude.com/product/claude-code
   - Dokumentace: https://code.claude.com/docs/en/overview
   - Ověř, že `claude` je v PATH (`which claude`).
   - Typicky se instaluje do `~/.local/bin` nebo `/usr/local/bin`.

3. Klonuj repo:
```
sudo mkdir -p /opt/aide
cd /opt/aide
git clone https://github.com/PavelTajdus/Aide engine
cd engine
```

4. Inicializuj workspace:
```
./scripts/init.sh /opt/aide/workspace
```

5. Nastav ownership, ať nemusíš používat sudo pro běh:
```
sudo chown -R $USER:$USER /opt/aide
```

6. Vyplň `/opt/aide/workspace/.env` (tokeny, user ID, chat ID).

7. Nainstaluj python dependencies (doporučeno do venv):
```
python3 -m venv /opt/aide/venv
/opt/aide/venv/bin/pip install -r /opt/aide/engine/requirements.txt
```

8. Spusť bota + scheduler:
```
PYTHON_BIN=/opt/aide/venv/bin/python ./scripts/run.sh /opt/aide/workspace
```

9. Logy:
```
./scripts/logs.sh /opt/aide/workspace
```

Poznámka: Pokud spouštíš přes `sudo`, pip instaluje balíčky do root prostředí.

### Automatické aktualizace

`install_vps.sh` automaticky nastaví cron job, který každý den ve 3:55 spustí `deploy.sh`:

```
55 3 * * * /opt/aide/engine/scripts/deploy.sh /opt/aide/workspace >> /opt/aide/workspace/data/logs/deploy.log 2>&1
```

`deploy.sh` provede: git pull → pip install → update workspace (symlinky, skills, verze) → restart služeb.

Pro ruční deploy:
```
/opt/aide/engine/scripts/deploy.sh /opt/aide/workspace
```

## Workspace — jak to funguje

Workspace je **oddělený od engine repa** a obsahuje tvoje osobní data.

Typická struktura:
```
~/aide-workspace/
├── .env
├── CLAUDE.md
├── .claude/skills/       → symlinky na engine/default_skills/
├── core_tools/           → symlink na engine/core_tools/
├── tools/                → custom nástroje (user-defined)
├── knowledge/
├── data/
│   ├── sessions.json
│   ├── sessions_slack.json
│   ├── cron.json
│   ├── tasks.json
│   ├── projects.json
│   ├── memory.json
│   ├── engine_version
│   └── logs/
├── conversations/
└── inbox/
```

**Jak engine najde workspace:**

1. Argument ve skriptu: `./scripts/run.sh /path/to/workspace`
2. Env proměnná `AIDE_WORKSPACE`
3. Aktuální adresář, pokud obsahuje `CLAUDE.md` nebo `data/`
4. Fallback: `~/aide-workspace`

## Skripty (ops)

- Start (bot + scheduler):
```
./scripts/run.sh [workspace]
```

- Stop:
```
./scripts/stop.sh [workspace]
```

- Restart (+ claude update):
```
./scripts/restart.sh [workspace]
```

- Deploy (git pull + pip + update workspace + restart):
```
./scripts/deploy.sh [workspace]
```

- Status:
```
./scripts/status.sh [workspace]
```

- Logs:
```
./scripts/logs.sh [workspace] [bot|slack|scheduler]
```

- Process snapshot:
```
./scripts/ps.sh [workspace]
```

- Backup workspace (git):
```
./scripts/backup.sh [workspace]
./scripts/backup.sh [workspace] --push
```

## Poznámky

- Workspace **nikdy** nepatří do git repa enginu.
- Core tools (`core_tools/`) i default skills (`default_skills/`) se do workspace symlinkují — aktualizují se automaticky při deploy.
- Telegram output je defaultně plain text. Lze přepnout na MarkdownV2 přes `AIDE_TELEGRAM_PARSE_MODE=markdown_v2`.
- Escape režim pro MarkdownV2: `AIDE_TELEGRAM_ESCAPE=none|aggressive`.
- Stavové updaty během běhu: `AIDE_TELEGRAM_PROGRESS=1` (0 = vypnuto).
- Slack bot přes Socket Mode vyžaduje `SLACK_APP_TOKEN` (xapp-...) a `SLACK_BOT_TOKEN` (xoxb-...).
- Slack přístup: `AIDE_SLACK_ALLOWED_USERS` (Slack user ID). Prázdné = žádný přístup.
- Slack notifikace: `AIDE_NOTIFY_PROVIDER=slack` + `AIDE_SLACK_DEFAULT_TARGET` (channel ID nebo user ID).
- Alternativa: `AIDE_SLACK_DEFAULT_CHANNEL_ID` nebo `AIDE_SLACK_DEFAULT_USER_ID`.
- Typ cíle: `AIDE_SLACK_DEFAULT_TARGET_TYPE=auto|dm|channel` (default `auto`).
- Slack bot se spouští automaticky, pokud jsou tokeny nastavené a `AIDE_SLACK_ENABLED=1`.
- Max velikost Slack příloh: `AIDE_SLACK_MAX_FILE_MB` (default 10).
- Slack přílohy se ukládají do `inbox/` a do promptu se předá jejich cesta.
- Vypnutí kanálu: `AIDE_TELEGRAM_ENABLED=0` nebo `AIDE_SLACK_ENABLED=0`.
- Claude Code bez potvrzování: `AIDE_CLAUDE_SKIP_PERMISSIONS=1`.
- Max velikost příloh: `AIDE_TELEGRAM_MAX_FILE_MB` (default 10).
- Scheduler paralelismus: `AIDE_SCHEDULER_WORKERS` (default 2).

Slack setup (minimum):
- Zapni Socket Mode a Event Subscriptions.
- Events: `app_mention`, `message.im`.
- Bot scopes typicky: `app_mentions:read`, `im:history`, `chat:write`, `im:write`, `files:read`.

## Tooling konvence (shrnutí)

- Nové tools piš v Pythonu 3 jako CLI v `workspace/tools/`.
- Vstup přes `argparse`, výstup JSON `{success, data|error}`.
- API klíče vždy z `.env`, nic hardcoded.
- Po vytvoření toolu vytvoř i skill v `.claude/skills/`.
- Šablona toolu: `templates/tool_skeleton.py`

## Backup workspace (git)

Doporučený postup:
```
cd /opt/aide/workspace
git init
cp /opt/aide/engine/templates/workspace.gitignore .gitignore
git add .
git commit -m "initial workspace"
git remote add origin <YOUR_PRIVATE_REPO>
git push -u origin main
```

Pak stačí:
```
/opt/aide/engine/scripts/backup.sh /opt/aide/workspace --push
```

## Troubleshooting

- Bot neběží: zkontroluj status
```
./scripts/status.sh [workspace]
```

- Logy bota a scheduleru:
```
./scripts/logs.sh [workspace]
./scripts/logs.sh [workspace] bot
./scripts/logs.sh [workspace] slack
./scripts/logs.sh [workspace] scheduler
```

- Telegram nic nevrací:
  - ověř `TELEGRAM_TOKEN` v `.env`
  - ověř `ALLOWED_USERS` (tvůj Telegram user ID) — prázdné znamená žádný přístup
  - zkontroluj `bot.log`

- Slack nic nevrací:
  - ověř `SLACK_BOT_TOKEN` a `SLACK_APP_TOKEN` v `.env`
  - ověř `AIDE_SLACK_ALLOWED_USERS` (tvůj Slack user ID)
  - zkontroluj `slack.log`

- Scheduler neposílá připomínky:
  - ověř `AIDE_DEFAULT_CHAT_ID`
  - zkontroluj `scheduler.log`

## MarkdownV2 cheat‑sheet (Telegram)

Použitelné formátování (MarkdownV2):

- *Kurzíva:* `_text_`
- **Tučně:** `*text*`
- `Kód:` `` `text` ``
- ```Blok kódu:``` ``` ```text``` ```
- Odkaz: `[label](https://example.com)`
- Seznam: `- položka`

Pozor: znaky `_ * [ ] ( ) ~ \` > # + - = | { } . !` jsou speciální.
