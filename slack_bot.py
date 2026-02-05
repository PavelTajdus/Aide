import argparse
import os
import queue
import re
import shutil
import threading
import time
from urllib import request
from pathlib import Path
from typing import Any, Dict, Optional

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from agent import run_agent, get_session_usage
from config import load_workspace_env, resolve_workspace
from core_tools._utils import atomic_write_json, file_lock, load_json
from markdown_to_mrkdwn import SlackMarkdownConverter

_mrkdwn_converter = SlackMarkdownConverter()


def _tables_to_codeblocks(text: str) -> str:
    """Convert markdown tables to code blocks for Slack display."""
    lines = text.split("\n")
    result = []
    table_lines = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        # Detect table row (starts with | or is separator like |---|---|)
        is_table_line = stripped.startswith("|") and stripped.endswith("|")

        if is_table_line:
            if not in_table:
                in_table = True
            table_lines.append(line)
        else:
            if in_table:
                # End of table - wrap in code block
                result.append("```")
                result.extend(table_lines)
                result.append("```")
                table_lines = []
                in_table = False
            result.append(line)

    # Handle table at end of text
    if table_lines:
        result.append("```")
        result.extend(table_lines)
        result.append("```")

    return "\n".join(result)


RUNNING: Dict[str, Any] = {}


def _sessions_path(workspace: Path) -> Path:
    return workspace / "data" / "sessions_slack.json"


def _session_key(channel_id: str, thread_ts: Optional[str]) -> str:
    return f"{channel_id}:{thread_ts or 'root'}"


def _get_session_id(workspace: Path, channel_id: str, thread_ts: Optional[str]) -> Optional[str]:
    path = _sessions_path(workspace)
    key = _session_key(channel_id, thread_ts)
    with file_lock(path):
        data = load_json(path, {})
        return data.get(key)


def _set_session_id(
    workspace: Path, channel_id: str, thread_ts: Optional[str], session_id: Optional[str]
) -> None:
    path = _sessions_path(workspace)
    key = _session_key(channel_id, thread_ts)
    with file_lock(path):
        data = load_json(path, {})
        if session_id:
            data[key] = session_id
        else:
            data.pop(key, None)
        atomic_write_json(path, data)


def _get_allowed_users() -> list[str]:
    raw = os.environ.get("AIDE_SLACK_ALLOWED_USERS", "")
    if not raw.strip():
        return []
    parts = [p.strip() for p in raw.replace(";", ",").split(",")]
    return [p for p in parts if p]


def _is_allowed(user_id: Optional[str], allowed: list[str]) -> bool:
    if user_id is None:
        return False
    if not allowed:
        return False
    return user_id in allowed


def _strip_mention(text: str, bot_user_id: Optional[str]) -> str:
    if not text:
        return ""
    if bot_user_id:
        text = re.sub(rf"<@{re.escape(bot_user_id)}>", "", text)
    return text.strip()


def _split_text(text: str, limit: int = 3500) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        chunks.append(text[start:end])
        start = end
    return chunks


