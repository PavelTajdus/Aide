import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
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
from context import log_conversation

_mrkdwn_converter = SlackMarkdownConverter()
_ALLOWED_REASONING_EFFORTS = {"minimal", "low", "medium", "high", "xhigh"}


def _normalize_effort(value: str) -> Optional[str]:
    raw = (value or "").strip().lower().replace("_", " ").replace("-", " ")
    raw = " ".join(raw.split())
    if raw in _ALLOWED_REASONING_EFFORTS:
        return raw
    aliases = {
        "extra high": "xhigh",
        "extrahigh": "xhigh",
        "ultra high": "xhigh",
        "ultrahigh": "xhigh",
    }
    return aliases.get(raw)


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


def _normalize_escaped_markdown(text: str) -> str:
    """Normalize model-emitted escaped markdown before mrkdwn conversion."""
    if not text:
        return text
    # Common issue: assistant returns escaped code fences/inline-code markers like \`path\`
    return text.replace("\\`", "`")


RUNNING: Dict[str, Any] = {}
# Per-thread metadata: key -> {started_at: float, last_tool: str, last_tool_at: float, prompt_preview: str}
RUNNING_META: Dict[str, Dict[str, Any]] = {}
# Per-thread message queue: key -> deque of (text, files, bot_user_id) tuples
THREAD_QUEUES: Dict[str, list] = {}
# Lock for THREAD_QUEUES access
THREAD_QUEUES_LOCK = threading.Lock()


def _sessions_path(workspace: Path) -> Path:
    return workspace / "data" / "sessions_slack.json"


def _session_options_path(workspace: Path) -> Path:
    return workspace / "data" / "sessions_slack_options.json"


def _session_key(channel_id: str, thread_ts: Optional[str]) -> str:
    return f"{channel_id}:{thread_ts or 'root'}"


def _current_backend_name() -> str:
    return os.environ.get("AIDE_BACKEND", "claude-code").strip().lower()


def _get_session_id(workspace: Path, channel_id: str, thread_ts: Optional[str]) -> Optional[str]:
    """Return session ID only if it belongs to the currently active backend.

    Session entries can be a plain string (legacy) or a dict
    ``{"session_id": "...", "backend": "..."}``.  When the stored backend
    differs from the active one the entry is silently dropped so that a
    fresh session is created with the correct backend.
    """
    path = _sessions_path(workspace)
    key = _session_key(channel_id, thread_ts)
    current_backend = _current_backend_name()
    with file_lock(path):
        data = load_json(path, {})
        entry = data.get(key)
        if entry is None:
            return None
        # Legacy format: plain string
        if isinstance(entry, str):
            return entry
        # New format: dict with backend affinity
        if isinstance(entry, dict):
            stored_backend = entry.get("backend", "")
            if stored_backend and stored_backend != current_backend:
                # Backend mismatch – discard stale session
                data.pop(key, None)
                atomic_write_json(path, data)
                return None
            return entry.get("session_id")
        return None


def _set_session_id(
    workspace: Path, channel_id: str, thread_ts: Optional[str], session_id: Optional[str]
) -> None:
    path = _sessions_path(workspace)
    key = _session_key(channel_id, thread_ts)
    current_backend = _current_backend_name()
    with file_lock(path):
        data = load_json(path, {})
        if session_id:
            data[key] = {"session_id": session_id, "backend": current_backend}
        else:
            data.pop(key, None)
        atomic_write_json(path, data)


def _sanitize_session_options(raw: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}

    model = str(raw.get("codex_model", "")).strip()
    if model:
        out["codex_model"] = model

    profile = str(raw.get("codex_profile", "")).strip()
    if profile:
        out["codex_profile"] = profile

    effort = _normalize_effort(str(raw.get("codex_reasoning_effort", "")))
    if effort:
        out["codex_reasoning_effort"] = effort

    return out


def _get_session_options(
    workspace: Path, channel_id: str, thread_ts: Optional[str]
) -> Dict[str, str]:
    path = _session_options_path(workspace)
    key = _session_key(channel_id, thread_ts)
    with file_lock(path):
        data = load_json(path, {})
        raw = data.get(key, {})
        if not isinstance(raw, dict):
            return {}
        return _sanitize_session_options(raw)


