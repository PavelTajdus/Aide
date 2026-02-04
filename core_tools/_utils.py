import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from dotenv import load_dotenv


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def resolve_workspace() -> Path:
    env = os.environ.get("AIDE_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()

    cwd = Path.cwd()
    if (cwd / ".env").exists() or (cwd / "data").exists():
        return cwd.resolve()

    raise RuntimeError("Workspace path not found. Set AIDE_WORKSPACE or run from workspace.")


def load_workspace_env(workspace: Path) -> None:
    env_path = workspace / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def iso_now() -> str:
    from datetime import datetime

    return datetime.now().isoformat()


def parse_dt(value: Optional[str]):
    from datetime import datetime

    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None