def _progress_enabled() -> bool:
    raw = os.environ.get("AIDE_SLACK_PROGRESS", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _max_file_bytes() -> tuple[int, float]:
    raw = os.environ.get("AIDE_SLACK_MAX_FILE_MB", "10").strip().lower()
    try:
        mb = float(raw)
    except ValueError:
        mb = 10.0
    if mb <= 0:
        mb = 10.0
    return int(mb * 1024 * 1024), mb


def _build_prompt(text: Optional[str], attachment_paths: list[str]) -> str:
    base = text.strip() if text else ""
    if attachment_paths:
        attachments = "\n".join(f"- {p}" for p in attachment_paths)
        if base:
            return f"{base}\n\nPřílohy:\n{attachments}"
        return f"Přišla příloha:\n{attachments}"
    return base


def _fetch_thread_history(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    bot_user_id: Optional[str],
    limit: int = 20,
) -> list[Dict[str, str]]:
    """Fetch thread history from Slack API. Returns list of {role, content} dicts."""
    try:
        result = client.conversations_replies(
            channel=channel_id,
            ts=thread_ts,
            limit=limit,
        )
        messages = result.get("messages", [])
    except SlackApiError as e:
        print(f"[WARN] Failed to fetch thread history: {e.response.get('error', str(e))}")
        return []

    history = []
    for msg in messages:
        # Skip subtypes like join, leave, etc.
        if msg.get("subtype"):
            continue
        text = msg.get("text", "").strip()
        if not text:
            continue
        user = msg.get("user")
        bot_id = msg.get("bot_id")

        # Determine role
        if bot_id or (bot_user_id and user == bot_user_id):
            role = "assistant"
        else:
            role = "user"
            # Strip bot mention from user messages
            if bot_user_id:
                text = re.sub(rf"<@{re.escape(bot_user_id)}>", "", text).strip()

        if text:
            history.append({"role": role, "content": text})

    return history


def _format_thread_context(history: list[Dict[str, str]]) -> str:
    """Format thread history as context for Claude."""
    if not history:
        return ""

    lines = ["Předchozí konverzace ve vlákně:"]
    lines.append("---")
    for msg in history:
        role_label = "Uživatel" if msg["role"] == "user" else "Aide"
        # Truncate very long messages
        content = msg["content"]
        if len(content) > 500:
            content = content[:500] + "..."
        lines.append(f"{role_label}: {content}")
    lines.append("---")
    lines.append("")

    return "\n".join(lines)


def _truncate(text: str, max_len: int = 60) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _progress_text(tool_name: str, tool_input: Optional[Dict[str, Any]] = None) -> str:
    name = tool_name.lower()
    inp = tool_input or {}

    # WebFetch - show URL
    if name == "webfetch":
        url = inp.get("url", "")
        if url:
            # Strip protocol for brevity
            url = re.sub(r"^https?://", "", url)
            return f"WebFetch: {_truncate(url)}"
        return "WebFetch…"

    # WebSearch - show query
    if name == "websearch":
        query = inp.get("query", "")
        if query:
            return f"WebSearch: {_truncate(query)}"
        return "WebSearch…"

    # Read - show file path
    if name == "read":
        path = inp.get("file_path", "")
        if path:
            # Show just filename or last part of path
            short = Path(path).name if "/" in path else path
            return f"Read: {_truncate(short, 50)}"
        return "Read…"

    # Write - show file path
    if name == "write":
        path = inp.get("file_path", "")
        if path:
            short = Path(path).name if "/" in path else path
            return f"Write: {_truncate(short, 50)}"
        return "Write…"

    # Edit - show file path
    if name == "edit":
        path = inp.get("file_path", "")
        if path:
            short = Path(path).name if "/" in path else path
            return f"Edit: {_truncate(short, 50)}"
        return "Edit…"

    # Bash - show command
    if name == "bash":
        cmd = inp.get("command", "")
        if cmd:
            return f"Bash: {_truncate(cmd)}"
        return "Bash…"

    # Grep - show pattern
    if name == "grep":
        pattern = inp.get("pattern", "")
        if pattern:
            return f"Grep: {_truncate(pattern)}"
        return "Grep…"

    # Glob - show pattern
    if name == "glob":
        pattern = inp.get("pattern", "")
        if pattern:
            return f"Glob: {_truncate(pattern)}"
        return "Glob…"

    # Task - show description
    if name == "task":
        desc = inp.get("description", "")
        if desc:
            return f"Task: {_truncate(desc)}"
        return "Task…"

    # Generic fallback
    return f"{tool_name}…"


def _download_file(
    file_info: Dict[str, Any],
    inbox: Path,
    token: str,
) -> Optional[str]:
    url = file_info.get("url_private_download") or file_info.get("url_private")
    if not url:
        return None

    name = file_info.get("name") or file_info.get("title") or "file"
    ext = Path(name).suffix
    file_id = file_info.get("id") or str(int(time.time()))
    filename = f"{int(time.time())}_{file_id}{ext}"
    target = inbox / filename

    req = request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            return None
        with target.open("wb") as f:
            shutil.copyfileobj(resp, f)
    return str(target)


def _progress_worker(
    client: WebClient,
    channel_id: str,
    message_ts: str,
    q: queue.Queue,
) -> None:
    last_update = 0.0
    last_text: Optional[str] = None

    while True:
        item = q.get()
        if item is None:
            break

        pending = item
        # Drain queue for latest message
        while True:
            try:
                nxt = q.get_nowait()
                if nxt is None:
                    pending = None
                    break
                pending = nxt
            except queue.Empty:
                break

        if pending is None:
            break
        if pending == last_text:
            continue

        now = time.time()
        wait = max(0.0, 1.0 - (now - last_update))
        if wait:
            time.sleep(wait)

        try:
            client.chat_update(channel=channel_id, ts=message_ts, text=pending)
            last_text = pending
            last_update = time.time()
        except SlackApiError:
            continue


def _handle_command(text: str) -> Optional[str]:
    cmd = text.strip().lower()
    if cmd in ("new", "nova", "nová", "reset"):
        return "new"
    if cmd in ("stop", "zastav"):
        return "stop"
    return None


def _post_message(
    client: WebClient,
    channel_id: str,
    text: str,
    thread_ts: Optional[str] = None,
) -> Optional[str]:
    try:
        if thread_ts:
            resp = client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=text)
        else:
            resp = client.chat_postMessage(channel=channel_id, text=text)
        return resp.get("ts")
    except SlackApiError:
        return None


