import argparse
import json
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


def _db_conn():
    """Get a Postgres connection if DATABASE_URL is set."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return None
    try:
        import psycopg2
        conn = psycopg2.connect(url)
        conn.autocommit = False
        return conn
    except Exception:
        return None


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
            # Strip known prefixes (e.g. "conversations-2026-02-08")
            if "-" in date_str and not date_str[0].isdigit():
                date_str = date_str.split("-", 1)[1]
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


def _format_czech_date(dt: datetime) -> str:
    if dt.hour == 0 and dt.minute == 0:
        return f"{dt.day}. {dt.month}. {dt.year}"
    return f"{dt.day}. {dt.month}. {dt.year} {dt.hour}:{dt.minute:02d}"


def _format_task_line(task: Dict[str, Any], due_dt: datetime) -> str:
    title = task.get("title") or "(untitled)"
    project = task.get("project")
    due_str = _format_czech_date(due_dt)
    if project:
        return f"- *{title}* ({due_str}, {project})"
    return f"- *{title}* ({due_str})"


def _heartbeat_hours() -> tuple:
    start = int(os.environ.get("AIDE_HEARTBEAT_START_HOUR", "8"))
    end = int(os.environ.get("AIDE_HEARTBEAT_END_HOUR", "22"))
    return start, end


def _task_id(task: Dict[str, Any]) -> str:
    return task.get("id", task.get("title", ""))



def _log_heartbeat_db(user_id: Optional[str], event_type: str, task_ids: List[str], action: str) -> None:
    """Log heartbeat actions to DB for dedup and audit."""
    conn = _db_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            for tid in task_ids:
                cur.execute(
                    "INSERT INTO heartbeat_log (user_id, event_type, reference_id, action) "
                    "VALUES (%s, %s, %s, %s)",
                    (user_id, event_type, tid if _is_uuid(tid) else None, action),
                )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


def _is_uuid(val: str) -> bool:
    try:
        import uuid
        uuid.UUID(val)
        return True
    except (ValueError, AttributeError):
        return False


def _heartbeat_reported_today_db(user_id: Optional[str]) -> Optional[set]:
    """Get task IDs already reported today from heartbeat_log.

    Returns None on DB failure (caller should fallback to JSON).
    Returns empty set if DB works but nothing reported yet.
    """
    conn = _db_conn()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT reference_id FROM heartbeat_log "
                "WHERE event_type = 'task_reminder' "
                "AND created_at::date = CURRENT_DATE "
                "AND (%s IS NULL OR user_id = %s)",
                (user_id, user_id),
            )
            return {str(row[0]) for row in cur.fetchall() if row[0]}
    except Exception:
        return None
    finally:
        conn.close()


def _load_heartbeat_tasks_for_user(user_id: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """Load open tasks with due dates from Postgres, filtered by user."""
    conn = _db_conn()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            if user_id:
                cur.execute(
                    "SELECT id, title, status, priority, project, due_date, remind_at "
                    "FROM tasks WHERE status = 'open' AND due_date IS NOT NULL "
                    "AND (user_id = %s OR user_id IS NULL)",
                    (user_id,),
                )
            else:
                cur.execute(
                    "SELECT id, title, status, priority, project, due_date, remind_at "
                    "FROM tasks WHERE status = 'open' AND due_date IS NOT NULL"
                )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            for r in rows:
                dd = r.get("due_date")
                if dd:
                    r["due"] = dd.isoformat() if hasattr(dd, "isoformat") else str(dd)
            return rows
    except Exception:
        return None
    finally:
        conn.close()


def _execute_heartbeat_job(workspace: Path, slack_user_id: Optional[str] = None, user_id: Optional[str] = None) -> None:
    now_hour = datetime.now().hour
    start_hour, end_hour = _heartbeat_hours()
    if now_hour < start_hour or now_hour >= end_hour:
        _log_line(workspace, f"Heartbeat: outside working hours ({start_hour}-{end_hour}), skipping")
        return

    overdue: List[Dict[str, Any]] = []
    upcoming: List[Dict[str, Any]] = []
    now = datetime.now()
    soon_hours = _heartbeat_soon_hours()
    soon_cutoff = now + timedelta(hours=soon_hours)

    # Try Postgres first (per-user filtered), fallback to JSON
    db_tasks = _load_heartbeat_tasks_for_user(user_id)
    if db_tasks is not None:
        tasks = db_tasks
    else:
        tasks_path = workspace / "data" / "tasks.json"
        with file_lock(tasks_path):
            tasks = load_json(tasks_path, [])

    for task in tasks:
        if task.get("status") != "open":
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

    # Dedup: check DB first, fallback to local file
    db_reported = _heartbeat_reported_today_db(user_id)
    if db_reported is not None:
        reported_ids = db_reported
    else:
        heartbeat_path = workspace / "data" / "last_heartbeat.json"
        last_hb: Dict[str, Any] = {}
        try:
            last_hb = json.loads(heartbeat_path.read_text()) if heartbeat_path.exists() else {}
        except Exception:
            pass
        today = now.date().isoformat()
        reported_ids = set(last_hb.get("reported_ids", [])) if last_hb.get("date") == today else set()

    new_overdue = [item for item in overdue if _task_id(item["task"]) not in reported_ids]
    new_upcoming = [item for item in upcoming if _task_id(item["task"]) not in reported_ids]

    if not new_overdue and not new_upcoming:
        _log_line(workspace, "Heartbeat: all tasks already reported today, skipping")
        return

    new_overdue.sort(key=lambda item: item["due"])
    new_upcoming.sort(key=lambda item: item["due"])

    lines: List[str] = []
    if new_overdue:
        lines.append(f"Po termínu ({len(new_overdue)}):")
        lines.extend(_format_task_line(item["task"], item["due"]) for item in new_overdue)
    if new_upcoming:
        lines.append(f"Blížící se ({len(new_upcoming)}):")
        lines.extend(_format_task_line(item["task"], item["due"]) for item in new_upcoming)

    new_task_ids = [_task_id(item["task"]) for item in new_overdue + new_upcoming]

    try:
        send_message("\n".join(lines), chat_id=slack_user_id)
        # Log to DB for dedup
        _log_heartbeat_db(user_id, "task_reminder", new_task_ids, "sent")
        # Also write local file as fallback
        heartbeat_path = workspace / "data" / "last_heartbeat.json"
        all_ids = reported_ids | set(new_task_ids)
        heartbeat_path.write_text(json.dumps({
            "reported_ids": sorted(all_ids),
            "date": now.date().isoformat(),
            "sent_at": now.isoformat(),
        }))
    except Exception as exc:
        _log_line(workspace, f"Heartbeat failed: {exc}")


_WORKSPACES_ROOT = Path(os.environ.get("AIDE_WORKSPACES_ROOT", "/opt/aide/workspaces"))


def _resolve_job_workspace(default_workspace: Path, user_id: Optional[str]) -> Path:
    """Resolve workspace for a cron job. Per-user if user_id set, else default."""
    if not user_id:
        return default_workspace
    user_ws = _WORKSPACES_ROOT / str(user_id)
    if user_ws.exists():
        return user_ws
    return default_workspace


def _execute_cron_job(
    workspace: Path,
    job_id: Optional[str],
    prompt: str,
    job_type: str = "cron",
    slack_user_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    try:
        if job_type == "heartbeat" or job_id == "heartbeat":
            _execute_heartbeat_job(workspace, slack_user_id=slack_user_id, user_id=user_id)
            return
        answer, _sid, _tool_log = run_agent(prompt, working_dir=workspace)
        send_message(answer, chat_id=slack_user_id)
    except Exception as exc:
        _log_line(workspace, f"Cron job failed ({job_id}): {exc}")


def _run_cron_jobs_db(workspace: Path, now: datetime, executor: ThreadPoolExecutor) -> bool:
    """Run cron jobs from Postgres. Returns True if DB was used, False to fallback."""
    conn = _db_conn()
    if not conn:
        return False
    try:
        due_jobs: List[Dict[str, Any]] = []
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.id, c.schedule, c.task, c.last_run, c.type, c.user_id, "
                "       u.slack_id, u.active "
                "FROM cron_jobs c "
                "LEFT JOIN users u ON c.user_id = u.id "
                "WHERE c.enabled = true"
            )
            cols = [d[0] for d in cur.description]
            jobs = [dict(zip(cols, row)) for row in cur.fetchall()]

        for job in jobs:
            # Skip jobs for inactive users
            if job.get("user_id") and job.get("active") is False:
                continue

            schedule = job.get("schedule")
            prompt = job.get("task")
            if not schedule or not prompt:
                continue

            try:
                last_run_raw = job.get("last_run")
                if isinstance(last_run_raw, datetime):
                    last_run = last_run_raw.replace(tzinfo=None)
                else:
                    last_run = parse_dt(str(last_run_raw) if last_run_raw else None)
                if not _should_run(schedule, last_run, now):
                    continue
            except Exception as exc:
                _log_line(workspace, f"Invalid cron schedule ({job.get('id')}): {schedule} ({exc})")
                continue

            due_jobs.append({
                "id": job.get("id"),
                "prompt": prompt,
                "type": job.get("type", "cron"),
                "user_id": str(job["user_id"]) if job.get("user_id") else None,
                "slack_id": job.get("slack_id"),
            })

        # Update last_run for due jobs
        if due_jobs:
            with conn.cursor() as cur:
                for job in due_jobs:
                    cur.execute(
                        "UPDATE cron_jobs SET last_run = %s WHERE id = %s",
                        (now, job["id"]),
                    )
            conn.commit()

        for job in due_jobs:
            job_ws = _resolve_job_workspace(workspace, job.get("user_id"))
            _log_line(workspace, f"Scheduling cron job {job.get('id')} (type={job.get('type')}, user={job.get('user_id', 'system')})")
            executor.submit(
                _execute_cron_job,
                job_ws,
                job.get("id"),
                job["prompt"],
                job.get("type", "cron"),
                job.get("slack_id"),
                job.get("user_id"),
            )

        return True
    except Exception as exc:
        _log_line(workspace, f"DB cron query failed, falling back to JSON: {exc}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def _run_cron_jobs(workspace: Path, now: datetime, executor: ThreadPoolExecutor) -> None:
    if _run_cron_jobs_db(workspace, now, executor):
        return

    # Fallback to JSON
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


def _run_task_reminders_db(workspace: Path, now: datetime) -> bool:
    """Check and send task reminders from Postgres. Returns True if DB was used."""
    conn = _db_conn()
    if not conn:
        return False
    try:
        due: List[Dict[str, Any]] = []
        with conn.cursor() as cur:
            cur.execute(
                "SELECT t.id, t.title, t.project, t.remind_at, t.remind_sent_at, "
                "       u.slack_id, u.active "
                "FROM tasks t "
                "LEFT JOIN users u ON t.user_id = u.id "
                "WHERE t.status = 'open' AND t.remind_at IS NOT NULL "
                "AND t.remind_at <= %s AND (t.remind_sent_at IS NULL OR t.remind_sent_at < t.remind_at)",
                (now,),
            )
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                task = dict(zip(cols, row))
                # Skip tasks for inactive users
                if task.get("active") is False:
                    continue
                title = task.get("title", "(untitled)")
                project = task.get("project")
                message = f"Reminder: {title}"
                if project:
                    message += f" (project: {project})"
                due.append({
                    "id": str(task["id"]),
                    "message": message,
                    "slack_id": task.get("slack_id"),
                })

        if not due:
            return True

        sent_ids: List[str] = []
        for item in due:
            try:
                send_message(item["message"], chat_id=item.get("slack_id"))
                sent_ids.append(item["id"])
            except Exception as exc:
                _log_line(workspace, f"Reminder failed: {exc}")

        if sent_ids:
            with conn.cursor() as cur:
                for sid in sent_ids:
                    cur.execute(
                        "UPDATE tasks SET remind_sent_at = %s WHERE id = %s",
                        (now, sid),
                    )
            conn.commit()

        return True
    except Exception as exc:
        _log_line(workspace, f"DB reminder query failed, falling back to JSON: {exc}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def _run_task_reminders(workspace: Path, now: datetime) -> None:
    if _run_task_reminders_db(workspace, now):
        return

    # Fallback to JSON
    tasks_path = workspace / "data" / "tasks.json"
    due: List[Dict[str, Any]] = []
    with file_lock(tasks_path):
        tasks: List[Dict[str, Any]] = load_json(tasks_path, [])

        for task in tasks:
            if task.get("status") != "open":
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
                message = f"Reminder: {title}"
                if project:
                    message += f" (project: {project})"
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
