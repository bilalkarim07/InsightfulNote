"""Bootstrap: load .env from repository root before anything else.

Import this FIRST in any executable script:

    from scripts._bootstrap import *  # noqa
"""
from __future__ import annotations

from pathlib import Path

# Try python-dotenv; fail loudly if unavailable.
try:
    from dotenv import load_dotenv
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "python-dotenv is required. Install with: pip install python-dotenv"
    ) from exc

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / ".env"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=False)
else:
    # Fall back to default search (cwd) if .env not at repo root
    load_dotenv(override=False)


def require_local_test_backend(database) -> None:
    """Prevent executable tests with synthetic fixtures from writing to Supabase."""
    try:
        if database.is_production():
            raise SystemExit(
                "Synthetic test data is prohibited against Supabase; use a local database."
            )
    except SystemExit:
        raise
    except Exception as exc:
        raise SystemExit(
            "Cannot verify a local test backend; refusing to use synthetic data: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