def _update_message(client: WebClient, channel_id: str, message_ts: str, text: str) -> None:
    try:
        client.chat_update(channel=channel_id, ts=message_ts, text=text)
    except SlackApiError:
        return


def _process_message(
    client: WebClient,
    workspace: Path,
    channel_id: str,
    thread_root: Optional[str],
    text: str,
    files: list[Dict[str, Any]],
    bot_user_id: Optional[str] = None,
) -> None:
    cmd = _handle_command(text)
    if cmd == "new":
        _set_session_id(workspace, channel_id, thread_root, None)
        _post_message(client, channel_id, "Nová session vytvořena.", thread_root)
        return
    if cmd == "stop":
        key = _session_key(channel_id, thread_root)
        proc = RUNNING.get(key)
        if not proc:
            _post_message(client, channel_id, "Neběží žádná session.", thread_root)
            return
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
        RUNNING.pop(key, None)
        _post_message(client, channel_id, "Session zastavena.", thread_root)
        return

    attachment_paths: list[str] = []
    oversize = False
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    inbox = workspace / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    max_bytes, max_mb = _max_file_bytes()

    for f in files or []:
        if f.get("mode") in ("tombstone", "hidden"):
            continue
        size = f.get("size")
        if isinstance(size, int) and size > max_bytes:
            oversize = True
            continue
        try:
            path = _download_file(f, inbox, token)
            if path:
                attachment_paths.append(path)
        except Exception:
            continue

    prompt = _build_prompt(text, attachment_paths)
    if oversize:
        warning = f"Příloha je příliš velká (max {int(max_mb)} MB) a nebyla stažena."
        if not prompt:
            _post_message(client, channel_id, warning, thread_root)
            return
        _post_message(client, channel_id, warning, thread_root)
    if not prompt:
        _post_message(client, channel_id, "Nepřišel text ani příloha.", thread_root)
        return

    # Fetch thread history for context (exclude the last message which is current prompt)
    if thread_root:
        history = _fetch_thread_history(client, channel_id, thread_root, bot_user_id, limit=20)
        # Remove last message if it matches current prompt (avoid duplication)
        if history and history[-1]["role"] == "user":
            history = history[:-1]
        thread_context = _format_thread_context(history)
        if thread_context:
            prompt = f"{thread_context}\nAktuální zpráva:\n{prompt}"

    thinking_ts = _post_message(client, channel_id, "Přemýšlím...", thread_root)
    if not thinking_ts:
        return

    session_id = _get_session_id(workspace, channel_id, thread_root)

    key = _session_key(channel_id, thread_root)

    def _process_cb(proc):
        RUNNING[key] = proc

    progress_q: Optional[queue.Queue] = None
    progress_thread: Optional[threading.Thread] = None

    if _progress_enabled():
        progress_q = queue.Queue()
        progress_thread = threading.Thread(
            target=_progress_worker,
            args=(client, channel_id, thinking_ts, progress_q),
            daemon=True,
        )
        progress_thread.start()

        def _tool_cb(name: str, inp: Dict[str, Any]) -> None:
            if not progress_q:
                return
            progress_q.put(_progress_text(name, inp))
    else:

        def _tool_cb(name: str, inp: Dict[str, Any]) -> None:
            return

    try:
        answer, new_session_id, _tool_log = run_agent(
            prompt,
            session_id=session_id,
            working_dir=workspace,
            process_cb=_process_cb,
            tool_cb=_tool_cb,
        )
    except Exception as exc:
        RUNNING.pop(key, None)
        _update_message(client, channel_id, thinking_ts, f"Chyba: {exc}")
        if progress_q:
            progress_q.put(None)
        if progress_thread:
            progress_thread.join(timeout=2)
        return

    if progress_q:
        progress_q.put(None)
    if progress_thread:
        progress_thread.join(timeout=2)

    RUNNING.pop(key, None)

    if new_session_id:
        _set_session_id(workspace, channel_id, thread_root, new_session_id)

    # Convert tables to code blocks, then Markdown to Slack mrkdwn
    answer = _tables_to_codeblocks(answer)
    answer = _mrkdwn_converter.convert(answer)

    chunks = _split_text(answer)
    _update_message(client, channel_id, thinking_ts, chunks[0])

    for chunk in chunks[1:]:
        _post_message(client, channel_id, chunk, thread_root)