def _set_session_options(
    workspace: Path,
    channel_id: str,
    thread_ts: Optional[str],
    options: Optional[Dict[str, str]],
) -> None:
    path = _session_options_path(workspace)
    key = _session_key(channel_id, thread_ts)
    with file_lock(path):
        data = load_json(path, {})
        clean = _sanitize_session_options(options or {})
        if clean:
            data[key] = clean
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


def _auto_thread_enabled() -> bool:
    raw = os.environ.get("AIDE_SLACK_AUTO_THREAD", "0").strip().lower()
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
            return f"{base}\n\nAttachments:\n{attachments}"
        return f"Attachment received:\n{attachments}"
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

    lines = ["Previous thread conversation:"]
    lines.append("---")
    for msg in history:
        role_label = "User" if msg["role"] == "user" else "Aide"
        # Truncate very long messages
        content = msg["content"]
        if len(content) > 500:
            content = content[:500] + "..."
        lines.append(f"{role_label}: {content}")
    lines.append("---")
    lines.append("")

    return "\n".join(lines)


def _truncate(text: str, max_len: int = 90) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _normalize_shell_command(cmd: str) -> str:
    """Extract inner command from common shell wrappers."""
    cmd = (cmd or "").strip()
    patterns = (
        r"^/bin/(?:ba)?sh\s+-lc\s+'(.+)'$",
        r'^/bin/(?:ba)?sh\s+-lc\s+"(.+)"$',
        r"^bash\s+-lc\s+'(.+)'$",
        r'^bash\s+-lc\s+"(.+)"$',
        r"^sh\s+-lc\s+'(.+)'$",
        r'^sh\s+-lc\s+"(.+)"$',
    )
    for pat in patterns:
        m = re.match(pat, cmd)
        if m:
            return m.group(1)
    return cmd


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
    if name in ("bash", "shell"):
        cmd = inp.get("command", "")
        if cmd:
            pretty = _normalize_shell_command(str(cmd))
            return f"Shell: {_truncate(pretty)}"
        return "Shell…"

    # Codex thinking
    if name == "thinking":
        text = str(inp.get("text", "")).strip()
        if text:
            return f"Thinking: {_truncate(text)}"
        return "Thinking…"

    # Assistant short status update
    if name in ("assistant_status", "status"):
        text = str(inp.get("text", "")).strip()
        if text:
            return _truncate(text, 140)
        return "Processing…"

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
    thread_ts: Optional[str],
    q: queue.Queue,
    ts_holder: Dict[str, Optional[str]],
) -> None:
    """Process tool-call progress updates.

    Creates a progress message lazily on first tool call (no notification
    until actual work starts). The message timestamp is stored in
    ts_holder["ts"] so the caller can delete it after completion.
    """
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
            msg_ts = ts_holder.get("ts")
            if msg_ts:
                client.chat_update(channel=channel_id, ts=msg_ts, text=pending)
            else:
                # Lazy create: first tool call creates the progress message
                kwargs: Dict[str, Any] = {"channel": channel_id, "text": pending}
                if thread_ts:
                    kwargs["thread_ts"] = thread_ts
                resp = client.chat_postMessage(**kwargs)
                ts_holder["ts"] = resp.get("ts")
            last_text = pending
            last_update = time.time()
        except SlackApiError:
            continue


def _handle_command(text: str) -> Optional[str]:
    cmd = text.strip().lower()
    if cmd in ("new", "reset"):
        return "new"
    if cmd in ("stop",):
        return "stop"
    if cmd in ("session", "status"):
        return "session"
    return None


