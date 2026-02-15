# Skill: Tasks

## When to activate
- User wants to add, edit, view, or complete tasks.
- Phrases: "add task", "to-do", "remind", "reminder".

## Task statuses
- `open` — active task (default for new tasks)
- `waiting` — blocked on external input (not shown in heartbeat notifications)
- `cancelled` — no longer needed (not shown in heartbeat notifications)
- `completed` — done (use `complete` subcommand, not `update --status completed`)

Only `open` tasks appear in overdue/upcoming heartbeat notifications.
When a task depends on someone else's action, set status to `waiting` and explain in `--context`.

## Multi-user features
- `--assignee "Name"` or `--assignee UUID` — assign task to another user
- `--shared` — create as team task (visible to all, user_id=NULL)
- Tasks assigned to you (assignee_id = your user) are visible in your list

## Steps
1. Gather required info: title, project (optional), due/remind/recurrence.
2. Use core tool `task_manage.py` (add/list/update/complete):
   `python $AIDE_ENGINE/core_tools/task_manage.py ...`
3. Confirm changes and optionally suggest a next step.

## Expected output
- Short confirmation + summary of the change.