def _handle_event(
    client: WebClient,
    workspace: Path,
    allowed: list[str],
    bot_user_id: Optional[str],
    channel_id: str,
    thread_root: Optional[str],
    user_id: Optional[str],
    text: str,
    files: list[Dict[str, Any]],
) -> None:
    if not _is_allowed(user_id, allowed):
        return

    cleaned = _strip_mention(text, bot_user_id)

    thread = threading.Thread(
        target=_process_message,
        args=(client, workspace, channel_id, thread_root, cleaned, files, bot_user_id),
        daemon=True,
    )
    thread.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Aide Slack bot")
    parser.add_argument("--workspace", default=None)
    args = parser.parse_args()

    workspace = resolve_workspace(args.workspace)
    load_workspace_env(workspace)

    slack_enabled = os.environ.get("AIDE_SLACK_ENABLED", "1").strip().lower()
    if slack_enabled in ("0", "false", "no", "off"):
        return

    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    app_token = os.environ.get("SLACK_APP_TOKEN")
    if not bot_token or not app_token:
        raise RuntimeError("Missing SLACK_BOT_TOKEN or SLACK_APP_TOKEN in workspace .env")

    allowed = _get_allowed_users()

    app = App(token=bot_token)
    client = app.client

    try:
        auth = client.auth_test()
        bot_user_id = auth.get("user_id")
    except SlackApiError:
        bot_user_id = None

    @app.event("app_mention")
    def handle_mention(body, event, logger):
        channel_id = event.get("channel")
        if not channel_id:
            return
        thread_root = event.get("thread_ts") or event.get("ts")
        _handle_event(
            client,
            workspace,
            allowed,
            bot_user_id,
            channel_id,
            thread_root,
            event.get("user"),
            event.get("text", ""),
            event.get("files", []) or [],
        )

    @app.event("message")
    def handle_message(body, event, logger):
        if event.get("subtype"):
            return
        if event.get("bot_id"):
            return
        if event.get("channel_type") != "im":
            return
        channel_id = event.get("channel")
        if not channel_id:
            return
        thread_root = event.get("thread_ts")
        _handle_event(
            client,
            workspace,
            allowed,
            bot_user_id,
            channel_id,
            thread_root,
            event.get("user"),
            event.get("text", ""),
            event.get("files", []) or [],
        )

    @app.command("/new")
    def handle_new_command(ack, body, logger):
        ack()
        user_id = body.get("user_id")
        channel_id = body.get("channel_id")
        if not _is_allowed(user_id, allowed):
            return
        # Clear all sessions for this channel
        path = _sessions_path(workspace)
        with file_lock(path):
            data = load_json(path, {})
            to_remove = [k for k in data if k.startswith(f"{channel_id}:")]
            for k in to_remove:
                data.pop(k, None)
            atomic_write_json(path, data)
        _post_message(client, channel_id, "🔄 Session resetována. Začínáme čistý.")

    @app.command("/stop")
    def handle_stop_command(ack, body, logger):
        ack()
        user_id = body.get("user_id")
        channel_id = body.get("channel_id")
        if not _is_allowed(user_id, allowed):
            return
        # Kill any running agent process for this channel
        stopped = False
        for key, proc in list(RUNNING.items()):
            if key.startswith(f"{channel_id}:") and proc.poll() is None:
                proc.terminate()
                RUNNING.pop(key, None)
                stopped = True
        if stopped:
            _post_message(client, channel_id, "Agent zastaven.")
        else:
            _post_message(client, channel_id, "Žádný agent neběží.")

    @app.command("/session")
    def handle_session_command(ack, body, logger):
        ack()
        user_id = body.get("user_id")
        channel_id = body.get("channel_id")
        if not _is_allowed(user_id, allowed):
            return

        # Get session for this channel (root session)
        session_id = _get_session_id(workspace, channel_id, None)
        if not session_id:
            _post_message(client, channel_id, "Žádná aktivní session.")
            return

        _post_message(client, channel_id, "Zjišťuji stav session...")

        usage_info = get_session_usage(session_id, working_dir=workspace)
        if not usage_info:
            _post_message(client, channel_id, f"Session: `{session_id[:8]}...`\nNepodařilo se získat usage info.")
            return

        # Extract info
        model_usage = usage_info.get("model_usage", {})
        model_name = list(model_usage.keys())[0] if model_usage else "unknown"
        model_data = model_usage.get(model_name, {})

        context_window = model_data.get("contextWindow", 200000)
        input_tokens = model_data.get("inputTokens", 0)
        cache_read = model_data.get("cacheReadInputTokens", 0)
        cache_create = model_data.get("cacheCreationInputTokens", 0)
        output_tokens = model_data.get("outputTokens", 0)

        # Total context used is approximately cache_read (previous context) + new input
        total_context = cache_read + cache_create + input_tokens
        usage_percent = (total_context / context_window) * 100 if context_window else 0
        remaining = context_window - total_context

        cost = usage_info.get("cost_usd", 0)

        msg = (
            f"*Session:* `{session_id[:8]}...`\n"
            f"*Model:* {model_name}\n"
            f"*Kontext:* {total_context:,} / {context_window:,} tokenů ({usage_percent:.1f}%)\n"
            f"*Zbývá:* ~{remaining:,} tokenů\n"
            f"*Tento dotaz:* ${cost:.4f}"
        )
        _post_message(client, channel_id, msg)

    SocketModeHandler(app, app_token).start()


if __name__ == "__main__":
    main()