def _handle_runtime_command(text: str) -> Optional[Dict[str, Any]]:
    parts = text.strip().split()
    if not parts:
        return None

    head = parts[0].lower()

    if head in ("model", "/model"):
        if len(parts) == 1 or parts[1].lower() in ("show", "status"):
            return {"action": "show"}
        if parts[1].lower() == "reset":
            return {"action": "reset"}

        opts: Dict[str, str] = {"codex_model": parts[1]}
        i = 2
        while i < len(parts):
            token = parts[i]
            lower = token.lower()

            if i + 1 < len(parts):
                two_word_effort = _normalize_effort(f"{parts[i]} {parts[i + 1]}")
                if two_word_effort:
                    opts["codex_reasoning_effort"] = two_word_effort
                    i += 2
                    continue

            one_effort = _normalize_effort(lower)
            if one_effort:
                opts["codex_reasoning_effort"] = one_effort
                i += 1
                continue

            if lower.startswith("effort="):
                effort = _normalize_effort(token.split("=", 1)[1].strip())
                if effort:
                    opts["codex_reasoning_effort"] = effort
                i += 1
                continue

            if lower.startswith("profile="):
                profile = token.split("=", 1)[1].strip()
                if profile:
                    opts["codex_profile"] = profile
                i += 1
                continue

            # Backward-compatible shorthand: next unknown token can be profile name.
            if "codex_profile" not in opts and token.strip():
                opts["codex_profile"] = token.strip()
            i += 1

        return {"action": "set", "options": opts}

    if head in ("effort", "reasoning", "/effort"):
        effort = _normalize_effort(" ".join(parts[1:])) if len(parts) > 1 else None
        if not effort:
            return {"action": "invalid_effort"}
        return {"action": "set", "options": {"codex_reasoning_effort": effort}}

    if head in ("profile", "/profile"):
        if len(parts) == 1:
            return {"action": "show"}
        if parts[1].lower() == "reset":
            return {"action": "clear_profile"}
        return {"action": "set", "options": {"codex_profile": parts[1].strip()}}

    return None


def _resolve_runtime_settings(
    workspace: Path, channel_id: str, thread_root: Optional[str]
) -> tuple[str, str, str]:
    runtime_opts = _get_session_options(workspace, channel_id, thread_root)
    model = runtime_opts.get("codex_model") or os.environ.get("AIDE_CODEX_MODEL", "(default)")
    effort = runtime_opts.get("codex_reasoning_effort") or os.environ.get(
        "AIDE_CODEX_REASONING_EFFORT", "(default)"
    )
    profile = runtime_opts.get("codex_profile") or os.environ.get("AIDE_CODEX_PROFILE", "(default)")
    return model, effort, profile


def _slash_thread_root(body: Dict[str, Any]) -> Optional[str]:
    # Slash command in thread should contain thread_ts; otherwise it's channel root.
    raw = body.get("thread_ts")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _execute_runtime_command(
    client: WebClient,
    workspace: Path,
    channel_id: str,
    thread_root: Optional[str],
    runtime_cmd: Dict[str, Any],
    thread_ts: Optional[str] = None,
) -> None:
    action = runtime_cmd.get("action")
    current = _get_session_options(workspace, channel_id, thread_root)

    if action == "invalid_effort":
        _post_message(client, channel_id, "Použij `effort minimal|low|medium|high|xhigh`.", thread_ts)
        return

    if action == "show":
        model, effort, profile = _resolve_runtime_settings(workspace, channel_id, thread_root)
        _post_message(
            client,
            channel_id,
            (
                f"*Codex runtime nastavení*\n"
                f"*Model:* {model}\n"
                f"*Effort:* {effort}\n"
                f"*Profile:* {profile}\n"
                f"`model <id> [minimal|low|medium|high|xhigh] [profile=<name>]`"
            ),
            thread_ts,
        )
        return

    if action == "reset":
        _set_session_options(workspace, channel_id, thread_root, None)
        _post_message(client, channel_id, "Runtime override smazán, používá se `.env`.", thread_ts)
        return

    if action == "clear_profile":
        current.pop("codex_profile", None)
        _set_session_options(workspace, channel_id, thread_root, current)
        _post_message(client, channel_id, "Runtime profile odstraněn.", thread_ts)
        return

    if action == "set":
        opts = runtime_cmd.get("options", {})
        if isinstance(opts, dict):
            merged = dict(current)
            merged.update(opts)
            _set_session_options(workspace, channel_id, thread_root, merged)
            model, effort, profile = _resolve_runtime_settings(workspace, channel_id, thread_root)
            _post_message(
                client,
                channel_id,
                f"Nastaveno: model `{model}`, effort `{effort}`, profile `{profile}`.",
                thread_ts,
            )
        return


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


