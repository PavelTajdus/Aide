# Aide — MVP Engine

## Rychlý start

1. Inicializace workspace:
```
./scripts/init.sh /Users/pavel/aide-workspace
```

2. Nastav `TELEGRAM_TOKEN`, `ALLOWED_USERS`, `AIDE_DEFAULT_CHAT_ID` ve `~/aide-workspace/.env`.

3. Spuštění:
```
./scripts/run.sh /Users/pavel/aide-workspace
```

## Instalace na VPS (Linux)

1. Nainstaluj Python 3 a pip:
```
sudo apt update
sudo apt install -y python3 python3-pip
```

2. Nainstaluj Claude Code CLI a přihlas se (vyžaduje předplatné).

3. Klonuj repo:
```
git clone https://github.com/PavelTajdus/Aide
cd Aide
```

4. Inicializuj workspace:
```
./scripts/init.sh /opt/aide-workspace
```

5. Vyplň `/opt/aide-workspace/.env` (tokeny, user ID, chat ID).

6. Spusť bota + scheduler:
```
./scripts/run.sh /opt/aide-workspace
```

7. Logy:
```
./scripts/logs.sh /opt/aide-workspace
```

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

## Poznámky

- Workspace **nikdy** nepatří do git repa enginu.
- Core tools jsou v enginu (`core_tools/`) a do workspace se symlinkují.
- Telegram output je defaultně plain text. Lze přepnout na MarkdownV2 přes `AIDE_TELEGRAM_PARSE_MODE=markdown_v2`.
- Escape režim pro MarkdownV2: `AIDE_TELEGRAM_ESCAPE=none|aggressive`.
- Stavové updaty během běhu: `AIDE_TELEGRAM_PROGRESS=1` (0 = vypnuto).

## Tooling konvence (shrnutí)

- Nové tools piš v Pythonu 3 jako CLI v `workspace/tools/`.
- Vstup přes `argparse`, výstup JSON `{success, data|error}`.
- API klíče vždy z `.env`, nic hardcoded.
- Po vytvoření toolu vytvoř i skill v `.claude/skills/`.
- Šablona toolu: `templates/tool_skeleton.py`

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
  - ověř `ALLOWED_USERS` (tvůj Telegram user ID)
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
