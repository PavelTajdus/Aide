import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import atomic_write_json, file_lock, iso_now, load_json, resolve_workspace


def _memory_path(workspace):
    return workspace / "data" / "memory.json"


def list_mem(workspace) -> None:
    items: List[Dict[str, Any]] = load_json(_memory_path(workspace), [])
    print(json.dumps({"success": True, "data": items}, ensure_ascii=False))


def add_mem(workspace, text: str) -> None:
    path = _memory_path(workspace)
    with file_lock(path):
        items = load_json(path, [])
        mem_id = str(uuid.uuid4())
        items.append({"id": mem_id, "text": text, "created": iso_now()})
        atomic_write_json(path, items)
    print(json.dumps({"success": True, "data": {"id": mem_id}}, ensure_ascii=False))


def search_mem(workspace, query: str) -> None:
    items = load_json(_memory_path(workspace), [])
    q = query.lower()
    results = [i for i in items if q in str(i.get("text", "")).lower()]
    print(json.dumps({"success": True, "data": results}, ensure_ascii=False))


def forget_mem(workspace, mem_id: str) -> None:
    path = _memory_path(workspace)
    with file_lock(path):
        items = load_json(path, [])
        new_items = [i for i in items if i.get("id") != mem_id]
        if len(new_items) == len(items):
            print(json.dumps({"success": False, "error": "Memory item not found"}, ensure_ascii=False))
            sys.exit(1)
        atomic_write_json(path, new_items)
    print(json.dumps({"success": True, "data": {"id": mem_id}}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage memory items")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")

    add_p = sub.add_parser("add")
    add_p.add_argument("--text", required=True)

    search_p = sub.add_parser("search")
    search_p.add_argument("--query", required=True)

    forget_p = sub.add_parser("forget")
    forget_p.add_argument("--id", required=True)

    args = parser.parse_args()
    workspace = resolve_workspace()

    try:
        if args.cmd == "list":
            list_mem(workspace)
        elif args.cmd == "add":
            add_mem(workspace, args.text)
        elif args.cmd == "search":
            search_mem(workspace, args.query)
        elif args.cmd == "forget":
            forget_mem(workspace, args.id)
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
