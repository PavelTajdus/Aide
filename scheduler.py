import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from croniter import croniter

from agent import run_agent
from config import load_workspace_env, resolve_workspace
from core_tools._utils import atomic_write_json, file_lock, load_json
from core_tools.send_message import send_message


POLL_INTERVAL_S = 60
GRACE_WINDOW_S = 61


def _log_line(workspace: Path, text: str) -> None:
    log_dir = workspace / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{datetime.now().date().isoformat()}.log"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat()}] {text}\n")


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _is_daily(schedule: str) -> bool:
    parts = schedule.split()
    if len(parts) != 5:
        return False
    minute, hour, dom, month, dow = parts
    return dom == "*" and month == "*" and dow == "*" and minute != "*" and hour != "*"


def _should_run(schedule: str, last_run: Optional[datetime], now: datetime) -> bool:
    itr = croniter(schedule, now)
    prev = itr.get_prev(datetime)

    if last_run and last_run >= prev:
        return False

    if prev >= now - timedelta(seconds=GRACE_WINDOW_S):
        return True

    if _is_daily(schedule) and prev.date() == now.date():
        return True

    return False


def _cleanup_logs(workspace: Path, days: int = 14) -> None:
    log_dir = workspace / "data" / "logs"
    if not log_dir.exists():
        return
    cutoff = datetime.now().date() - timedelta(days=days)
    for path in log_dir.glob("*.log"):
        try:
            date_str = path.stem
            date = datetime.fromisoformat(date_str).date()
            if date < cutoff:
                path.unlink(missing_ok=True)
        except Exception:
            continue


def _run_cron_jobs(workspace: Path, now: datetime) -> None:
    cron_path = workspace / "data" / "cron.json"
    with file_lock(cron_path):
        jobs: List[Dict[str, Any]] = load_json(cron_path, [])
        changed = False

        for job in jobs:
            if not job.get("enabled", True):
                continue
            schedule = job.get("schedule")
            prompt = job.get("prompt")
            if not schedule or not prompt:
                continue

            last_run = _parse_dt(job.get("last_run"))
            if not _should_run(schedule, last_run, now):
                continue

            _log_line(workspace, f"Running cron job {job.get('id')}")
            try:
                answer, _sid, _tool_log = run_agent(prompt, working_dir=workspace)
                send_message(answer)
                job["last_run"] = now.isoformat()
                changed = True
            except Exception as exc:
                _log_line(workspace, f"Cron job failed: {exc}")

        if changed:
            atomic_write_json(cron_path, jobs)


def _run_task_reminders(workspace: Path, now: datetime) -> None:
    tasks_path = workspace / "data" / "tasks.json"
    with file_lock(tasks_path):
        tasks: List[Dict[str, Any]] = load_json(tasks_path, [])
        changed = False

        for task in tasks:
            if task.get("status") == "completed":
                continue
            remind_at = _parse_dt(task.get("remind"))
            if not remind_at:
                continue
            if task.get("remind_sent_at"):
                continue
            if remind_at <= now:
                title = task.get("title", "(untitled)")
                project = task.get("project")
                message = f"Připomínka: {title}"
                if project:
                    message += f" (projekt: {project})"
                try:
                    send_message(message)
                    task["remind_sent_at"] = now.isoformat()
                    changed = True
                except Exception as exc:
                    _log_line(workspace, f"Reminder failed: {exc}")

        if changed:
            atomic_write_json(tasks_path, tasks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Aide scheduler")
    parser.add_argument("--workspace", default=None)
    args = parser.parse_args()

    workspace = resolve_workspace(args.workspace)
    load_workspace_env(workspace)

    _log_line(workspace, "Scheduler started")

    while True:
        now = datetime.now()
        try:
            _run_cron_jobs(workspace, now)
            _run_task_reminders(workspace, now)
            _cleanup_logs(workspace)
        except Exception as exc:
            _log_line(workspace, f"Scheduler error: {exc}")
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