def _delete_message(client: WebClient, channel_id: str, message_ts: str) -> None:
    try:
        client.chat_delete(channel=channel_id, ts=message_ts)
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
    event_ts: Optional[str] = None,
) -> None:
    key = _session_key(channel_id, thread_root)
    cmd = _handle_command(text)
    runtime_cmd = _handle_runtime_command(text)
    if cmd == "new":
        _set_session_id(workspace, channel_id, thread_root, None)
        _set_session_options(workspace, channel_id, thread_root, None)
        RUNNING.pop(key, None)
        RUNNING_META.pop(key, None)
        _post_message(client, channel_id, "New session created.", thread_root)
        _process_next_in_queue(client, workspace, channel_id, thread_root, key)
        return
    if cmd == "stop":
        proc = RUNNING.get(key)
        if not proc:
            RUNNING.pop(key, None)
            RUNNING_META.pop(key, None)
            _post_message(client, channel_id, "No session running.", thread_root)
            return
        # Clear queued messages too
        with THREAD_QUEUES_LOCK:
            THREAD_QUEUES.pop(key, None)
        if hasattr(proc, "terminate"):
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
        RUNNING.pop(key, None)
        RUNNING_META.pop(key, None)
        _post_message(client, channel_id, "Session stopped.", thread_root)
        return
    if cmd == "session":
        session_id = _get_session_id(workspace, channel_id, thread_root)
        if not session_id:
            _post_message(client, channel_id, "No active session.", thread_root)
            return
        _post_message(client, channel_id, "Checking status...", thread_root)
        usage_info = get_session_usage(session_id, working_dir=workspace)
        if not usage_info:
            _post_message(client, channel_id, f"Session: `{session_id[:8]}...` - cannot get info", thread_root)
            return
        model_usage = usage_info.get("model_usage", {})
        model_name = list(model_usage.keys())[0] if model_usage else "unknown"
        model_data = model_usage.get(model_name, {})
        context_window = model_data.get("contextWindow", 200000)
        cache_read = model_data.get("cacheReadInputTokens", 0)
        cache_create = model_data.get("cacheCreationInputTokens", 0)
        input_tokens = model_data.get("inputTokens", 0)
        total_context = cache_read + cache_create + input_tokens
        usage_percent = (total_context / context_window) * 100 if context_window else 0
        remaining = context_window - total_context
        msg = (
            f"*Session:* `{session_id[:8]}...`\n"
            f"*Model:* {model_name}\n"
            f"*Context:* {total_context:,} / {context_window:,} ({usage_percent:.1f}%)\n"
            f"*Remaining:* ~{remaining:,} tokens"
        )
        runtime_model, runtime_effort, runtime_profile = _resolve_runtime_settings(
            workspace, channel_id, thread_root
        )
        msg += (
            f"\n*Runtime model:* {runtime_model}"
            f"\n*Runtime effort:* {runtime_effort}"
            f"\n*Runtime profile:* {runtime_profile}"
        )
        _post_message(client, channel_id, msg, thread_root)
        return
    if runtime_cmd:
        _execute_runtime_command(client, workspace, channel_id, thread_root, runtime_cmd, thread_root)
        _process_next_in_queue(client, workspace, channel_id, thread_root, key)
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
        warning = f"Attachment too large (max {int(max_mb)} MB), not downloaded."
        if not prompt:
            _post_message(client, channel_id, warning, thread_root)
            RUNNING.pop(key, None)
            RUNNING_META.pop(key, None)
            _process_next_in_queue(client, workspace, channel_id, thread_root, key)
            return
        _post_message(client, channel_id, warning, thread_root)
    if not prompt:
        _post_message(client, channel_id, "No text or attachment received.", thread_root)
        RUNNING.pop(key, None)
        RUNNING_META.pop(key, None)
        _process_next_in_queue(client, workspace, channel_id, thread_root, key)
        return

    # Fetch thread history for context (exclude the last message which is current prompt)
    if thread_root:
        history = _fetch_thread_history(client, channel_id, thread_root, bot_user_id, limit=20)
        # Remove last message if it matches current prompt (avoid duplication)
        if history and history[-1]["role"] == "user":
            history = history[:-1]
        thread_context = _format_thread_context(history)
        if thread_context:
            prompt = f"{thread_context}\nCurrent message:\n{prompt}"

    key = _session_key(channel_id, thread_root)

    # Add reaction to indicate we're working (no notification)
    if event_ts:
        _add_reaction(client, channel_id, event_ts)

    session_id = _get_session_id(workspace, channel_id, thread_root)
    session_options = _get_session_options(workspace, channel_id, thread_root)

    def _process_cb(proc):
        RUNNING[key] = proc

    progress_q: Optional[queue.Queue] = None
    progress_thread: Optional[threading.Thread] = None
    # Shared dict so progress worker can store the lazily-created message ts
    progress_ts: Dict[str, Optional[str]] = {"ts": None}

    if _progress_enabled():
        progress_q = queue.Queue()
        progress_thread = threading.Thread(
            target=_progress_worker,
            args=(client, channel_id, thread_root, progress_q, progress_ts),
            daemon=True,
        )
        progress_thread.start()

        def _tool_cb(name: str, inp: Dict[str, Any]) -> None:
            meta = RUNNING_META.get(key)
            if meta:
                meta["last_tool"] = _progress_text(name, inp)
                meta["last_tool_at"] = time.time()
            if not progress_q:
                return
            progress_q.put(_progress_text(name, inp))
    else:

        def _tool_cb(name: str, inp: Dict[str, Any]) -> None:
            meta = RUNNING_META.get(key)
            if meta:
                meta["last_tool"] = _progress_text(name, inp)
                meta["last_tool_at"] = time.time()

    # Pass Slack context to agent subprocess via extra_env (thread-safe)
    agent_extra_env: Dict[str, str] = {"AIDE_SLACK_CHANNEL_ID": channel_id}
    if thread_root:
        agent_extra_env["AIDE_SLACK_THREAD_TS"] = thread_root

    try:
        answer, new_session_id, _tool_log = run_agent(
            prompt,
            session_id=session_id,
            working_dir=workspace,
            process_cb=_process_cb,
            tool_cb=_tool_cb,
            backend_options=session_options,
            extra_env=agent_extra_env,
        )
    except Exception as exc:
        RUNNING.pop(key, None)
        RUNNING_META.pop(key, None)
        if progress_q:
            progress_q.put(None)
        if progress_thread:
            progress_thread.join(timeout=2)
        if event_ts:
            _remove_reaction(client, channel_id, event_ts)
        if progress_ts["ts"]:
            _delete_message(client, channel_id, progress_ts["ts"])
        _post_message(client, channel_id, f"Error: {exc}", thread_root)
        # Still process queued messages after error
        _process_next_in_queue(client, workspace, channel_id, thread_root, key)
        return

    if progress_q:
        progress_q.put(None)
    if progress_thread:
        progress_thread.join(timeout=2)

    RUNNING.pop(key, None)
    RUNNING_META.pop(key, None)

    if new_session_id:
        _set_session_id(workspace, channel_id, thread_root, new_session_id)

    log_conversation(workspace, text, answer)

    # Convert tables to code blocks, then Markdown to Slack mrkdwn
    answer = _tables_to_codeblocks(answer)
    answer = _normalize_escaped_markdown(answer)
    answer = _mrkdwn_converter.convert(answer)

    chunks = _split_text(answer)
    # Remove reaction and progress, post final answer as new message
    # so Slack sends a notification for the completed response.
    if event_ts:
        _remove_reaction(client, channel_id, event_ts)
    if progress_ts["ts"]:
        _delete_message(client, channel_id, progress_ts["ts"])
    for chunk in chunks:
        _post_message(client, channel_id, chunk, thread_root)

    # Process next queued message if any
    _process_next_in_queue(client, workspace, channel_id, thread_root, key)


