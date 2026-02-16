# Skill: Cron (Scheduled Tasks)

## When to activate
- User wants to schedule a recurring or one-time task.
- User asks for a reminder, timer, periodic check, or scheduled action.
- Phrases: "remind me", "every Monday", "at 8:00", "schedule", "cron", "timer", "za 5 minut", "každý den".

## What you can do
- Schedule any prompt to run automatically (cron expression).
- Examples: daily reports, weekly checks, periodic reminders, data fetches.

## Steps
1. Determine schedule (cron expression) and what should happen (prompt).
2. Use core tool:
   `python $AIDE_ENGINE/core_tools/cron_manage.py add --schedule "CRON_EXPR" --prompt "What to do"`
3. To list existing jobs: `python $AIDE_ENGINE/core_tools/cron_manage.py list`
4. To remove: `python $AIDE_ENGINE/core_tools/cron_manage.py remove --id "UUID"`

## One-time reminders
For "remind me in X minutes/hours" or "remind me at HH:MM":
1. Calculate the exact target time.
2. Create a cron with the specific minute/hour: `--schedule "25 10 16 2 *"` (= 10:25, 16. Feb)
3. Include in the prompt: `"Připomínka: [text]. Po odeslání smaž tento cron job: [JOB_ID]"`
   - Replace [JOB_ID] with the actual ID returned from the add command.
4. The heartbeat runner will execute the prompt at the scheduled time and the job will self-delete.
5. Do NOT tell the user to manually delete the cron. Handle it automatically.

## Cron expression examples
- `*/30 * * * *` — every 30 minutes
- `0 8 * * 1-5` — weekdays at 8:00
- `0 9 * * 1` — every Monday at 9:00
- `0 0 1 * *` — first day of month at midnight
- `30 14 16 2 *` — one-time: 14:30 on Feb 16

## Expected output
- Confirm what was scheduled, when it will run, and the job ID.
- For one-time reminders: just confirm "Připomenu ti v HH:MM." No extra instructions.
