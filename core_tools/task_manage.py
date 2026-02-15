import argparse
import json
import os
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from croniter import croniter

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import resolve_workspace

# --- Database connection ---

_DB_URL = None


def _get_db_url() -> str:
    global _DB_URL
    if _DB_URL is None:
        _DB_URL = os.environ.get("DATABASE_URL", "")
    if not _DB_URL:
        raise RuntimeError("DATABASE_URL not set")
    return _DB_URL


def _get_conn():
    import psycopg2
    conn = psycopg2.connect(_get_db_url())
    conn.autocommit = False
    return conn


def _get_user_id() -> Optional[str]:
    return os.environ.get("AIDE_USER_ID")


def _iso_now() -> str:
    return datetime.now().isoformat()


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


# --- Recurrence ---


def _advance_due(due: Optional[str], recurrence: str) -> Optional[str]:
    base = _parse_dt(due) or datetime.now()
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
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        day = min(base.day, last_day)
        return base.replace(year=year, month=month, day=day).isoformat()

    if len(rec.split()) >= 5:
        itr = croniter(rec, base)
        return itr.get_next(datetime).isoformat()

    return None


# --- Row formatting ---


def _row_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(row)
    d["id"] = str(d["id"])
    for key in ("user_id", "assignee_id"):
        if d.get(key):
            d[key] = str(d[key])
    for key in ("created_at", "updated_at", "completed_at", "remind_at", "remind_sent_at"):
        if d.get(key):
            d[key] = d[key].isoformat()
    if d.get("due_date"):
        d["due_date"] = d["due_date"].isoformat()
    # Backward compat aliases
    d["title"] = d.get("title", "")
    d["status"] = d.get("status", "open")
    d["created"] = d.get("created_at", "")
    d["due"] = d.get("due_date", "")
    d["remind"] = d.get("remind_at", "")
    d["priority"] = d.get("priority", "")
    d["context"] = d.get("context", "")
    d["project"] = d.get("project", "")
    d["recurrence"] = d.get("recurrence", "")
    return d


# --- User filter ---


def _user_filter(user_id: Optional[str]) -> tuple:
    """Tasks visible to user: own + assigned to + team (NULL)."""
    if user_id:
        return "(user_id = %s OR assignee_id = %s OR user_id IS NULL)", [user_id, user_id]
    return "TRUE", []


# --- Commands ---


def list_tasks(workspace: Path, status: Optional[str]) -> None:
    import psycopg2.extras

    user_id = _get_user_id()
    user_sql, user_params = _user_filter(user_id)

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            sql = f"SELECT * FROM tasks WHERE {user_sql}"
            params = list(user_params)
            if status:
                sql += " AND status = %s"
                params.append(status)
            sql += " ORDER BY created_at DESC"
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    tasks = [_row_to_dict(r) for r in rows]
    print(json.dumps({"success": True, "data": tasks}, ensure_ascii=False))


def _resolve_assignee(assignee_raw: Optional[str]) -> Optional[str]:
    """Resolve assignee to user UUID. Accepts UUID or user name (case-insensitive)."""
    if not assignee_raw:
        return None
    # If it looks like a UUID, return directly
    try:
        uuid.UUID(assignee_raw)
        return assignee_raw
    except ValueError:
        pass
    # Try to find by name
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM users WHERE LOWER(name) = LOWER(%s) AND active = true",
                (assignee_raw,),
            )
            row = cur.fetchone()
            if row:
                return str(row[0])
    finally:
        conn.close()
    return None


