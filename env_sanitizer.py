"""Environment sanitizer for Aide agent subprocess.

Removes sensitive environment variables before passing env to the
Claude Code / Codex subprocess.  Tools (Python scripts in workspace/tools/)
load their own secrets via ``load_dotenv()`` from the ``.env`` file, so they
are unaffected by this filtering.

Configuration:
    AIDE_ENV_SANITIZE=1          Enable sanitizer (default: 1)
    AIDE_ENV_EXTRA_KEEP=FOO,BAR  Additional vars to keep (comma-separated)
"""

import os
import re
import sys
from typing import Dict, List, Optional, Set

# ── Patterns that indicate a secret ──────────────────────────────────────

_SECRET_PATTERNS: List[re.Pattern] = [
    re.compile(r"_TOKEN$", re.IGNORECASE),
    re.compile(r"_TOKEN_FILE$", re.IGNORECASE),
    re.compile(r"_SECRET$", re.IGNORECASE),
    re.compile(r"_API_KEY$", re.IGNORECASE),
    re.compile(r"_PASSWORD$", re.IGNORECASE),
    re.compile(r"_ACCESS_TOKEN$", re.IGNORECASE),
    re.compile(r"_BEARER_TOKEN$", re.IGNORECASE),
    re.compile(r"_CLIENT_ID$", re.IGNORECASE),
    re.compile(r"_CLIENT_SECRET$", re.IGNORECASE),
    re.compile(r"_LOGIN$", re.IGNORECASE),
    re.compile(r"_WEBHOOK_URL$", re.IGNORECASE),
    re.compile(r"_CREDENTIAL", re.IGNORECASE),
    re.compile(r"_CONN_STRING$", re.IGNORECASE),
    re.compile(r"_DSN$", re.IGNORECASE),
    re.compile(r"^OPENROUTER_", re.IGNORECASE),
    re.compile(r"^PERPLEXITY_", re.IGNORECASE),
    re.compile(r"^BRAIN_DB_URL$", re.IGNORECASE),
    # Cloud providers & databases
    re.compile(r"^AWS_", re.IGNORECASE),
    re.compile(r"^AZURE_", re.IGNORECASE),
    re.compile(r"^GCP_", re.IGNORECASE),
    re.compile(r"^GCLOUD_", re.IGNORECASE),
    re.compile(r"_PRIVATE_KEY$", re.IGNORECASE),
    re.compile(r"_SECRET_ACCESS_KEY$", re.IGNORECASE),
    re.compile(r"_ACCESS_KEY_ID$", re.IGNORECASE),
    re.compile(r"^DATABASE_URL$", re.IGNORECASE),
    re.compile(r"^REDIS_URL$", re.IGNORECASE),
    re.compile(r"^POSTGRES_URL$", re.IGNORECASE),
]

# ── Variables that must always be kept (even if they match patterns) ─────

_ALWAYS_KEEP: Set[str] = {
    # System
    "PATH",
    "HOME",
    "USER",
    "SHELL",
    "LANG",
    "LC_ALL",
    "TERM",
    "TMPDIR",
    "XDG_RUNTIME_DIR",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    # Python
    "PYTHONPATH",
    "PYTHONIOENCODING",
    "VIRTUAL_ENV",
    # Aide (non-secret)
    "AIDE_WORKSPACE",
    "AIDE_ENGINE",
    "AIDE_BACKEND",
    "AIDE_CLAUDE_SKIP_PERMISSIONS",
    "AIDE_DEBUG_EVENTS",
    "AIDE_ENV_SANITIZE",
    "AIDE_ENV_EXTRA_KEEP",
    "AIDE_NOTIFY_PROVIDER",
    "AIDE_SLACK_DEFAULT_TARGET",
    "AIDE_SLACK_DEFAULT_CHANNEL_ID",
    "AIDE_SLACK_DEFAULT_USER_ID",
    "AIDE_SLACK_DEFAULT_TARGET_TYPE",
    "AIDE_SLACK_CHANNEL_ID",
    "AIDE_SLACK_THREAD_TS",
    "AIDE_DEFAULT_CHAT_ID",
    # Git
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    # Claude Code reads ANTHROPIC_API_KEY from user .env (not engine)
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "ANTHROPIC_MODEL",
}


def _is_secret(key: str) -> bool:
    """Check if an env var name looks like a secret."""
    for pat in _SECRET_PATTERNS:
        if pat.search(key):
            return True
    return False


def sanitize_env(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Return a copy of ``env`` (default: os.environ) with secrets removed.

    Respects AIDE_ENV_SANITIZE (default "1") — set to "0" to disable.
    """
    if env is None:
        env = dict(os.environ)
    else:
        env = dict(env)

    enabled = env.get("AIDE_ENV_SANITIZE", "1").strip().lower()
    if enabled in ("0", "false", "no", "off"):
        return env

    # Parse extra keep list
    extra_keep_raw = env.get("AIDE_ENV_EXTRA_KEEP", "")
    extra_keep = {k.strip() for k in extra_keep_raw.split(",") if k.strip()}
    keep = _ALWAYS_KEEP | extra_keep

    removed = []
    for key in list(env.keys()):
        if key in keep:
            continue
        if _is_secret(key):
            removed.append(key)
            del env[key]

    debug = str(env.get("AIDE_DEBUG_EVENTS", "")).strip().lower()
    if removed and debug in ("1", "true", "yes", "on"):
        print(f"[env-sanitizer] Removed {len(removed)} secret(s)", file=sys.stderr)

    return env
