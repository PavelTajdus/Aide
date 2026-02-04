import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import atomic_write_json, file_lock, iso_now, load_json, resolve_workspace


def _cron_path(workspace):
    return workspace / "data" / "cron.json"


def list_jobs(workspace) -> None:
    jobs: List[Dict[str, Any]] = load_json(_cron_path(workspace), [])
    print(json.dumps({"success": True, "data": jobs}, ensure_ascii=False))


def add_job(workspace, schedule: str, prompt: str) -> None:
    path = _cron_path(workspace)
    with file_lock(path):
        jobs: List[Dict[str, Any]] = load_json(path, [])
        job_id = str(uuid.uuid4())
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

    print(json.dumps({"success": True, "data": {"id": job_id}}, ensure_ascii=False))


def remove_job(workspace, job_id: str) -> None:
    path = _cron_path(workspace)
    with file_lock(path):
        jobs = load_json(path, [])
        new_jobs = [j for j in jobs if j.get("id") != job_id]
        if len(new_jobs) == len(jobs):
            print(json.dumps({"success": False, "error": "Cron job not found"}, ensure_ascii=False))
            sys.exit(1)
        atomic_write_json(path, new_jobs)
    print(json.dumps({"success": True, "data": {"id": job_id}}, ensure_ascii=False))


def enable_job(workspace, job_id: str, enabled: bool) -> None:
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
    print(json.dumps({"success": True, "data": {"id": job_id, "enabled": enabled}}, ensure_ascii=False))


def update_job(workspace, job_id: str, schedule: str | None, prompt: str | None) -> None:
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
    print(json.dumps({"success": True, "data": {"id": job_id}}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage cron jobs")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")

    add_p = sub.add_parser("add")
    add_p.add_argument("--schedule", required=True)
    add_p.add_argument("--prompt", required=True)

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
            add_job(workspace, args.schedule, args.prompt)
        elif args.cmd == "remove":
            remove_job(workspace, args.id)
        elif args.cmd == "enable":
            enable_job(workspace, args.id, True)
        elif args.cmd == "disable":
            enable_job(workspace, args.id, False)
        elif args.cmd == "update":
            update_job(workspace, args.id, args.schedule, args.prompt)
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
