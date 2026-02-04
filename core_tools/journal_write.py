import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import resolve_workspace


def main() -> None:
    parser = argparse.ArgumentParser(description="Append to journal")
    parser.add_argument("--text", required=True)
    args = parser.parse_args()

    workspace = resolve_workspace()
    from datetime import datetime

    date_str = datetime.now().date().isoformat()
    journal_dir = workspace / "data" / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    journal_path = journal_dir / f"{date_str}.md"

    timestamp = datetime.now().isoformat()
    entry = f"\n\n## {timestamp}\n\n{args.text}\n"
    with journal_path.open("a", encoding="utf-8") as f:
        f.write(entry)

    print(json.dumps({"success": True, "data": {"path": str(journal_path)}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        sys.exit(1)
