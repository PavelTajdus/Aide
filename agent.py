"""Aide agent runner — backend-agnostic subprocess wrapper.

Public API (unchanged):
    run_agent(prompt, session_id, working_dir, timeout_s, process_cb, tool_cb)
        -> (answer_text, session_id, tool_log)

    get_session_usage(session_id, working_dir, timeout_s)
        -> dict | None

Backend is selected via AIDE_BACKEND env var (default: claude-code).
"""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from backends import get_backend
from config import load_workspace_env, resolve_workspace

Event = Dict[str, object]
ToolInfo = Dict[str, object]


def _parse_json_line(line: str) -> Optional[Event]:
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def get_session_usage(
    session_id: str,
    working_dir: Optional[Path] = None,
    timeout_s: int = 30,
) -> Optional[Dict]:
    """Get usage info for a session (backend-dependent)."""
    if working_dir is None:
        working_dir = resolve_workspace()

    load_workspace_env(working_dir)
    backend = get_backend()

    cmd = backend.build_usage_cmd(session_id, working_dir)
    if cmd is None:
        return None

    try:
        result = subprocess.run(
            cmd,
            cwd=str(working_dir),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=os.environ.copy(),
        )
        if result.returncode != 0:
            return None
        parsed = backend.parse_usage_output(result.stdout)
        if parsed:
            parsed["session_id"] = session_id
        return parsed
    except (subprocess.TimeoutExpired, Exception):
        return None


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

    backend = get_backend()
    backend.gen_context(working_dir)

    cmd = backend.build_cmd(prompt, session_id, working_dir)

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
    post_tool_chunks: List[str] = []
    saw_tool_use = False
    final_text: Optional[str] = None
    new_session_id: Optional[str] = None
    raw_lines: List[str] = []

    last_activity = time.time()
    while True:
        if timeout_s and (time.time() - last_activity) > timeout_s:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise TimeoutError("Agent CLI timed out (no activity).")

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
                last_activity = time.time()
            continue

        last_activity = time.time()
        parsed = backend.parse_event(evt)

        p_type = parsed.get("type", "ignore")
        p_text = parsed.get("text")
        p_sid = parsed.get("session_id")
        p_tools = parsed.get("tools") or []

        if os.environ.get("AIDE_DEBUG_EVENTS"):
            print(f"[DEBUG] backend={os.environ.get('AIDE_BACKEND', 'claude-code')} "
                  f"type={p_type}, raw_keys={list(evt.keys())}")

        if p_sid:
            new_session_id = p_sid

        if p_text:
            assistant_chunks.append(p_text)
            post_tool_chunks.append(p_text)

        if p_tools:
            saw_tool_use = True
            post_tool_chunks.clear()
            tool_log.append(evt)
            if tool_cb:
                for tool_info in p_tools:
                    tool_cb(tool_info["name"], tool_info.get("input", {}))

        if p_type == "result" and p_text:
            final_text = p_text

    if proc.poll() is None:
        proc.wait(timeout=5)

    if final_text is None:
        if saw_tool_use and post_tool_chunks:
            final_text = "".join(post_tool_chunks).strip()
        else:
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
    parser = argparse.ArgumentParser(description="Run Aide agent (backend-agnostic).")
    parser.add_argument("prompt", help="Prompt to send")
    parser.add_argument("--session", dest="session_id", default=None)
    parser.add_argument("--workspace", dest="workspace", default=None)
    parser.add_argument("--backend", dest="backend", default=None,
                        help="Backend: claude-code, codex")
    args = parser.parse_args()

    if args.backend:
        os.environ["AIDE_BACKEND"] = args.backend

    working_dir = resolve_workspace(args.workspace)
    answer, sid, _tool_log = run_agent(
        args.prompt, session_id=args.session_id, working_dir=working_dir
    )
    if sid:
        print(f"[session_id] {sid}")
    print(answer)


if __name__ == "__main__":
    main()
