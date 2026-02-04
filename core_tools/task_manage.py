import argparse
import json
import sys
import uuid
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from croniter import croniter

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import atomic_write_json, file_lock, iso_now, load_json, parse_dt, resolve_workspace


def _tasks_path(workspace):
    return workspace / "data" / "tasks.json"


def _advance_due(due: Optional[str], recurrence: str) -> Optional[str]:
    base = parse_dt(due) or datetime.now()
    rec = recurrence.strip().lower()

    if rec == "daily":
        return (base + timedelta(days=1)).isoformat()
    if rec == "weekly":
        return (base + timedelta(days=7)).isoformat()
    if rec == "monthly":
        year = base.year
        month = base.month + 1
        if month == 13:
            month = 1
            year += 1
        day = base.day
        # clamp day to last day of month
        import calendar

        last_day = calendar.monthrange(year, month)[1]
        day = min(day, last_day)
        return base.replace(year=year, month=month, day=day).isoformat()

    # Cron expression
    if len(rec.split()) >= 5:
        itr = croniter(rec, base)
        return itr.get_next(datetime).isoformat()

    return None


def list_tasks(workspace, status: Optional[str]) -> None:
    tasks: List[Dict[str, Any]] = load_json(_tasks_path(workspace), [])
    if status:
        tasks = [t for t in tasks if t.get("status") == status]
    print(json.dumps({"success": True, "data": tasks}, ensure_ascii=False))


def add_task(workspace, args) -> None:
    path = _tasks_path(workspace)
    with file_lock(path):
        tasks = load_json(path, [])
        task_id = str(uuid.uuid4())
        task = {
            "id": task_id,
            "title": args.title,
            "project": args.project,
            "status": "open",
            "priority": args.priority,
            "context": args.context,
            "created": iso_now(),
            "due": args.due,
            "remind": args.remind,
            "recurrence": args.recurrence,
        }
        tasks.append(task)
        atomic_write_json(path, tasks)
    print(json.dumps({"success": True, "data": {"id": task_id}}, ensure_ascii=False))


def update_task(workspace, args) -> None:
    path = _tasks_path(workspace)
    with file_lock(path):
        tasks = load_json(path, [])
        found = False
        for task in tasks:
            if task.get("id") == args.id:
                for field in ("title", "project", "status", "priority", "context", "due", "remind", "recurrence"):
                    value = getattr(args, field)
                    if value is not None:
                        task[field] = value
                found = True
        if not found:
            print(json.dumps({"success": False, "error": "Task not found"}, ensure_ascii=False))
            sys.exit(1)
        atomic_write_json(path, tasks)
    print(json.dumps({"success": True, "data": {"id": args.id}}, ensure_ascii=False))


def complete_task(workspace, task_id: str) -> None:
    path = _tasks_path(workspace)
    with file_lock(path):
        tasks = load_json(path, [])
        new_task = None
        found = False
        for task in tasks:
            if task.get("id") == task_id:
                task["status"] = "completed"
                task["completed"] = iso_now()
                found = True
                rec = task.get("recurrence")
                if rec:
                    new_due = _advance_due(task.get("due"), rec)
                    new_remind = None
                    due_dt = parse_dt(task.get("due"))
                    remind_dt = parse_dt(task.get("remind"))
                    if new_due and due_dt and remind_dt:
                        delta = due_dt - remind_dt
                        new_due_dt = parse_dt(new_due)
                        if new_due_dt:
                            new_remind = (new_due_dt - delta).isoformat()
                    new_task = {
                        "id": str(uuid.uuid4()),
                        "title": task.get("title"),
                        "project": task.get("project"),
                        "status": "open",
                        "priority": task.get("priority"),
                        "context": task.get("context"),
                        "created": iso_now(),
                        "due": new_due,
                        "remind": new_remind,
                        "recurrence": rec,
                    }
        if not found:
            print(json.dumps({"success": False, "error": "Task not found"}, ensure_ascii=False))
            sys.exit(1)
        if new_task:
            tasks.append(new_task)
        atomic_write_json(path, tasks)
    print(json.dumps({"success": True, "data": {"id": task_id}}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage tasks")
    sub = parser.add_subparsers(dest="cmd", required=True)

    list_p = sub.add_parser("list")
    list_p.add_argument("--status", default=None)

    add_p = sub.add_parser("add")
    add_p.add_argument("--title", required=True)
    add_p.add_argument("--project", default=None)
    add_p.add_argument("--priority", default=None)
    add_p.add_argument("--context", default=None)
    add_p.add_argument("--due", default=None)
    add_p.add_argument("--remind", default=None)
    add_p.add_argument("--recurrence", default=None)

    up_p = sub.add_parser("update")
    up_p.add_argument("--id", required=True)
    up_p.add_argument("--title")
    up_p.add_argument("--project")
    up_p.add_argument("--status")
    up_p.add_argument("--priority")
    up_p.add_argument("--context")
    up_p.add_argument("--due")
    up_p.add_argument("--remind")
    up_p.add_argument("--recurrence")

    comp_p = sub.add_parser("complete")
    comp_p.add_argument("--id", required=True)

    args = parser.parse_args()
    workspace = resolve_workspace()

    try:
        if args.cmd == "list":
            list_tasks(workspace, args.status)
        elif args.cmd == "add":
            add_task(workspace, args)
        elif args.cmd == "update":
            update_task(workspace, args)
        elif args.cmd == "complete":
            complete_task(workspace, args.id)
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