def _process_next_in_queue(
    client: WebClient,
    workspace: Path,
    channel_id: str,
    thread_root: Optional[str],
    key: str,
) -> None:
    """Check queue and process next queued messages if any. Merges all into one prompt."""
    with THREAD_QUEUES_LOCK:
        q = THREAD_QUEUES.get(key, [])
        if not q:
            return
        queued = list(q)
        q.clear()

    # Merge all queued messages into one prompt
    texts = [t for t, _f, _b, _e in queued if t]
    all_files = []
    bot_uid = None
    last_event_ts = None
    for _t, f, b, e in queued:
        all_files.extend(f)
        if b:
            bot_uid = b
        # Remove hourglass reactions from queued messages
        if e:
            _remove_reaction(client, channel_id, e, "hourglass_flowing_sand")
            last_event_ts = e
    merged_text = "\n\n".join(texts)

    # Process in current thread (already a daemon thread)
    _process_message(client, workspace, channel_id, thread_root, merged_text, all_files, bot_uid, last_event_ts)


def _add_reaction(client: WebClient, channel_id: str, timestamp: str, emoji: str = "eyes") -> None:
    try:
        client.reactions_add(channel=channel_id, timestamp=timestamp, name=emoji)
    except SlackApiError as e:
        print(f"[WARN] reactions_add failed: {e.response['error'] if e.response else e}")


