import os
from pathlib import Path
from typing import List, Optional

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
