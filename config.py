"""Minimal .env loader. No dependency, and it never logs or echoes a value.

Existing environment variables always win, so a key exported in the shell is not overwritten by a
stale .env. Values are never printed — only whether a key is present.
"""
import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent / ".env"
SECRET_HINTS = ("key", "token", "secret", "password")


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


def is_secret(name: str) -> bool:
    return any(h in name.lower() for h in SECRET_HINTS)


def redacted_status(names: list[str]) -> str:
    """Safe to log: names only, and secrets are reported as set/unset, never shown."""
    if not names:
        return "no .env values loaded"
    return "loaded from .env: " + ", ".join(f"{n}=<set>" if is_secret(n) else n for n in names)
