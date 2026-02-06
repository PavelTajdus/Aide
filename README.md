# Aide

A personal AI assistant that runs on your server and communicates via Telegram or Slack. Built on top of [Claude Code CLI](https://claude.com/product/claude-code) — it has access to the filesystem, can write and run code, search the web, and work with APIs. It's not a chatbot. It's a copilot that remembers, plans, and acts on its own.

## What makes it more than a chatbot

**Memory.** Aide automatically saves important information — your decisions, preferences, contacts, project status. At the start of each new conversation, it retrieves relevant facts and uses them as context. You never have to repeat yourself.

**Custom tools.** Aide can write Python scripts and use them as tools. Need an e-shop API integration? Auto-generated product descriptions? Competitor price monitoring? Tell it what you need, it writes a script, saves it to the workspace, and uses it from then on.

**Planning and automation.** Task management with priorities, projects, and recurrence. Cron jobs — schedule a morning briefing, periodic reporting, or anything else. Aide proactively alerts you about upcoming deadlines.

**Examples:**
- E-shop management — API integration, product descriptions, inventory updates
- SEO research — keyword analysis, site audits, content strategy
- Content creation — writing articles, review, CMS publishing
- Morning briefing — task overview, deadlines, important information
- Invoicing and emails — integration with billing APIs, email services, Discord
- Monitoring — tracking GitHub commits, web changes, RSS feeds
- Research — web search, product comparison, fact-checking

## Requirements

- Python 3 + pip
- [Claude Code CLI](https://claude.com/product/claude-code) installed and in PATH (requires subscription)
- Telegram bot token and/or Slack app tokens

## Installation

### VPS (recommended)

```bash
sudo ./scripts/install_vps.sh
```

The script installs dependencies, creates a venv, sets up systemd services, and configures daily auto-deploy.

After installation, fill in `/opt/aide/workspace/.env` (tokens, user IDs, chat IDs) and run:

```bash
./scripts/run.sh /opt/aide/workspace
```

<details>
<summary>Manual installation (step by step)</summary>

1. Install dependencies: `sudo apt install -y git python3 python3-pip python3-venv python3-full`
2. Install [Claude Code CLI](https://claude.com/product/claude-code) and verify it's in PATH
3. Clone the repo:
   ```bash
   sudo mkdir -p /opt/aide && cd /opt/aide
   git clone https://github.com/PavelTajdus/Aide engine && cd engine
   ```
4. Initialize workspace: `./scripts/init.sh /opt/aide/workspace`
5. Set ownership: `sudo chown -R $USER:$USER /opt/aide`
6. Fill in `/opt/aide/workspace/.env`
7. Create venv and install dependencies:
   ```bash
   python3 -m venv /opt/aide/venv
   /opt/aide/venv/bin/pip install -r /opt/aide/engine/requirements.txt
   ```
8. Run: `PYTHON_BIN=/opt/aide/venv/bin/python ./scripts/run.sh /opt/aide/workspace`

</details>

### Local development

```bash
./scripts/init.sh ~/aide-workspace
# fill in ~/aide-workspace/.env
./scripts/run.sh ~/aide-workspace
```

Detailed setup guides:
- [Telegram setup](docs/TELEGRAM_SETUP.md)
- [Slack setup](docs/SLACK_SETUP.md)

### Deploy and updates

```bash
./scripts/deploy.sh [workspace]    # git pull → pip install → update workspace → restart
```

`install_vps.sh` sets up automatic daily deploy at 3:55 AM.

## Workspace

The workspace is separate from the engine repo — it contains your personal data and should never be committed to the engine.

```
~/aide-workspace/
├── .env                          # Tokens, API keys
├── CLAUDE.md                     # Agent personality and rules
├── .claude/skills/               # Symlinks to default_skills/ + custom
├── core_tools/                   # Symlink to engine/core_tools/
├── tools/                        # Custom tools
├── knowledge/                    # Reference documents
├── data/                         # Sessions, tasks, memory, cron, logs
├── conversations/
└── inbox/                        # Uploaded files from chat
```

The engine finds the workspace by: script argument > env `AIDE_WORKSPACE` > current directory > `~/aide-workspace`.

### Backup

```bash
cd /opt/aide/workspace
git init
cp /opt/aide/engine/templates/workspace.gitignore .gitignore
git add . && git commit -m "initial workspace"
git remote add origin <YOUR_PRIVATE_REPO>
git push -u origin main
```

Then just: `./scripts/backup.sh [workspace] --push`

## Scripts

| Script | Description |
|--------|-------------|
| `run.sh [workspace]` | Start (bot + scheduler) |
| `stop.sh [workspace]` | Stop |
| `restart.sh [workspace]` | Restart + claude update |
| `deploy.sh [workspace]` | Git pull + pip + update + restart |
| `status.sh [workspace]` | Service status |
| `logs.sh [workspace] [bot\|slack\|scheduler]` | Logs |
| `ps.sh [workspace]` | Processes |
| `backup.sh [workspace] [--push]` | Git backup workspace |

## Configuration (.env)

### Telegram

| Variable | Description |
|----------|-------------|
| `TELEGRAM_TOKEN` | Bot token |
| `ALLOWED_USERS` | Allowed Telegram user IDs |
| `AIDE_DEFAULT_CHAT_ID` | Chat ID for notifications and reminders |
| `AIDE_TELEGRAM_ENABLED` | `0` = disabled |
| `AIDE_TELEGRAM_PARSE_MODE` | `markdown_v2` for formatting (default: plain text) |
| `AIDE_TELEGRAM_ESCAPE` | `none\|aggressive` |
| `AIDE_TELEGRAM_PROGRESS` | `1` = status updates during execution |
| `AIDE_TELEGRAM_MAX_FILE_MB` | Max attachment size (default 10) |

### Slack

| Variable | Description |
|----------|-------------|
| `SLACK_BOT_TOKEN` | xoxb-... token |
| `SLACK_APP_TOKEN` | xapp-... token (Socket Mode) |
| `AIDE_SLACK_ENABLED` | `1` = enabled |
| `AIDE_SLACK_ALLOWED_USERS` | Allowed Slack user IDs |
| `AIDE_SLACK_DEFAULT_TARGET` | Channel/user ID for notifications |
| `AIDE_SLACK_DEFAULT_TARGET_TYPE` | `auto\|dm\|channel` (default `auto`) |
| `AIDE_SLACK_MAX_FILE_MB` | Max attachment size (default 10) |
| `AIDE_NOTIFY_PROVIDER` | `slack` for Slack notifications |

### Other

| Variable | Description |
|----------|-------------|
| `AIDE_CLAUDE_SKIP_PERMISSIONS` | `1` = Claude Code without confirmations |
| `AIDE_SCHEDULER_WORKERS` | Parallel cron jobs (default 2) |

## Custom tools and skills

**Tools** are Python CLI scripts in `workspace/tools/`. Aide can create them on its own when you describe what you need — or you can write them manually:
- Input via `argparse`, output JSON `{success, data|error}`
- API keys from `.env`, nothing hardcoded
- Template: `templates/tool_skeleton.py`

**Skills** are Markdown files in `.claude/skills/` that describe when and how the agent should use a tool. Aide comes with built-in skills for memory, tasks, research, and daily overviews.

## Troubleshooting

Check status and logs:

```bash
./scripts/status.sh [workspace]
./scripts/logs.sh [workspace] [bot|slack|scheduler]
```

**Telegram not responding:** verify `TELEGRAM_TOKEN` and `ALLOWED_USERS` in `.env`, check `bot.log`.

**Slack not responding:** verify `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` and `AIDE_SLACK_ALLOWED_USERS`, check `slack.log`.

**Scheduler not sending reminders:** verify `AIDE_DEFAULT_CHAT_ID`, check `scheduler.log`.