def add_task(workspace: Path, args) -> None:
    import psycopg2.extras

    task_id = str(uuid.uuid4())
    user_id = None if getattr(args, "shared", False) else _get_user_id()
    raw_assignee = getattr(args, "assignee", None)
    assignee_id = _resolve_assignee(raw_assignee)
    if raw_assignee and assignee_id is None:
        print(json.dumps({"success": False, "error": f"Assignee '{raw_assignee}' not found"}, ensure_ascii=False))
        sys.exit(1)

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO tasks (id, user_id, assignee_id, title, project, status, priority, context, due_date, remind_at, recurrence)
                   VALUES (%s, %s, %s, %s, %s, 'open', %s, %s, %s, %s, %s)""",
                (task_id, user_id, assignee_id, args.title, args.project, args.priority,
                 args.context, args.due or None, args.remind or None, args.recurrence or None),
            )
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"success": True, "data": {"id": task_id, "assignee_id": assignee_id}}, ensure_ascii=False))


def update_task(workspace: Path, args) -> None:
    import psycopg2.extras

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Build SET clause dynamically
            fields = []
            values = []
            assignee_id = _resolve_assignee(getattr(args, "assignee", None))
            field_map = {
                "title": args.title,
                "project": args.project,
                "status": args.status,
                "priority": args.priority,
                "context": args.context,
                "due_date": args.due or None,
                "remind_at": args.remind or None,
                "recurrence": args.recurrence,
                "assignee_id": assignee_id,
            }
            for col, val in field_map.items():
                if val is not None:
                    fields.append(f"{col} = %s")
                    values.append(val)

            # Reset remind_sent_at when remind_at changes
            if args.remind is not None:
                fields.append("remind_sent_at = NULL")

            if not fields:
                print(json.dumps({"success": False, "error": "No fields to update"}, ensure_ascii=False))
                sys.exit(1)

            user_id = _get_user_id()
            user_sql, user_params = _user_filter(user_id)
            values.append(args.id)
            sql = f"UPDATE tasks SET {', '.join(fields)} WHERE id = %s AND {user_sql}"
            cur.execute(sql, values + list(user_params))
            if cur.rowcount == 0:
                print(json.dumps({"success": False, "error": "Task not found"}, ensure_ascii=False))
                sys.exit(1)
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"success": True, "data": {"id": args.id}}, ensure_ascii=False))


def complete_task(workspace: Path, task_id: str) -> None:
    import psycopg2.extras

    user_id = _get_user_id()
    user_sql, user_params = _user_filter(user_id)

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Get task first for recurrence handling (filtered by ownership)
            cur.execute(
                f"SELECT * FROM tasks WHERE id = %s AND {user_sql}",
                [task_id] + list(user_params),
            )
            task = cur.fetchone()
            if not task:
                print(json.dumps({"success": False, "error": "Task not found"}, ensure_ascii=False))
                sys.exit(1)

            cur.execute(
                "UPDATE tasks SET status = 'completed', completed_at = NOW() WHERE id = %s",
                (task_id,),
            )

            # Handle recurrence
            rec = task.get("recurrence")
            if rec:
                due_str = task["due_date"].isoformat() if task.get("due_date") else None
                new_due = _advance_due(due_str, rec)
                new_remind = None
                if new_due and task.get("due_date") and task.get("remind_at"):
                    due_as_date = task["due_date"] if isinstance(task["due_date"], date) else task["due_date"].date() if hasattr(task["due_date"], "date") else None
                    remind_as_date = task["remind_at"].date() if hasattr(task["remind_at"], "date") else None
                    if due_as_date and remind_as_date:
                        delta = due_as_date - remind_as_date
                    else:
                        delta = timedelta(0)
                    new_due_dt = _parse_dt(new_due)
                    if new_due_dt and delta:
                        new_remind = (new_due_dt - delta).isoformat()

                new_id = str(uuid.uuid4())
                cur.execute(
                    """INSERT INTO tasks (id, user_id, assignee_id, title, project, status, priority, context, due_date, remind_at, recurrence)
                       VALUES (%s, %s, %s, %s, %s, 'open', %s, %s, %s, %s, %s)""",
                    (new_id, str(task["user_id"]) if task.get("user_id") else None,
                     str(task["assignee_id"]) if task.get("assignee_id") else None,
                     task["title"], task["project"], task["priority"],
                     task["context"], new_due, new_remind, rec),
                )

        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"success": True, "data": {"id": task_id}}, ensure_ascii=False))


# --- CLI ---


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage tasks (PostgreSQL)")
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
    add_p.add_argument("--assignee", default=None, help="Assign to user (UUID or name)")
    add_p.add_argument("--shared", action="store_true", help="Create as team task (user_id=NULL)")

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
    up_p.add_argument("--assignee", default=None, help="Assign to user (UUID or name)")

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
