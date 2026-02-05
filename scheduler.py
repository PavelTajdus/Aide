import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from croniter import croniter

from agent import run_agent
from config import load_workspace_env, resolve_workspace
from core_tools._utils import atomic_write_json, file_lock, load_json, parse_dt
from core_tools.send_message import send_message


POLL_INTERVAL_S = 60
GRACE_WINDOW_S = 61


def _get_worker_count() -> int:
    raw = os.environ.get("AIDE_SCHEDULER_WORKERS", "2").strip().lower()
    try:
        value = int(raw)
    except ValueError:
        value = 2
    return max(1, value)


def _log_line(workspace: Path, text: str) -> None:
    log_dir = workspace / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{datetime.now().date().isoformat()}.log"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat()}] {text}\n")


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


def _heartbeat_soon_hours() -> int:
    raw = os.environ.get("AIDE_HEARTBEAT_SOON_HOURS", "24").strip().lower()
    try:
        value = int(raw)
    except ValueError:
        value = 24
    return max(1, value)


def _format_task_line(task: Dict[str, Any], due_dt: datetime) -> str:
    title = task.get("title") or "(untitled)"
    project = task.get("project")
    due_str = due_dt.isoformat()
    if project:
        return f"- {title} (due {due_str}, projekt: {project})"
    return f"- {title} (due {due_str})"


def _execute_heartbeat_job(workspace: Path) -> None:
    tasks_path = workspace / "data" / "tasks.json"
    overdue: List[Dict[str, Any]] = []
    upcoming: List[Dict[str, Any]] = []
    now = datetime.now()
    soon_hours = _heartbeat_soon_hours()
    soon_cutoff = now + timedelta(hours=soon_hours)

    with file_lock(tasks_path):
        tasks: List[Dict[str, Any]] = load_json(tasks_path, [])
        for task in tasks:
            if task.get("status") == "completed":
                continue
            due_dt = parse_dt(task.get("due"))
            if not due_dt:
                continue
            if due_dt <= now:
                overdue.append({"due": due_dt, "task": task})
            elif due_dt <= soon_cutoff:
                upcoming.append({"due": due_dt, "task": task})

    if not overdue and not upcoming:
        _log_line(workspace, "Heartbeat: nothing to report")
        return

    overdue.sort(key=lambda item: item["due"])
    upcoming.sort(key=lambda item: item["due"])

    lines: List[str] = []
    if overdue:
        lines.append(f"Overdue ({len(overdue)}):")
        lines.extend(_format_task_line(item["task"], item["due"]) for item in overdue)
    if upcoming:
        lines.append(f"Blížící se do {soon_hours}h ({len(upcoming)}):")
        lines.extend(_format_task_line(item["task"], item["due"]) for item in upcoming)

    try:
        send_message("\n".join(lines))
    except Exception as exc:
        _log_line(workspace, f"Heartbeat failed: {exc}")


def _execute_cron_job(workspace: Path, job_id: Optional[str], prompt: str) -> None:
    try:
        if job_id == "heartbeat":
            _execute_heartbeat_job(workspace)
            return
        answer, _sid, _tool_log = run_agent(prompt, working_dir=workspace)
        send_message(answer)
    except Exception as exc:
        _log_line(workspace, f"Cron job failed ({job_id}): {exc}")


def _run_cron_jobs(workspace: Path, now: datetime, executor: ThreadPoolExecutor) -> None:
    cron_path = workspace / "data" / "cron.json"
    due_jobs: List[Dict[str, Any]] = []
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

            try:
                last_run = parse_dt(job.get("last_run"))
                if not _should_run(schedule, last_run, now):
                    continue
            except Exception as exc:
                _log_line(workspace, f"Invalid cron schedule ({job.get('id')}): {schedule} ({exc})")
                continue

            job["last_run"] = now.isoformat()
            due_jobs.append({"id": job.get("id"), "prompt": prompt})
            changed = True

        if changed:
            atomic_write_json(cron_path, jobs)

    for job in due_jobs:
        _log_line(workspace, f"Scheduling cron job {job.get('id')}")
        executor.submit(_execute_cron_job, workspace, job.get("id"), job["prompt"])


def _run_task_reminders(workspace: Path, now: datetime) -> None:
    tasks_path = workspace / "data" / "tasks.json"
    due: List[Dict[str, Any]] = []
    with file_lock(tasks_path):
        tasks: List[Dict[str, Any]] = load_json(tasks_path, [])

        for task in tasks:
            if task.get("status") == "completed":
                continue
            remind_at = parse_dt(task.get("remind"))
            if not remind_at:
                continue
            sent_at = parse_dt(task.get("remind_sent_at"))
            if sent_at and sent_at >= remind_at:
                continue
            if remind_at <= now:
                title = task.get("title", "(untitled)")
                project = task.get("project")
                message = f"Připomínka: {title}"
                if project:
                    message += f" (projekt: {project})"
                due.append({"id": task.get("id"), "message": message})

    if not due:
        return

    sent_ids: List[str] = []
    for item in due:
        try:
            send_message(item["message"])
            if item.get("id"):
                sent_ids.append(item["id"])
        except Exception as exc:
            _log_line(workspace, f"Reminder failed: {exc}")

    if not sent_ids:
        return

    with file_lock(tasks_path):
        tasks = load_json(tasks_path, [])
        changed = False
        for task in tasks:
            if task.get("id") in sent_ids:
                task["remind_sent_at"] = now.isoformat()
                changed = True
        if changed:
            atomic_write_json(tasks_path, tasks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Aide scheduler")
    parser.add_argument("--workspace", default=None)
    args = parser.parse_args()

    workspace = resolve_workspace(args.workspace)
    load_workspace_env(workspace)

    _log_line(workspace, "Scheduler started")
    executor = ThreadPoolExecutor(max_workers=_get_worker_count())

    while True:
        now = datetime.now()
        try:
            _run_cron_jobs(workspace, now, executor)
            _run_task_reminders(workspace, now)
            _cleanup_logs(workspace)
        except Exception as exc:
            _log_line(workspace, f"Scheduler error: {exc}")
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
