import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional
from urllib import request

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _utils import read_workspace_env, resolve_workspace


def _make_env_getter(ws_env: Dict[str, str]):
    """Return a thread-safe env lookup that checks os.environ then workspace .env."""
    def _env(key: str, default: str | None = None) -> str | None:
        return os.environ.get(key) or ws_env.get(key) or default
    return _env


def _send_telegram(text: str, chat_id: str | None, env) -> None:
    token = env("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("Missing TELEGRAM_TOKEN")

    chat_id = chat_id or env("AIDE_DEFAULT_CHAT_ID")
    if not chat_id:
        raise RuntimeError("Missing chat_id (AIDE_DEFAULT_CHAT_ID)")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")

    req = request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Telegram API error: {resp.status}")


def _slack_default_target(chat_id: str | None, env) -> str:
    if chat_id:
        return chat_id
    target = env("AIDE_SLACK_DEFAULT_TARGET")
    if target:
        return target
    channel = env("AIDE_SLACK_DEFAULT_CHANNEL_ID")
    if channel:
        return channel
    user = env("AIDE_SLACK_DEFAULT_USER_ID")
    if user:
        return user
    raise RuntimeError("Missing Slack target (AIDE_SLACK_DEFAULT_TARGET or AIDE_SLACK_DEFAULT_CHANNEL_ID/USER_ID)")


def _send_slack(text: str, chat_id: str | None, env) -> None:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError

    token = env("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("Missing SLACK_BOT_TOKEN")

    target = _slack_default_target(chat_id, env)
    target_type = (env("AIDE_SLACK_DEFAULT_TARGET_TYPE", "auto") or "auto").strip().lower()

    def _is_user_id(value: str) -> bool:
        return value.startswith("U") or value.startswith("W")

    def _is_channel_id(value: str) -> bool:
        return value.startswith("C") or value.startswith("G") or value.startswith("D")

    client = WebClient(token=token)

    if target_type == "channel":
        channel_id = target
    elif target_type == "dm":
        if _is_channel_id(target) and target.startswith("D"):
            channel_id = target
        else:
            try:
                resp = client.conversations_open(users=target)
                channel_id = resp["channel"]["id"]
            except SlackApiError as exc:
                raise RuntimeError(f"Slack DM open failed: {exc}") from exc
    else:
        if _is_channel_id(target):
            channel_id = target
        elif _is_user_id(target):
            try:
                resp = client.conversations_open(users=target)
                channel_id = resp["channel"]["id"]
            except SlackApiError as exc:
                raise RuntimeError(f"Slack DM open failed: {exc}") from exc
        else:
            raise RuntimeError("Slack target must be channel ID or user ID")

    try:
        client.chat_postMessage(channel=channel_id, text=text)
    except SlackApiError as exc:
        raise RuntimeError(f"Slack API error: {exc}") from exc


def send_message(text: str, chat_id: str | None = None, provider: str | None = None) -> None:
    workspace = resolve_workspace()
    # Thread-safe: read .env as dict without mutating os.environ
    ws_env = read_workspace_env(workspace)
    env = _make_env_getter(ws_env)

    provider = (provider or env("AIDE_NOTIFY_PROVIDER") or "telegram").strip().lower()
    if provider in ("none", "off", "disabled"):
        return
    if provider in ("telegram", "tg"):
        _send_telegram(text, chat_id, env)
        return
    if provider in ("slack",):
        _send_slack(text, chat_id, env)
        return
    raise RuntimeError(f"Unknown notify provider: {provider}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send message (Telegram/Slack)")
    parser.add_argument("--text", required=True)
    parser.add_argument("--chat-id", default=None)
    parser.add_argument("--provider", default=None)
    args = parser.parse_args()

    send_message(args.text, args.chat_id, args.provider)
    print(json.dumps({"success": True}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        sys.exit(1)
