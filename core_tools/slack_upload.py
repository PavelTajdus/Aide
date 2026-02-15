"""Upload a file to Slack channel/thread.

Uses SLACK_BOT_TOKEN from .env and AIDE_SLACK_CHANNEL_ID / AIDE_SLACK_THREAD_TS
from environment (set by slack_bot.py before agent launch).
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import load_workspace_env, resolve_workspace


def upload_file(
    file_path: str,
    channel_id: str | None = None,
    thread_ts: str | None = None,
    title: str | None = None,
    comment: str | None = None,
) -> dict:
    workspace = resolve_workspace()
    load_workspace_env(workspace)

    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError

    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("Missing SLACK_BOT_TOKEN in .env")

    channel_id = channel_id or os.environ.get("AIDE_SLACK_CHANNEL_ID")
    if not channel_id:
        raise RuntimeError("Missing channel_id (pass --channel or set AIDE_SLACK_CHANNEL_ID)")

    thread_ts = thread_ts or os.environ.get("AIDE_SLACK_THREAD_TS")

    path = Path(file_path)
    if not path.exists():
        raise RuntimeError(f"File not found: {file_path}")

    client = WebClient(token=token)

    try:
        resp = client.files_upload_v2(
            channel=channel_id,
            file=str(path),
            filename=path.name,
            title=title or path.name,
            initial_comment=comment or "",
            thread_ts=thread_ts,
        )
        file_info = resp.get("file", {})
        return {
            "file_id": file_info.get("id"),
            "filename": file_info.get("name"),
            "url": file_info.get("permalink"),
        }
    except SlackApiError as exc:
        raise RuntimeError(f"Slack upload failed: {exc}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload file to Slack")
    parser.add_argument("--file", required=True, help="Path to file to upload")
    parser.add_argument("--channel", default=None, help="Slack channel ID (default: from env)")
    parser.add_argument("--thread-ts", default=None, help="Thread timestamp (default: from env)")
    parser.add_argument("--title", default=None, help="File title")
    parser.add_argument("--comment", default=None, help="Initial comment with the file")
    args = parser.parse_args()

    result = upload_file(
        file_path=args.file,
        channel_id=args.channel,
        thread_ts=args.thread_ts,
        title=args.title,
        comment=args.comment,
    )
    print(json.dumps({"success": True, "data": result}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        sys.exit(1)
