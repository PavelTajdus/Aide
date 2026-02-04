import argparse
import json
import os
import sys
from pathlib import Path
from urllib import request

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import load_workspace_env, resolve_workspace


def send_message(text: str, chat_id: str | None = None) -> None:
    workspace = resolve_workspace()
    load_workspace_env(workspace)

    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("Missing TELEGRAM_TOKEN")

    chat_id = chat_id or os.environ.get("AIDE_DEFAULT_CHAT_ID")
    if not chat_id:
        raise RuntimeError("Missing chat_id (AIDE_DEFAULT_CHAT_ID)")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")

    req = request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Telegram API error: {resp.status}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send Telegram message")
    parser.add_argument("--text", required=True)
    parser.add_argument("--chat-id", default=None)
    args = parser.parse_args()

    send_message(args.text, args.chat_id)
    print(json.dumps({"success": True}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        sys.exit(1)
