import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    """Load workspace .env into os.environ (startup only, NOT thread-safe)."""
    env_path = workspace_path / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)


def read_workspace_env(workspace_path: Path) -> dict[str, str]:
    """Read workspace .env as a dict without mutating os.environ."""
    from dotenv import dotenv_values

    env_path = workspace_path / ".env"
    if not env_path.exists():
        return {}
    values = dotenv_values(env_path)
    return {k: v for k, v in values.items() if v is not None}


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


def _parse_skill(path: Path) -> Optional[Dict[str, str]]:
    """Parse a skill file and extract name, description, and trigger info."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    name = path.stem
    title = ""
    triggers = ""

    in_activate = False
    activate_lines: List[str] = []

    for line in text.splitlines():
        stripped = line.strip()

        # First heading = title/description
        if not title and stripped.startswith("#") and "skill" in stripped.lower():
            title = stripped.lstrip("#").strip()
            # Remove "Skill: " prefix if present
            if title.lower().startswith("skill:"):
                title = title[len("skill:"):].strip()
            continue

        # Detect activation section
        if stripped.lower().startswith("##") and any(
            kw in stripped.lower() for kw in ("activate", "aktivuje")
        ):
            in_activate = True
            continue

        # Next ## heading ends activation section (### sub-headings are OK)
        if in_activate and stripped.startswith("##") and not stripped.startswith("###"):
            break

        # Skip ### sub-headings within activation section
        if in_activate and stripped.startswith("###"):
            continue

        if in_activate and stripped.startswith("-"):
            activate_lines.append(stripped.lstrip("- ").strip())

    if activate_lines:
        # Keep triggers compact — truncate long lines
        short = [l[:80].rstrip(". ") for l in activate_lines[:2]]
        triggers = "; ".join(short)

    return {"name": name, "title": title or name, "triggers": triggers}


def _generate_skills(workspace: Path, auto_dir: Path) -> str:
    """Generate skills.md and return compact skills summary for CLAUDE.md."""
    skills_dir = workspace / ".claude" / "skills"
    if not skills_dir.is_dir():
        _write_auto(auto_dir / "skills.md", "# Skills\n\n(none)\n")
        return ""

    skills = []
    for md in sorted(skills_dir.glob("*.md")):
        info = _parse_skill(md)
        if info:
            skills.append(info)

    if not skills:
        _write_auto(auto_dir / "skills.md", "# Skills\n\n(none)\n")
        return ""

    # Full auto/skills.md with triggers
    lines = ["# Available skills\n"]
    for s in skills:
        entry = f"- **{s['name']}**: {s['title']}"
        if s["triggers"]:
            entry += f" — {s['triggers']}"
        lines.append(entry)
    _write_auto(auto_dir / "skills.md", "\n".join(lines) + "\n")

    # Compact summary for CLAUDE.md
    summary_lines = ["## Skills\n"]
    for s in skills:
        entry = f"- **{s['name']}**"
        if s["triggers"]:
            entry += f" — {s['triggers']}"
        summary_lines.append(entry)

    return "\n".join(summary_lines)


def _db_conn(workspace: Path):
    """Get a Postgres connection using DATABASE_URL from workspace .env or os.environ."""
    try:
        import psycopg2
    except ImportError:
        return None
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        ws_env = read_workspace_env(workspace)
        url = ws_env.get("DATABASE_URL", "")
    if not url:
        return None
    try:
        return psycopg2.connect(url)
    except Exception:
        return None


def _db_query_tasks(workspace: Path, user_id: str = None) -> Optional[List[Dict]]:
    """Query open tasks from Postgres, filtered by user_id if provided."""
    conn = _db_conn(workspace)
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            if user_id:
                cur.execute(
                    "SELECT title, status, priority, due_date FROM tasks "
                    "WHERE status NOT IN ('done', 'completed') "
                    "AND (user_id = %s OR user_id IS NULL) "
                    "ORDER BY created_at DESC LIMIT 20",
                    (user_id,),
                )
            else:
                cur.execute(
                    "SELECT title, status, priority, due_date FROM tasks "
                    "WHERE status NOT IN ('done', 'completed') "
                    "ORDER BY created_at DESC LIMIT 20"
                )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception:
        return None
    finally:
        conn.close()


def _db_query_cron(workspace: Path, user_id: str = None) -> Optional[List[Dict]]:
    """Query active cron jobs from Postgres, filtered by user_id if provided."""
    conn = _db_conn(workspace)
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            if user_id:
                cur.execute(
                    "SELECT id, schedule, task FROM cron_jobs "
                    "WHERE enabled = true AND (user_id = %s OR user_id IS NULL) "
                    "ORDER BY id LIMIT 10",
                    (user_id,),
                )
            else:
                cur.execute(
                    "SELECT id, schedule, task FROM cron_jobs "
                    "WHERE enabled = true ORDER BY id LIMIT 10"
                )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception:
        return None
    finally:
        conn.close()


def _generate_tasks(workspace: Path, auto_dir: Path, user_id: str = None) -> None:
    open_tasks = _db_query_tasks(workspace, user_id=user_id)
    if open_tasks is None:
        # Fallback to JSON
        items = _load_json(workspace / "data" / "tasks.json", [])
        open_tasks = [t for t in items if t.get("status", "open") != "done"]

    if not open_tasks:
        _write_auto(auto_dir / "tasks.md", "# Open tasks\n\n(none)\n")
        return

    lines = ["# Open tasks\n"]
    for t in open_tasks[:20]:
        prio = t.get("priority", "")
        title = t.get("title", "(untitled)")
        due = t.get("due", "") or t.get("due_date", "")
        parts = [f"- [{prio}] {title}" if prio else f"- {title}"]
        if due:
            parts.append(f"(due: {due})")
        lines.append(" ".join(parts))

    _write_auto(auto_dir / "tasks.md", "\n".join(lines) + "\n")


def _generate_cron(workspace: Path, auto_dir: Path, user_id: str = None) -> None:
    active = _db_query_cron(workspace, user_id=user_id)
    if active is None:
        # Fallback to JSON
        items = _load_json(workspace / "data" / "cron.json", [])
        active = [j for j in items if j.get("enabled", True)]

    if not active:
        _write_auto(auto_dir / "cron.md", "# Cron jobs\n\n(none)\n")
        return

    lines = ["# Active cron jobs\n"]
    for j in active[:10]:
        jid = j.get("id", "?")
        sched = j.get("schedule", "?")
        prompt = (j.get("prompt", "") or j.get("task", "") or "")[:60]
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


def _is_migrated(workspace: Path) -> bool:
    """Check if workspace uses the new modular context structure."""
    rules = workspace / ".claude" / "rules"
    return (rules / "soul.md").exists() or (rules / "user.md").exists()


def _generate_claude_md(workspace: Path, skills_summary: str = "") -> None:
    """Generate top-level CLAUDE.md as a minimal auto-generated wrapper.

    Only runs if workspace has been migrated to modular context (soul.md/user.md
    exist). Leaves legacy CLAUDE.md untouched on non-migrated workspaces.
    """
    if not _is_migrated(workspace):
        return

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

    # Inline skills summary (compact routing table)
    if skills_summary:
        lines.append(skills_summary)
        lines.append("")

    (workspace / "CLAUDE.md").write_text("\n".join(lines), encoding="utf-8")


def generate_auto_context(workspace: Path, user_id: str = None) -> None:
    """Generate CLAUDE.md and .claude/rules/auto/ files from workspace data.

    Called at the start of every run_agent() invocation.
    Never raises — errors are silently ignored.
    """
    try:
        auto_dir = workspace / ".claude" / "rules" / "auto"
        auto_dir.mkdir(parents=True, exist_ok=True)
        # Skills first — summary is inlined into CLAUDE.md
        skills_summary = _generate_skills(workspace, auto_dir)
        _generate_claude_md(workspace, skills_summary)
        now = datetime.now()
        _write_auto(auto_dir / "datetime.md", f"# Current date and time\n\nToday is {now.strftime('%d. %m. %Y')}, {now.strftime('%H:%M')}.\n")
        _generate_tasks(workspace, auto_dir, user_id=user_id)
        _generate_cron(workspace, auto_dir, user_id=user_id)
        _generate_projects(workspace, auto_dir)
    except Exception:
        pass
