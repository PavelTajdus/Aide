# Aide — MVP Engine

## Rychlý start

1. Inicializace workspace:
```
./scripts/init.sh ~/aide-workspace
```

2. Nastav `TELEGRAM_TOKEN`, `ALLOWED_USERS`, `AIDE_DEFAULT_CHAT_ID` ve `~/aide-workspace/.env`.

3. Spuštění:
```
./scripts/run.sh ~/aide-workspace
```

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

## Workspace — jak to funguje

Workspace je **oddělený od engine repa** a obsahuje tvoje osobní data.

Typická struktura:
```
~/aide-workspace/
├── .env
├── CLAUDE.md
├── .claude/skills/
├── tools/
├── data/
│   ├── sessions.json
│   ├── cron.json
│   ├── tasks.json
│   ├── projects.json
│   ├── logs/
│   └── journal/
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

- Restart:
```
./scripts/restart.sh [workspace]
```

- Status:
```
./scripts/status.sh [workspace]
```

- Logs:
```
./scripts/logs.sh [workspace] [bot|scheduler]
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
- Core tools jsou v enginu (`core_tools/`) a do workspace se symlinkují.
- Telegram output je defaultně plain text. Lze přepnout na MarkdownV2 přes `AIDE_TELEGRAM_PARSE_MODE=markdown_v2`.
- Escape režim pro MarkdownV2: `AIDE_TELEGRAM_ESCAPE=none|aggressive`.
- Stavové updaty během běhu: `AIDE_TELEGRAM_PROGRESS=1` (0 = vypnuto).
- Claude Code bez potvrzování: `AIDE_CLAUDE_SKIP_PERMISSIONS=1`.
- Max velikost příloh: `AIDE_TELEGRAM_MAX_FILE_MB` (default 10).
- Scheduler paralelismus: `AIDE_SCHEDULER_WORKERS` (default 2).

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
./scripts/logs.sh [workspace] scheduler
```

- Telegram nic nevrací:
  - ověř `TELEGRAM_TOKEN` v `.env`
  - ověř `ALLOWED_USERS` (tvůj Telegram user ID) — prázdné znamená žádný přístup
  - zkontroluj `bot.log`

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
