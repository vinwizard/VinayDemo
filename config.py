"""Minimal .env loader. No dependency, and it never logs or echoes a value.

Existing environment variables always win, so a key exported in the shell is not overwritten by a
stale .env. Values are never printed — only whether a key is present.
"""
import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent / ".env"


def load_env(path: Path = ENV_FILE) -> list[str]:
    """Loads KEY=value lines. Returns the names (never values) of the keys it set."""
    if not path.exists():
        return []
    loaded = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if not name or not value or name in os.environ:
            continue
        os.environ[name] = value
        loaded.append(name)
    return loaded


def setting(env: str, default, floor=0, cast=int):
    """A number env setting (a count, or with cast=float a dollar budget), never below `floor`. Anything
    unreadable is the default rather than a crash mid-run: a typo in Render must not end a paid run."""
    try:
        return max(floor, cast(os.environ.get(env) or default))
    except ValueError:
        return default