def _remove_reaction(client: WebClient, channel_id: str, timestamp: str, emoji: str = "eyes") -> None:
    try:
        client.reactions_remove(channel=channel_id, timestamp=timestamp, name=emoji)
    except SlackApiError:
        pass


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
    event_ts: Optional[str] = None,
) -> None:
    if not _is_allowed(user_id, allowed):
        return

    cleaned = _strip_mention(text, bot_user_id)
    key = _session_key(channel_id, thread_root)

    # If a process is already running for this thread, queue the message
    with THREAD_QUEUES_LOCK:
        if key in RUNNING:
            THREAD_QUEUES.setdefault(key, []).append((cleaned, files, bot_user_id, event_ts))
            if event_ts:
                _add_reaction(client, channel_id, event_ts, "hourglass_flowing_sand")
            return
        # Reserve the slot immediately to prevent race conditions
        RUNNING[key] = True
        RUNNING_META[key] = {
            "started_at": time.time(),
            "last_tool": None,
            "last_tool_at": None,
            "prompt_preview": cleaned[:80] if cleaned else "",
        }

    thread = threading.Thread(
        target=_process_message,
        args=(client, workspace, channel_id, thread_root, cleaned, files, bot_user_id, event_ts),
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
            event_ts=event.get("ts"),
        )

    @app.event("message")
    def handle_message(body, event, logger):
        if event.get("subtype") and event.get("subtype") != "file_share":
            return
        if event.get("bot_id"):
            return
        channel_type = event.get("channel_type")
        channel_id = event.get("channel")
        if not channel_id:
            return

        if channel_type == "im":
            # DM – always respond
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
                event_ts=event.get("ts"),
            )
            return

        # Channel thread auto-reply (no mention needed)
        if _auto_thread_enabled() and channel_type in ("channel", "group"):
            thread_ts = event.get("thread_ts")
            if not thread_ts:
                return  # not a thread reply – ignore
            # Skip if message contains @mention – handle_mention already handles it
            if bot_user_id and f"<@{bot_user_id}>" in (event.get("text") or ""):
                return
            # Only respond if we already have a session for this thread
            if not _get_session_id(workspace, channel_id, thread_ts):
                return
            _handle_event(
                client,
                workspace,
                allowed,
                bot_user_id,
                channel_id,
                thread_ts,
                event.get("user"),
                event.get("text", ""),
                event.get("files", []) or [],
                event_ts=event.get("ts"),
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
        # Clear all runtime options for this channel too
        opts_path = _session_options_path(workspace)
        with file_lock(opts_path):
            opts = load_json(opts_path, {})
            to_remove = [k for k in opts if k.startswith(f"{channel_id}:")]
            for k in to_remove:
                opts.pop(k, None)
            atomic_write_json(opts_path, opts)
        _post_message(client, channel_id, "Session reset. Starting fresh.")

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
            if not key.startswith(f"{channel_id}:"):
                continue
            if hasattr(proc, "poll") and proc.poll() is None:
                proc.terminate()
            RUNNING.pop(key, None)
            RUNNING_META.pop(key, None)
            with THREAD_QUEUES_LOCK:
                THREAD_QUEUES.pop(key, None)
            stopped = True
        if stopped:
            _post_message(client, channel_id, "Agent stopped.")
        else:
            _post_message(client, channel_id, "No agent running.")

    @app.command("/session")
    def handle_session_command(ack, body, logger):
        ack()
        user_id = body.get("user_id")
        channel_id = body.get("channel_id")
        if not _is_allowed(user_id, allowed):
            return

        # Get ALL sessions for this channel (root + threads)
        path = _sessions_path(workspace)
        with file_lock(path):
            data = load_json(path, {})

        channel_sessions = {k: v for k, v in data.items() if k.startswith(f"{channel_id}:")}

        if not channel_sessions:
            _post_message(client, channel_id, "No active session in this channel.")
            return

        _post_message(client, channel_id, f"Checking {len(channel_sessions)} session(s)...")

        messages = []
        for key, session_id in channel_sessions.items():
            thread_ts = key.split(":", 1)[1] if ":" in key else "root"
            thread_label = "channel" if thread_ts == "root" else "thread"

            usage_info = get_session_usage(session_id, working_dir=workspace)
            if not usage_info:
                messages.append(f"*{thread_label}:* `{session_id[:8]}...` - cannot get info")
                continue

            model_usage = usage_info.get("model_usage", {})
            model_name = list(model_usage.keys())[0] if model_usage else "unknown"
            model_data = model_usage.get(model_name, {})

            context_window = model_data.get("contextWindow", 200000)
            cache_read = model_data.get("cacheReadInputTokens", 0)
            cache_create = model_data.get("cacheCreationInputTokens", 0)
            input_tokens = model_data.get("inputTokens", 0)

            total_context = cache_read + cache_create + input_tokens
            usage_percent = (total_context / context_window) * 100 if context_window else 0

            messages.append(
                f"*{thread_label}:* `{session_id[:8]}...`\n"
                f"  Context: {total_context:,} / {context_window:,} ({usage_percent:.1f}%)"
            )

        _post_message(client, channel_id, "\n\n".join(messages))

    @app.command("/model")
    def handle_model_command(ack, body, logger):
        ack()
        user_id = body.get("user_id")
        channel_id = body.get("channel_id")
        if not _is_allowed(user_id, allowed):
            return
        thread_root = _slash_thread_root(body)
        text = str(body.get("text", "")).strip()
        raw = f"model {text}".strip()
        runtime_cmd = _handle_runtime_command(raw)
        if not runtime_cmd:
            _post_message(
                client,
                channel_id,
                "Použití: `/model`, `/model reset`, `/model gpt-5.3-codex xhigh`",
                thread_root,
            )
            return
        _execute_runtime_command(client, workspace, channel_id, thread_root, runtime_cmd, thread_root)

    @app.command("/effort")
    def handle_effort_command(ack, body, logger):
        ack()
        user_id = body.get("user_id")
        channel_id = body.get("channel_id")
        if not _is_allowed(user_id, allowed):
            return
        thread_root = _slash_thread_root(body)
        text = str(body.get("text", "")).strip()
        raw = f"effort {text}".strip()
        runtime_cmd = _handle_runtime_command(raw)
        if not runtime_cmd:
            _post_message(client, channel_id, "Použití: `/effort low` nebo `/effort extra high`", thread_root)
            return
        _execute_runtime_command(client, workspace, channel_id, thread_root, runtime_cmd, thread_root)

    @app.command("/profile")
    def handle_profile_command(ack, body, logger):
        ack()
        user_id = body.get("user_id")
        channel_id = body.get("channel_id")
        if not _is_allowed(user_id, allowed):
            return
        thread_root = _slash_thread_root(body)
        text = str(body.get("text", "")).strip()
        raw = f"profile {text}".strip()
        runtime_cmd = _handle_runtime_command(raw)
        if not runtime_cmd:
            _post_message(client, channel_id, "Použití: `/profile default` nebo `/profile reset`", thread_root)
            return
        _execute_runtime_command(client, workspace, channel_id, thread_root, runtime_cmd, thread_root)

    @app.command("/alive")
    def handle_alive_command(ack, body, logger):
        ack()
        user_id = body.get("user_id")
        channel_id = body.get("channel_id")
        if not _is_allowed(user_id, allowed):
            return

        lines = []

        # 1. Process status (systemd or ps)
        services = {"aide-bot": "unknown", "aide-slack": "unknown", "aide-scheduler": "unknown"}
        try:
            for svc in services:
                result = subprocess.run(
                    ["systemctl", "is-active", svc],
                    capture_output=True, text=True, timeout=5,
                )
                services[svc] = result.stdout.strip() or "inactive"
        except Exception:
            # Fallback: check via ps
            for svc in services:
                services[svc] = "?"

        svc_statuses = []
        for svc, state in services.items():
            short = svc.replace("aide-", "")
            icon = "OK" if state == "active" else state.upper()
            svc_statuses.append(f"{short}: {icon}")
        lines.append(f"*Services:* {', '.join(svc_statuses)}")

        # 2. Last heartbeat
        hb_path = workspace / "data" / "last_heartbeat.json"
        try:
            with open(hb_path) as f:
                hb = json.load(f)
            sent_at = hb.get("sent_at", "")
            if sent_at:
                hb_time = datetime.fromisoformat(sent_at)
                if hb_time.tzinfo is None:
                    hb_time = hb_time.replace(tzinfo=timezone.utc)
                ago = datetime.now(timezone.utc) - hb_time
                mins = int(ago.total_seconds() // 60)
                if mins < 60:
                    lines.append(f"*Heartbeat:* pred {mins} min")
                else:
                    hours = mins // 60
                    lines.append(f"*Heartbeat:* pred {hours} hod")
            else:
                lines.append("*Heartbeat:* no data")
        except Exception:
            lines.append("*Heartbeat:* no data")

        # 3. Running agents (what's Aide doing right now?)
        now = time.time()
        if RUNNING:
            active = []
            for rkey, proc in list(RUNNING.items()):
                is_alive = True
                if hasattr(proc, "poll"):
                    is_alive = proc.poll() is None
                elif proc is True:
                    is_alive = True

                if not is_alive:
                    continue

                meta = RUNNING_META.get(rkey, {})
                elapsed = now - meta.get("started_at", now)
                elapsed_str = f"{int(elapsed // 60)}m {int(elapsed % 60)}s"

                last_tool = meta.get("last_tool")
                last_tool_at = meta.get("last_tool_at")
                prompt_preview = meta.get("prompt_preview", "")

                detail = f"Running {elapsed_str}"
                if last_tool:
                    tool_ago = int(now - last_tool_at) if last_tool_at else 0
                    detail += f" | last: {last_tool} ({tool_ago}s ago)"
                if prompt_preview:
                    detail += f"\n  _\"{prompt_preview}\"_"

                active.append(detail)

            if active:
                lines.append(f"*Agents:* {len(active)} running")
                for a in active[:5]:
                    lines.append(f"  {a}")
            else:
                lines.append("*Agents:* idle")
        else:
            lines.append("*Agents:* idle")

        # 4. Queued messages
        with THREAD_QUEUES_LOCK:
            total_queued = sum(len(q) for q in THREAD_QUEUES.values())
        if total_queued:
            lines.append(f"*Queued:* {total_queued} message(s)")

        _post_message(client, channel_id, "\n".join(lines))

    SocketModeHandler(app, app_token).start()


if __name__ == "__main__":
    main()
