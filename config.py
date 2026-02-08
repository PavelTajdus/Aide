import json
import os
from pathlib import Path
from typing import Any, List, Optional

from dotenv import load_dotenv


ENGINE_ROOT = Path(__file__).resolve().parent


def resolve_engine() -> Path:
    env = os.environ.get("AIDE_ENGINE")
    if env:
        return Path(env).expanduser().resolve()
    return ENGINE_ROOT


def resolve_workspace(workspace_arg: Optional[str] = None) -> Path:
    if workspace_arg:
        return Path(workspace_arg).expanduser().resolve()

    env = os.environ.get("AIDE_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()

    # Fallback: if current working directory looks like workspace
    cwd = Path.cwd()
    if (cwd / "CLAUDE.md").exists() or (cwd / "data").exists():
        return cwd.resolve()

    raise RuntimeError("Workspace path not provided. Set AIDE_WORKSPACE or pass --workspace.")


def load_workspace_env(workspace_path: Path) -> None:
    env_path = workspace_path / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)


def get_allowed_users() -> List[int]:
    raw = os.environ.get("ALLOWED_USERS", "")
    if not raw.strip():
        return []
    parts = [p.strip() for p in raw.replace(";", ",").split(",")]
    ids = []
    for part in parts:
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            continue
    return ids


# ---------------------------------------------------------------------------
# Auto-generated context files (.claude/rules/auto/)
# ---------------------------------------------------------------------------

_AUTO_HEADER = "<!-- Auto-generated, do not edit -->\n\n"


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_auto(path: Path, content: str) -> None:
    path.write_text(_AUTO_HEADER + content, encoding="utf-8")


def _generate_skills(workspace: Path, auto_dir: Path) -> None:
    skills_dir = workspace / ".claude" / "skills"
    if not skills_dir.is_dir():
        _write_auto(auto_dir / "skills.md", "# Skills\n\n(none)\n")
        return

    lines = ["# Available skills\n"]
    for md in sorted(skills_dir.glob("*.md")):
        name = md.stem
        # Read first non-empty line as description
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        desc = ""
        for line in text.splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                desc = stripped
                break
        lines.append(f"- **{name}**: {desc}")

    _write_auto(auto_dir / "skills.md", "\n".join(lines) + "\n")


def _generate_tasks(workspace: Path, auto_dir: Path) -> None:
    items = _load_json(workspace / "data" / "tasks.json", [])
    open_tasks = [t for t in items if t.get("status", "open") != "done"]
    if not open_tasks:
        _write_auto(auto_dir / "tasks.md", "# Open tasks\n\n(none)\n")
        return

    lines = ["# Open tasks\n"]
    for t in open_tasks[:20]:
        prio = t.get("priority", "")
        title = t.get("title", "(untitled)")
        due = t.get("due", "")
        parts = [f"- [{prio}] {title}" if prio else f"- {title}"]
        if due:
            parts.append(f"(due: {due})")
        lines.append(" ".join(parts))

    _write_auto(auto_dir / "tasks.md", "\n".join(lines) + "\n")


def _generate_cron(workspace: Path, auto_dir: Path) -> None:
    items = _load_json(workspace / "data" / "cron.json", [])
    active = [j for j in items if j.get("enabled", True)]
    if not active:
        _write_auto(auto_dir / "cron.md", "# Cron jobs\n\n(none)\n")
        return

    lines = ["# Active cron jobs\n"]
    for j in active[:10]:
        jid = j.get("id", "?")
        sched = j.get("schedule", "?")
        prompt = j.get("prompt", "")[:60]
        lines.append(f"- `{jid}` — `{sched}` — {prompt}")

    _write_auto(auto_dir / "cron.md", "\n".join(lines) + "\n")


def _generate_projects(workspace: Path, auto_dir: Path) -> None:
    items = _load_json(workspace / "data" / "projects.json", [])
    active = [p for p in items if p.get("status", "active") != "archived"]
    if not active:
        _write_auto(auto_dir / "projects.md", "# Projects\n\n(none)\n")
        return

    lines = ["# Active projects\n"]
    for p in active[:10]:
        name = p.get("name", "(unnamed)")
        status = p.get("status", "")
        lines.append(f"- **{name}**" + (f" ({status})" if status else ""))

    _write_auto(auto_dir / "projects.md", "\n".join(lines) + "\n")


def _generate_claude_md(workspace: Path) -> None:
    """Generate top-level CLAUDE.md as a minimal auto-generated wrapper."""
    lines = [
        "<!-- Auto-generated at each agent run. Your config lives in .claude/rules/ -->",
        "",
        "# Aide",
        "",
        "You are Aide, a personal AI copilot.",
        "Your full configuration is loaded from `.claude/rules/` automatically.",
        "",
    ]

    # Inline user.md content if it exists (so CLAUDE.md shows user context)
    user_md = workspace / ".claude" / "rules" / "user.md"
    if user_md.exists():
        try:
            content = user_md.read_text(encoding="utf-8").strip()
            if content:
                lines.append(content)
                lines.append("")
        except Exception:
            pass

    (workspace / "CLAUDE.md").write_text("\n".join(lines), encoding="utf-8")


def generate_auto_context(workspace: Path) -> None:
    """Generate CLAUDE.md and .claude/rules/auto/ files from workspace data.

    Called at the start of every run_agent() invocation.
    Never raises — errors are silently ignored.
    """
    try:
        auto_dir = workspace / ".claude" / "rules" / "auto"
        auto_dir.mkdir(parents=True, exist_ok=True)
        _generate_claude_md(workspace)
        _generate_skills(workspace, auto_dir)
        _generate_tasks(workspace, auto_dir)
        _generate_cron(workspace, auto_dir)
        _generate_projects(workspace, auto_dir)
    except Exception:
        pass
