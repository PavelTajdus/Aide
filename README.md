# Aide

Osobní AI asistent postavený nad Claude Code CLI. Aide funguje jako tvůj pobočník — komunikuješ s ním přes Telegram nebo Slack, on si pamatuje kontext, spravuje úkoly, plánuje připomínky a umí pracovat s vlastními nástroji. Běží jako služba na serveru nebo lokálně.

**Co umí:**
- Konverzace přes Telegram a Slack (včetně vláken a příloh)
- Dlouhodobá paměť — automaticky si ukládá a vybavuje důležité informace
- Správa úkolů s prioritami, projekty a opakováním
- Plánované úlohy (cron) — připomínky, denní přehledy, vlastní automatizace
- Rozšiřitelnost přes vlastní nástroje (Python) a skills (Markdown)

## Rychlý start

```bash
./scripts/init.sh ~/aide-workspace
```

Vyplň `~/aide-workspace/.env` — minimálně `TELEGRAM_TOKEN`, `ALLOWED_USERS`, `AIDE_DEFAULT_CHAT_ID`.

```bash
./scripts/run.sh ~/aide-workspace
```

Podrobný setup pro jednotlivé platformy:
- [Telegram setup](docs/TELEGRAM_SETUP.md)
- [Slack setup](docs/SLACK_SETUP.md)

## Instalace na VPS

Automaticky (doporučeno):

```bash
sudo ./scripts/install_vps.sh
```

Skript nainstaluje závislosti, vytvoří venv, nastaví systemd services a denní auto-deploy (3:55 cron).

<details>
<summary>Ruční instalace</summary>

1. Nainstaluj závislosti: `sudo apt install -y git python3 python3-pip python3-venv python3-full`
2. Nainstaluj [Claude Code CLI](https://claude.com/product/claude-code) a ověř, že je v PATH
3. Klonuj repo:
   ```bash
   sudo mkdir -p /opt/aide && cd /opt/aide
   git clone https://github.com/PavelTajdus/Aide engine && cd engine
   ```
4. Inicializuj workspace: `./scripts/init.sh /opt/aide/workspace`
5. Nastav ownership: `sudo chown -R $USER:$USER /opt/aide`
6. Vyplň `/opt/aide/workspace/.env`
7. Vytvoř venv a nainstaluj dependencies:
   ```bash
   python3 -m venv /opt/aide/venv
   /opt/aide/venv/bin/pip install -r /opt/aide/engine/requirements.txt
   ```
8. Spusť: `PYTHON_BIN=/opt/aide/venv/bin/python ./scripts/run.sh /opt/aide/workspace`

</details>

### Deploy a aktualizace

```bash
./scripts/deploy.sh [workspace]    # git pull → pip install → update workspace → restart
```

`install_vps.sh` nastaví automatický deploy každý den ve 3:55.

## Workspace

Workspace je oddělený od engine repa — obsahuje tvoje osobní data a nikdy nepatří do enginu.

```
~/aide-workspace/
├── .env                          # Tokeny, API klíče
├── CLAUDE.md                     # Osobnost a pravidla agenta
├── .claude/skills/               # Symlinky na default_skills/ + vlastní
├── core_tools/                   # Symlink na engine/core_tools/
├── tools/                        # Vlastní nástroje
├── knowledge/                    # Referenční dokumenty
├── data/                         # Sessions, úkoly, paměť, cron, logy
├── conversations/
└── inbox/                        # Nahrané soubory z chatu
```

Engine najde workspace podle: argument skriptu > env `AIDE_WORKSPACE` > aktuální adresář > `~/aide-workspace`.

### Backup

```bash
cd /opt/aide/workspace
git init
cp /opt/aide/engine/templates/workspace.gitignore .gitignore
git add . && git commit -m "initial workspace"
git remote add origin <YOUR_PRIVATE_REPO>
git push -u origin main
```

Pak stačí: `./scripts/backup.sh [workspace] --push`

## Skripty

| Skript | Popis |
|--------|-------|
| `run.sh [workspace]` | Start (bot + scheduler) |
| `stop.sh [workspace]` | Stop |
| `restart.sh [workspace]` | Restart + claude update |
| `deploy.sh [workspace]` | Git pull + pip + update + restart |
| `status.sh [workspace]` | Status služeb |
| `logs.sh [workspace] [bot\|slack\|scheduler]` | Logy |
| `ps.sh [workspace]` | Procesy |
| `backup.sh [workspace] [--push]` | Git backup workspace |

## Konfigurace (.env)

### Telegram

| Proměnná | Popis |
|----------|-------|
| `TELEGRAM_TOKEN` | Bot token |
| `ALLOWED_USERS` | Povolená Telegram user ID |
| `AIDE_DEFAULT_CHAT_ID` | Chat ID pro notifikace a připomínky |
| `AIDE_TELEGRAM_ENABLED` | `0` = vypnuto |
| `AIDE_TELEGRAM_PARSE_MODE` | `markdown_v2` pro formátování (default: plain text) |
| `AIDE_TELEGRAM_ESCAPE` | `none\|aggressive` |
| `AIDE_TELEGRAM_PROGRESS` | `1` = stavové updaty během běhu |
| `AIDE_TELEGRAM_MAX_FILE_MB` | Max velikost příloh (default 10) |

### Slack

| Proměnná | Popis |
|----------|-------|
| `SLACK_BOT_TOKEN` | xoxb-... token |
| `SLACK_APP_TOKEN` | xapp-... token (Socket Mode) |
| `AIDE_SLACK_ENABLED` | `1` = zapnuto |
| `AIDE_SLACK_ALLOWED_USERS` | Povolená Slack user ID |
| `AIDE_SLACK_DEFAULT_TARGET` | Channel/user ID pro notifikace |
| `AIDE_SLACK_DEFAULT_TARGET_TYPE` | `auto\|dm\|channel` (default `auto`) |
| `AIDE_SLACK_MAX_FILE_MB` | Max velikost příloh (default 10) |
| `AIDE_NOTIFY_PROVIDER` | `slack` pro notifikace přes Slack |

### Ostatní

| Proměnná | Popis |
|----------|-------|
| `AIDE_CLAUDE_SKIP_PERMISSIONS` | `1` = Claude Code bez potvrzování |
| `AIDE_SCHEDULER_WORKERS` | Paralelní cron joby (default 2) |

## Vlastní nástroje a skills

**Nástroje** jsou Python CLI skripty v `workspace/tools/`:
- Vstup přes `argparse`, výstup JSON `{success, data|error}`
- API klíče z `.env`, nic hardcoded
- Šablona: `templates/tool_skeleton.py`

**Skills** jsou Markdown soubory v `.claude/skills/`, které popisují kdy a jak agent nástroj použije.

## Troubleshooting

Zkontroluj status a logy:

```bash
./scripts/status.sh [workspace]
./scripts/logs.sh [workspace] [bot|slack|scheduler]
```

**Telegram neodpovídá:** ověř `TELEGRAM_TOKEN` a `ALLOWED_USERS` v `.env`, zkontroluj `bot.log`.

**Slack neodpovídá:** ověř `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` a `AIDE_SLACK_ALLOWED_USERS`, zkontroluj `slack.log`.

**Scheduler neposílá připomínky:** ověř `AIDE_DEFAULT_CHAT_ID`, zkontroluj `scheduler.log`.
