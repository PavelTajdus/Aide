# Aide Engine

This is the Aide engine repo — the runtime that powers the Aide personal AI copilot.

## Architecture

- `agent.py` — runs Claude Code CLI as subprocess, parses streaming JSON events
- `config.py` — workspace resolution, env loading, auto-context generation
- `context.py` — memory recall, conversation logging
- `main.py` — Telegram bot (python-telegram-bot, async)
- `slack_bot.py` — Slack bot (slack-bolt, Socket Mode)
- `scheduler.py` — cron job runner (APScheduler)
- `core_tools/` — CLI tools the agent calls: tasks, memory, cron, projects, send_message
- `default_skills/` — skill definitions symlinked into workspace
- `templates/context/` — modular context templates (soul, user, tools, channel)
- `scripts/` — init, update, deploy, run, restart, backup

## Modular context system

Workspace context is split across files that Claude Code loads natively:

```
$WORKSPACE/
├── CLAUDE.md                          # Auto-generated (by generate_auto_context)
├── .claude/
│   ├── rules/
│   │   ├── soul.md                    # Persona, tone, style (user-owned, copy-once)
│   │   ├── user.md                    # User profile, preferences (user-owned, copy-once)
│   │   ├── channel.md                 # Channel formatting rules (user-owned, copy-once)
│   │   ├── tools.md                   # Engine rules (SYMLINK → engine/templates/context/tools.md)
│   │   └── auto/                      # Regenerated at every run_agent() call
│   │       ├── skills.md              # From .claude/skills/*.md
│   │       ├── tasks.md               # From data/tasks.json
│   │       ├── cron.md                # From data/cron.json
│   │       └── projects.md            # From data/projects.json
│   └── skills/                        # Symlinks → engine/default_skills/ + custom
```

**User-owned files** (soul.md, user.md, channel.md) are copied once from templates and never overwritten by deploy.

**Engine-managed** (tools.md) is a symlink — updates automatically on deploy.

**Auto-generated** (auto/*) are written by `config.py:generate_auto_context()` before every agent run.

**CLAUDE.md** is auto-generated — inlines user.md content so Claude Code always sees the user context at top level.

## Code conventions

- All prompts and instructions in source code MUST be in English. The agent responds in the user's language, but code stays English.
- Tools are Python CLI scripts with argparse input and JSON stdout output.
- Writes are atomic (temp file + rename), never direct overwrite.
- All functions that run before/during agent execution must be crash-safe (try/except, never raise).

## Key paths

- Engine: code lives here, deployed via git
- Workspace: user data, separate from engine, never in git (has its own optional backup)
- `scripts/init.sh <path>` creates a new workspace
- `scripts/update.sh <path>` refreshes symlinks and engine version
- `scripts/deploy.sh <path>` does git pull + pip + update + restart

## Testing changes

After modifying context templates or auto-generation:
```bash
./scripts/init.sh /tmp/test-ws
python3 -c "from config import generate_auto_context; from pathlib import Path; generate_auto_context(Path('/tmp/test-ws'))"
cat /tmp/test-ws/CLAUDE.md
ls /tmp/test-ws/.claude/rules/auto/
rm -rf /tmp/test-ws
```
