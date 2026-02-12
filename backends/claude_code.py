"""Claude Code CLI backend for Aide.

Handles command construction, JSONL event parsing, and context generation
for the ``claude`` CLI tool.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import generate_auto_context

# ── Types ────────────────────────────────────────────────────────────────

Event = Dict[str, object]
ToolInfo = Dict[str, object]
ParsedEvent = Dict[str, Any]

# ── Command construction ─────────────────────────────────────────────────


def build_cmd(
    prompt: str,
    session_id: Optional[str] = None,
    working_dir: Optional[Path] = None,
) -> list[str]:
    """Build the ``claude`` CLI command list."""
    cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose"]

    skip = os.environ.get("AIDE_CLAUDE_SKIP_PERMISSIONS", "1").strip().lower()
    if skip in ("1", "true", "yes", "on"):
        cmd.append("--dangerously-skip-permissions")

    if session_id:
        cmd.extend(["--resume", session_id])

    cmd.append(prompt)
    return cmd


# ── Context generation ───────────────────────────────────────────────────


def gen_context(workspace: Path) -> None:
    """Generate context files for Claude Code (CLAUDE.md + .claude/rules/auto/)."""
    generate_auto_context(workspace)


# ── Event parsing helpers (moved from agent.py) ─────────────────────────


def _event_type(evt: Event) -> Optional[str]:
    for key in ("type", "event"):
        if key in evt and isinstance(evt[key], str):
            return evt[key]
    return None


def _extract_text(evt: Event) -> Optional[str]:
    # Direct text field
    text = evt.get("text")
    if isinstance(text, str):
        return text

    # Result field (Claude CLI result event)
    result = evt.get("result")
    if isinstance(result, str):
        return result

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
        parts = [
            item["text"]
            for item in content
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ]
        if parts:
            return "".join(parts)

    # Message wrapper
    message = evt.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list):
            parts = [
                item["text"]
                for item in content
                if isinstance(item, dict)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ]
            if parts:
                return "".join(parts)

    return None


def _extract_tool_info(block: Dict) -> Optional[ToolInfo]:
    """Extract tool name and input from a tool_use block."""
    name = block.get("name") or block.get("tool_name") or block.get("tool")
    if not isinstance(name, str):
        return None
    return {"name": name, "input": block.get("input", {})}


def _extract_tools_from_event(evt: Event) -> List[ToolInfo]:
    """Extract all tool info from an event."""
    tools: List[ToolInfo] = []
    seen: set = set()

    # message.content tool_use blocks
    message = evt.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    info = _extract_tool_info(block)
                    if info and info["name"] not in seen:
                        tools.append(info)
                        seen.add(info["name"])

    # Direct tool_use key
    tool_use = evt.get("tool_use")
    if isinstance(tool_use, dict):
        info = _extract_tool_info(tool_use)
        if info and info["name"] not in seen:
            tools.append(info)
            seen.add(info["name"])
    elif isinstance(tool_use, list):
        for item in tool_use:
            if isinstance(item, dict):
                info = _extract_tool_info(item)
                if info and info["name"] not in seen:
                    tools.append(info)
                    seen.add(info["name"])

    # Top-level content blocks
    content = evt.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                info = _extract_tool_info(block)
                if info and info["name"] not in seen:
                    tools.append(info)
                    seen.add(info["name"])

    return tools


# ── Main parse function ──────────────────────────────────────────────────


def parse_event(evt: Event) -> ParsedEvent:
    """Normalize a Claude Code JSONL event into a standard format.

    Returns ``ParsedEvent`` with keys:
        type: "text" | "tool" | "session" | "result" | "ignore"
        text: extracted text or None
        session_id: session identifier or None
        tools: list of {name, input} dicts
    """
    parsed: ParsedEvent = {
        "type": "ignore",
        "text": None,
        "session_id": None,
        "tools": [],
    }

    etype = _event_type(evt)

    # Session / system events
    if etype in ("system", "session"):
        sid = evt.get("session_id") or evt.get("session")
        if isinstance(sid, str):
            parsed["type"] = "session"
            parsed["session_id"] = sid
        return parsed

    # Text extraction
    text = _extract_text(evt)

    # Tool extraction
    tools = _extract_tools_from_event(evt)

    # Result / final events
    if etype in ("result", "final", "message_stop"):
        parsed["type"] = "result"
        parsed["text"] = text
        return parsed

    # Tool use events
    if tools:
        parsed["type"] = "tool"
        parsed["tools"] = tools
        parsed["text"] = text
        return parsed

    # Plain text
    if text is not None:
        parsed["type"] = "text"
        parsed["text"] = text
        return parsed

    return parsed


# ── Session usage ────────────────────────────────────────────────────────


def build_usage_cmd(
    session_id: str,
    working_dir: Optional[Path] = None,
) -> Optional[list[str]]:
    """Build command to query session usage."""
    cmd = [
        "claude", "-p", "--output-format", "json",
        "--resume", session_id,
        "Reply only: ok",
    ]
    skip = os.environ.get("AIDE_CLAUDE_SKIP_PERMISSIONS", "1").strip().lower()
    if skip in ("1", "true", "yes", "on"):
        cmd.append("--dangerously-skip-permissions")
    return cmd


def parse_usage_output(stdout: str) -> Optional[Dict]:
    """Parse JSON output from a usage query."""
    try:
        data = json.loads(stdout)
        return {
            "usage": data.get("usage", {}),
            "model_usage": data.get("modelUsage", {}),
            "cost_usd": data.get("total_cost_usd", 0),
        }
    except json.JSONDecodeError:
        return None
