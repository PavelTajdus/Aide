import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import atomic_write_json, file_lock, iso_now, load_json, resolve_workspace


def _projects_path(workspace):
    return workspace / "data" / "projects.json"


def _projects_dir(workspace):
    return workspace / "data" / "projects"


def _slugify(text: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-"
    out = []
    for ch in text.lower().replace(" ", "-"):
        if ch in allowed:
            out.append(ch)
        elif ch.isalnum():
            out.append(ch)
    slug = "".join(out).strip("-")
    return slug or "project"


def list_projects(workspace) -> None:
    items: List[Dict[str, Any]] = load_json(_projects_path(workspace), [])
    print(json.dumps({"success": True, "data": items}, ensure_ascii=False))


def add_project(workspace, name: str) -> None:
    path = _projects_path(workspace)
    with file_lock(path):
        items = load_json(path, [])
        base = _slugify(name)
        existing_ids = {i.get("id") for i in items}
        project_id = base
        if project_id in existing_ids:
            project_id = f"{base}-{str(uuid.uuid4())[:8]}"
        md_path = _projects_dir(workspace) / f"{project_id}.md"
        _projects_dir(workspace).mkdir(parents=True, exist_ok=True)
        if not md_path.exists():
            md_path.write_text(f"# {name}\n\n", encoding="utf-8")
        items.append(
            {
                "id": project_id,
                "name": name,
                "status": "active",
                "file": str(md_path),
                "created": iso_now(),
            }
        )
        atomic_write_json(path, items)
    print(json.dumps({"success": True, "data": {"id": project_id}}, ensure_ascii=False))


def update_project(workspace, project_id: str, name: str | None, status: str | None) -> None:
    path = _projects_path(workspace)
    with file_lock(path):
        items = load_json(path, [])
        found = False
        for item in items:
            if item.get("id") == project_id:
                if name:
                    item["name"] = name
                if status:
                    item["status"] = status
                found = True
        if not found:
            print(json.dumps({"success": False, "error": "Project not found"}, ensure_ascii=False))
            sys.exit(1)
        atomic_write_json(path, items)
    print(json.dumps({"success": True, "data": {"id": project_id}}, ensure_ascii=False))


def archive_project(workspace, project_id: str) -> None:
    update_project(workspace, project_id, None, "archived")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage projects")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")

    add_p = sub.add_parser("add")
    add_p.add_argument("--name", required=True)

    up_p = sub.add_parser("update")
    up_p.add_argument("--id", required=True)
    up_p.add_argument("--name")
    up_p.add_argument("--status")

    arch_p = sub.add_parser("archive")
    arch_p.add_argument("--id", required=True)

    args = parser.parse_args()
    workspace = resolve_workspace()

    try:
        if args.cmd == "list":
            list_projects(workspace)
        elif args.cmd == "add":
            add_project(workspace, args.name)
        elif args.cmd == "update":
            update_project(workspace, args.id, args.name, args.status)
        elif args.cmd == "archive":
            archive_project(workspace, args.id)
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
