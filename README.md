# Aide

Osobní AI asistent, který běží na tvém serveru a komunikuje přes Telegram nebo Slack. Postavený nad [Claude Code CLI](https://claude.com/product/claude-code) — má přístup k souborovému systému, umí psát a spouštět kód, hledat na webu a pracovat s API. Není to chatbot. Je to pobočník, který si pamatuje, plánuje a jedná samostatně.

## Čím je víc než chatbot

**Paměť.** Aide si automaticky ukládá důležité informace — tvoje rozhodnutí, preference, kontakty, stav projektů. Při každé nové konverzaci si relevantní fakta sám vyhledá a použije jako kontext. Nemusíš mu nic opakovat.

**Vlastní nástroje.** Aide si umí napsat Python skripty, které pak používá jako nástroje. Potřebuješ napojení na API třetí strany? Automatické generování reportů? Zpracování dat? Řekneš mu co potřebuješ, on si napíše skript, uloží ho do workspace a od té doby ho používá.

**Plánování a automatizace.** Správa úkolů s prioritami, projekty a opakováním. Cron joby — naplánuj si ranní přehled, pravidelný reporting nebo cokoliv jiného. Aide tě sám upozorní na blížící se deadliny.

**Příklady, co si s ním lidi staví:**
- Ranní briefing — denní přehled úkolů, deadlinů a důležitých informací
- API integrace — napojení na libovolnou službu (CRM, CMS, fakturace, e-commerce, ...)
- Obsahové workflow — research, draft, review, publikace
- Monitoring — sledování GitHub repozitářů, webů, RSS feedů, čehokoliv s API
- Zpracování dat — parsování dokumentů, generování reportů, transformace souborů
- Research — hledání na webu, porovnávání, ověřování faktů, sumarizace
- Automatizace — opakované připomínky, notifikace, periodické skripty

## Požadavky

- Python 3 + pip
- [Claude Code CLI](https://claude.com/product/claude-code) nainstalovaný a v PATH (vyžaduje předplatné)
- Telegram bot token a/nebo Slack app tokeny

### Proč Claude a proč předplatné?

Aide používá Claude Code CLI, které vyžaduje předplatné Anthropic (Pro/Max). Není to jen obchodní rozhodnutí — pro autonomního agenta s přístupem k nástrojům je kvalita modelu zásadní.

**Spolehlivost při práci s nástroji.** Autonomní agent nepíše jen text — volá API, spouští skripty, zapisuje soubory. Slabší modely při tom častěji chybují, komolí syntaxi a nedokážou se zotavit z chyb. Komunita kolem OpenClaw (podobný open-source agent) zjistila, že degradace kvality mezi frontier a mid-tier modely není postupná — je to skok. Buď model zvládá spolehlivě řetězit nástroje, nebo ne.

**Hlubší porozumění.** Při testování s výkonnými středními modely jsem opakovaně narážel na to, že si agent vymýšlel kontext — třeba při zapisování úkolů přidával informace, které nikdo neřekl, nebo překrucoval zadání. U osobního asistenta, kterému důvěřuješ a spoléháš se na něj, si tohle nemůžeš dovolit.

**Bezpečnost.** Agent s přístupem k souborům, shellu a API potřebuje odolnost proti prompt injection. OpenClaw ve své bezpečnostní dokumentaci přímo varuje před nasazením slabších modelů pro agenty s nástroji — úspěšný prompt injection útok má dopad na všechno, k čemu má agent přístup.

## Instalace

### VPS (doporučeno)

```bash
sudo ./scripts/install_vps.sh
```

Skript nainstaluje závislosti, vytvoří venv, nastaví systemd services a denní auto-deploy.

Po instalaci vyplň `/opt/aide/workspace/.env` (tokeny, user ID, chat ID) a spusť:

```bash
./scripts/run.sh /opt/aide/workspace
```

<details>
<summary>Ruční instalace (krok po kroku)</summary>

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

### Lokální vývoj

```bash
./scripts/init.sh ~/aide-workspace
# vyplň ~/aide-workspace/.env
./scripts/run.sh ~/aide-workspace
```

Podrobný setup pro jednotlivé platformy:
- [Telegram setup](docs/TELEGRAM_SETUP.md)
- [Slack setup](docs/SLACK_SETUP.md)

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

**Nástroje** jsou Python CLI skripty v `workspace/tools/`. Aide si je umí vytvořit sám, když mu popíšeš co potřebuješ — nebo je můžeš napsat ručně:
- Vstup přes `argparse`, výstup JSON `{success, data|error}`
- API klíče z `.env`, nic hardcoded
- Šablona: `templates/tool_skeleton.py`

**Skills** jsou Markdown soubory v `.claude/skills/`, které popisují kdy a jak agent nástroj použije. Aide přichází s vestavěnými skills pro paměť, úkoly, research a denní přehledy.

## Troubleshooting

Zkontroluj status a logy:

```bash
./scripts/status.sh [workspace]
./scripts/logs.sh [workspace] [bot|slack|scheduler]
```

**Telegram neodpovídá:** ověř `TELEGRAM_TOKEN` a `ALLOWED_USERS` v `.env`, zkontroluj `bot.log`.

**Slack neodpovídá:** ověř `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` a `AIDE_SLACK_ALLOWED_USERS`, zkontroluj `slack.log`.

**Scheduler neposílá připomínky:** ověř `AIDE_DEFAULT_CHAT_ID`, zkontroluj `scheduler.log`.
