"""Load environment variables from the project .env file exactly once.

Importing this module is sufficient to make .env values available via os.environ.
"""

from __future__ import annotations

from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

_LOADED = False


def load_env(force: bool = False) -> None:
    global _LOADED
    if _LOADED and not force:
        return

    if load_dotenv is None:
        _LOADED = True
        return

    # Project root is one level above this file (core/env.py -> project root).
    project_root = Path(__file__).resolve().parents[1]
    env_file = project_root / ".env"

    if env_file.exists():
        load_dotenv(env_file, override=False)
    else:
        # Fall back to default search (walks up from CWD).
        load_dotenv(override=False)

    _LOADED = True


load_env()