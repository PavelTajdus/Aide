# Aide — Engine Rules

Files in `.claude/rules/auto/` are auto-generated at every agent run. Never modify them.

## Memory

### Saving to memory (proactively, SILENTLY)
On every response check: "Was an important fact mentioned?" If yes, SILENTLY save:
`python $AIDE_ENGINE/core_tools/memory_manage.py add --text "..."`

What to save (without asking):
- Decisions (even small ones)
- User preferences
- Contacts and relationships between people
- Project status and important milestones
- Important deadlines and numbers
- Anything that should survive between conversations

What NOT to save:
- Trivial facts already in CLAUDE.md
- Temporary things (one-off meetings, minor details)
- Duplicates — search before saving to check if it's already in memory

## Context tools (use on demand, not automatically)
Do NOT pre-load memory, logs, or tasks at session start. Only call these when the conversation actually needs them:

- **Previous conversations** — when user asks about past work or what was discussed:
  `cat $AIDE_WORKSPACE/data/logs/conversations-$(date +%Y-%m-%d).log`
  (use yesterday's date if user asks about yesterday, etc.)
- **Memory recall** — when user mentions facts, people, decisions, or preferences from the past:
  `python $AIDE_ENGINE/core_tools/memory_manage.py search --query "..."`
- **Tasks** — when user asks about tasks, deadlines, or to-dos:
  `python $AIDE_ENGINE/core_tools/task_manage.py list`

For simple greetings or general questions, skip these tools entirely.

## Tool rules

### NEVER
- Do not overwrite whole files (append/patch only).
- Do not write directly to `cron.json`, `sessions.json` — use tools.
- Do not run destructive bash commands without confirmation.
- Do not delete data without explicit instruction.

### Tasks (mandatory)
- Manage tasks only via `python $AIDE_ENGINE/core_tools/task_manage.py ...`
- Never claim you can't access tasks — always use the tool.
- Do not describe "how you search" in the workspace; call the tool and return a short result.

### Memory (mandatory)
- Manage memory via `python $AIDE_ENGINE/core_tools/memory_manage.py ...`
- Commands: `add --text "..."`, `search --query "..."`, `list`, `forget --id "UUID"`
- Never claim you can't access memory — always use the tool.

## Tooling conventions (mandatory)
- **Language:** Python 3.
- **Location:** `workspace/tools/<name>.py`.
- **Naming:** `snake_case`, one tool = one responsibility.
- **Input:** always `argparse`, no interactive prompts.
- **Output:** JSON on stdout `{success, data|error}`.
- **Errors:** `exit code != 0` + JSON error.
- **Config:** keys/secrets always from `.env` (e.g. `BRAVE_API_KEY`), never hardcoded.
- **IO:** writes only atomically (temp + rename), never direct overwrite.
- **Docs:** after creating a tool, also create a skill in `.claude/skills/`.

### When you need a new tool
1. Create it in `workspace/tools/` as a Python CLI script.
2. Use argparse for input, validate, write atomically.
3. One tool = one responsibility.
4. Output JSON on stdout (success/error + data).
5. Errors: non-zero exit code + error message.
6. Writes: temp file + rename (never direct overwrite).
7. Register as a skill in `.claude/skills/`.

### When you need a new skill
1. Create it in `.claude/skills/` as markdown.
2. Describe: when to activate, steps, which tools to use, expected output.
3. One skill = one use case.

## Workspace structure

```
/knowledge/     → persistent knowledge (references, research)
/tasks/         → inbox and task notes
/decisions/     → important decisions
/strategic/     → current-focus.md, goals
/tools/         → custom tools
/data/          → sessions, tasks.json, memory.json, cron.json
```

## File writing conventions
- Use UTF-8.
- Do not remove existing content without explicit instruction.
