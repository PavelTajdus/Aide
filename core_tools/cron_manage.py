import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import atomic_write_json, file_lock, iso_now, load_json, resolve_workspace

_DB_URL: Optional[str] = None


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


def _get_user_id() -> str:
    """Required — multi-user mode only."""
    uid = os.environ.get("AIDE_USER_ID")
    if not uid:
        print(json.dumps({"success": False, "error": "AIDE_USER_ID not set. Cannot operate without user identity."}))
        sys.exit(1)
    return uid


def _cron_path(workspace):
    return workspace / "data" / "cron.json"


def list_jobs(workspace) -> None:
    conn = None
    try:
        conn = _get_conn()
        user_id = _get_user_id()
        with conn.cursor() as cur:
            if user_id:
                cur.execute(
                    "SELECT id, user_id, type, schedule, command, task, enabled, last_run, created_at "
                    "FROM cron_jobs WHERE user_id = %s OR user_id IS NULL ORDER BY created_at",
                    (user_id,),
                )
            else:
                cur.execute(
                    "SELECT id, user_id, type, schedule, command, task, enabled, last_run, created_at "
                    "FROM cron_jobs ORDER BY created_at"
                )
            cols = [d[0] for d in cur.description]
            jobs = []
            for row in cur.fetchall():
                job = dict(zip(cols, row))
                for k in ("last_run", "created_at"):
                    if job.get(k) and hasattr(job[k], "isoformat"):
                        job[k] = job[k].isoformat()
                if job.get("user_id"):
                    job["user_id"] = str(job["user_id"])
                jobs.append(job)
        print(json.dumps({"success": True, "data": jobs}, ensure_ascii=False))
    except Exception:
        # Fallback to JSON
        jobs: List[Dict[str, Any]] = load_json(_cron_path(workspace), [])
        print(json.dumps({"success": True, "data": jobs}, ensure_ascii=False))
    finally:
        if conn:
            conn.close()


def add_job(workspace, schedule: str, prompt: str, job_type: str = "cron") -> None:
    job_id = str(uuid.uuid4())
    user_id = _get_user_id()
    conn = None
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO cron_jobs (id, user_id, type, schedule, task, enabled) "
                "VALUES (%s, %s, %s, %s, %s, true)",
                (job_id, user_id, job_type, schedule, prompt),
            )
        conn.commit()
    except Exception:
        # Fallback to JSON
        path = _cron_path(workspace)
        with file_lock(path):
            jobs: List[Dict[str, Any]] = load_json(path, [])
            jobs.append(
                {
                    "id": job_id,
                    "schedule": schedule,
                    "prompt": prompt,
                    "enabled": True,
                    "created": iso_now(),
                    "last_run": None,
                }
            )
            atomic_write_json(path, jobs)
    finally:
        if conn:
            conn.close()

    print(json.dumps({"success": True, "data": {"id": job_id}}, ensure_ascii=False))


def _ownership_filter(user_id: Optional[str]) -> tuple:
    """Return SQL fragment and params for ownership check."""
    if user_id:
        return "AND (user_id = %s OR user_id IS NULL)", (user_id,)
    return "", ()


def remove_job(workspace, job_id: str) -> None:
    conn = None
    user_id = _get_user_id()
    own_sql, own_params = _ownership_filter(user_id)
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM cron_jobs WHERE id = %s {own_sql}", (job_id,) + own_params)
            if cur.rowcount == 0:
                print(json.dumps({"success": False, "error": "Cron job not found"}, ensure_ascii=False))
                sys.exit(1)
        conn.commit()
    except SystemExit:
        raise
    except Exception:
        path = _cron_path(workspace)
        with file_lock(path):
            jobs = load_json(path, [])
            new_jobs = [j for j in jobs if j.get("id") != job_id]
            if len(new_jobs) == len(jobs):
                print(json.dumps({"success": False, "error": "Cron job not found"}, ensure_ascii=False))
                sys.exit(1)
            atomic_write_json(path, new_jobs)
    finally:
        if conn:
            conn.close()
    print(json.dumps({"success": True, "data": {"id": job_id}}, ensure_ascii=False))


