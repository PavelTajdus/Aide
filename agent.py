import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from config import load_workspace_env, resolve_workspace


Event = Dict[str, object]


def _parse_json_line(line: str) -> Optional[Event]:
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _event_type(evt: Event) -> Optional[str]:
    for key in ("type", "event"):
        if key in evt and isinstance(evt[key], str):
            return evt[key]
    return None


def _extract_text(evt: Event) -> Optional[str]:
    # Common fields
    text = evt.get("text")
    if isinstance(text, str):
        return text

    # Delta-based streaming
    delta = evt.get("delta")
    if isinstance(delta, dict):
        dt = delta.get("text")
        if isinstance(dt, str):
            return dt
        if isinstance(delta.get("text_delta"), str):
            return delta.get("text_delta")
        if isinstance(delta.get("value"), str):
            return delta.get("value")

    # Content arrays
    content = evt.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        if parts:
            return "".join(parts)

    # Message wrapper
    message = evt.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            if parts:
                return "".join(parts)

    return None


ToolInfo = Dict[str, object]


def _extract_tool_info(block: Dict) -> Optional[ToolInfo]:
    """Extract tool name and input from a tool_use block."""
    name = block.get("name") or block.get("tool_name") or block.get("tool")
    if not isinstance(name, str):
        return None
    return {"name": name, "input": block.get("input", {})}


def _extract_tools_from_event(evt: Event) -> List[ToolInfo]:
    """Extract all tool info from an event."""
    tools: List[ToolInfo] = []
    seen_names: set = set()

    # Check message.content for tool_use blocks (Claude CLI format)
    message = evt.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    info = _extract_tool_info(block)
                    if info and info["name"] not in seen_names:
                        tools.append(info)
                        seen_names.add(info["name"])

    # Check for tool_use key directly
    tool_use = evt.get("tool_use")
    if isinstance(tool_use, dict):
        info = _extract_tool_info(tool_use)
        if info and info["name"] not in seen_names:
            tools.append(info)
            seen_names.add(info["name"])
    elif isinstance(tool_use, list):
        for item in tool_use:
            if isinstance(item, dict):
                info = _extract_tool_info(item)
                if info and info["name"] not in seen_names:
                    tools.append(info)
                    seen_names.add(info["name"])

    # Check for content blocks with tool_use type at top level
    content = evt.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                info = _extract_tool_info(block)
                if info and info["name"] not in seen_names:
                    tools.append(info)
                    seen_names.add(info["name"])

    return tools


def run_agent(
    prompt: str,
    session_id: Optional[str] = None,
    working_dir: Optional[Path] = None,
    timeout_s: int = 300,
    process_cb: Optional[Callable[[subprocess.Popen], None]] = None,
    tool_cb: Optional[Callable[[str, Dict], None]] = None,
) -> Tuple[str, Optional[str], List[Event]]:
    if working_dir is None:
        working_dir = resolve_workspace()

    load_workspace_env(working_dir)

    cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose"]
    skip_perms = os.environ.get("AIDE_CLAUDE_SKIP_PERMISSIONS", "1").strip().lower()
    if skip_perms in ("1", "true", "yes", "on"):
        cmd.append("--dangerously-skip-permissions")
    if session_id:
        cmd.extend(["--resume", session_id])
    cmd.append(prompt)

    proc = subprocess.Popen(
        cmd,
        cwd=str(working_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=os.environ.copy(),
    )

    if process_cb:
        process_cb(proc)

    tool_log: List[Event] = []
    assistant_chunks: List[str] = []
    final_text: Optional[str] = None
    new_session_id: Optional[str] = None
    raw_lines: List[str] = []

    start = time.time()
    while True:
        if timeout_s and (time.time() - start) > timeout_s:
            proc.terminate()
            raise TimeoutError("Claude Code CLI timed out.")

        line = proc.stdout.readline() if proc.stdout else ""
        if line == "":
            if proc.poll() is not None:
                break
            time.sleep(0.05)
            continue

        evt = _parse_json_line(line)
        if not evt:
            if line.strip():
                raw_lines.append(line.rstrip("\n"))
            continue

        etype = _event_type(evt)

        # Debug: log all events to see what Claude CLI sends
        if os.environ.get("AIDE_DEBUG_EVENTS"):
            print(f"[DEBUG] Event type={etype}, keys={list(evt.keys())}")

        if etype in ("system", "session"):
            sid = evt.get("session_id") or evt.get("session")
            if isinstance(sid, str):
                new_session_id = sid

        text = _extract_text(evt)
        if text:
            assistant_chunks.append(text)

        # Detect and extract tool use info
        tools_found = _extract_tools_from_event(evt)

        if tools_found:
            tool_log.append(evt)
            if tool_cb:
                for tool_info in tools_found:
                    tool_cb(tool_info["name"], tool_info.get("input", {}))

        if etype in ("result", "final", "message_stop"):
            text = _extract_text(evt)
            if text:
                final_text = text

    if proc.poll() is None:
        proc.wait(timeout=5)

    if final_text is None:
        final_text = "".join(assistant_chunks).strip()

    if not final_text:
        stderr = proc.stderr.read().strip() if proc.stderr else ""
        if stderr:
            final_text = f"(no output)\n{stderr}"
        elif raw_lines:
            final_text = "\n".join(raw_lines).strip()
        else:
            rc = proc.returncode
            final_text = "(no output)"
            if rc and rc != 0:
                final_text = f"(no output) (exit {rc})"

    return final_text, new_session_id, tool_log


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Claude Code CLI as Aide agent.")
    parser.add_argument("prompt", help="Prompt to send")
    parser.add_argument("--session", dest="session_id", default=None)
    parser.add_argument("--workspace", dest="workspace", default=None)
    args = parser.parse_args()

    working_dir = resolve_workspace(args.workspace)
    answer, sid, _tool_log = run_agent(args.prompt, session_id=args.session_id, working_dir=working_dir)
    if sid:
        print(f"[session_id] {sid}")
    print(answer)


if __name__ == "__main__":
    main()
