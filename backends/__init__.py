"""Backend registry for Aide agent execution engines."""

import os
from types import ModuleType


def get_backend(name: str | None = None) -> ModuleType:
    """Return the backend module for the given name.

    Reads AIDE_BACKEND env var if *name* is not provided.
    Default: ``claude-code``.
    """
    name = (name or os.environ.get("AIDE_BACKEND") or "claude-code").strip().lower()
    if not name:
        name = "claude-code"

    if name in ("claude-code", "claude"):
        from backends import claude_code
        return claude_code
    if name in ("codex", "codex-cli", "openai"):
        from backends import codex_cli
        return codex_cli

    raise ValueError(f"Unknown backend: {name!r}. Use 'claude-code' or 'codex'.")