def enable_job(workspace, job_id: str, enabled: bool) -> None:
    conn = None
    user_id = _get_user_id()
    own_sql, own_params = _ownership_filter(user_id)
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE cron_jobs SET enabled = %s WHERE id = %s {own_sql}",
                (enabled, job_id) + own_params,
            )
            if cur.rowcount == 0:
                print(json.dumps({"success": False, "error": "Cron job not found"}, ensure_ascii=False))
                sys.exit(1)
        conn.commit()
    except SystemExit:
        raise
    except Exception:
        path = _cron_path(workspace)
        with file_lock(path):
            jobs = load_json(path, [])
            found = False
            for j in jobs:
                if j.get("id") == job_id:
                    j["enabled"] = enabled
                    found = True
            if not found:
                print(json.dumps({"success": False, "error": "Cron job not found"}, ensure_ascii=False))
                sys.exit(1)
            atomic_write_json(path, jobs)
    finally:
        if conn:
            conn.close()
    print(json.dumps({"success": True, "data": {"id": job_id, "enabled": enabled}}, ensure_ascii=False))


def update_job(workspace, job_id: str, schedule: Optional[str], prompt: Optional[str]) -> None:
    conn = None
    user_id = _get_user_id()
    own_sql, own_params = _ownership_filter(user_id)
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            sets = []
            vals = []
            if schedule:
                sets.append("schedule = %s")
                vals.append(schedule)
            if prompt:
                sets.append("task = %s")
                vals.append(prompt)
            if not sets:
                print(json.dumps({"success": True, "data": {"id": job_id}}, ensure_ascii=False))
                return
            vals.append(job_id)
            cur.execute(f"UPDATE cron_jobs SET {', '.join(sets)} WHERE id = %s {own_sql}", vals + list(own_params))
            if cur.rowcount == 0:
                print(json.dumps({"success": False, "error": "Cron job not found"}, ensure_ascii=False))
                sys.exit(1)
        conn.commit()
    except SystemExit:
        raise
    except Exception:
        path = _cron_path(workspace)
        with file_lock(path):
            jobs = load_json(path, [])
            found = False
            for j in jobs:
                if j.get("id") == job_id:
                    if schedule:
                        j["schedule"] = schedule
                    if prompt:
                        j["prompt"] = prompt
                    found = True
            if not found:
                print(json.dumps({"success": False, "error": "Cron job not found"}, ensure_ascii=False))
                sys.exit(1)
            atomic_write_json(path, jobs)
    finally:
        if conn:
            conn.close()
    print(json.dumps({"success": True, "data": {"id": job_id}}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage cron jobs")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")

    add_p = sub.add_parser("add")
    add_p.add_argument("--schedule", required=True)
    add_p.add_argument("--prompt", required=True)
    add_p.add_argument("--type", default="cron", choices=["cron", "heartbeat"])

    rm_p = sub.add_parser("remove")
    rm_p.add_argument("--id", required=True)

    en_p = sub.add_parser("enable")
    en_p.add_argument("--id", required=True)

    dis_p = sub.add_parser("disable")
    dis_p.add_argument("--id", required=True)

    up_p = sub.add_parser("update")
    up_p.add_argument("--id", required=True)
    up_p.add_argument("--schedule")
    up_p.add_argument("--prompt")

    args = parser.parse_args()
    workspace = resolve_workspace()

    try:
        if args.cmd == "list":
            list_jobs(workspace)
        elif args.cmd == "add":
            add_job(workspace, args.schedule, args.prompt, getattr(args, "type", "cron"))
        elif args.cmd == "remove":
            remove_job(workspace, args.id)
        elif args.cmd == "enable":
            enable_job(workspace, args.id, True)
        elif args.cmd == "disable":
            enable_job(workspace, args.id, False)
        elif args.cmd == "update":
            update_job(workspace, args.id, args.schedule, args.prompt)
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
