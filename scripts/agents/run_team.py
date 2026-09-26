"""Team graph CLI.

Usage:
    python scripts/agents/run_team.py ollama gpt-oss:120b "Tesla Model Y"
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from core.team.graph import run_team  # noqa: E402


def main() -> None:
    provider = sys.argv[1] if len(sys.argv) > 1 else "ollama"
    model_id = sys.argv[2] if len(sys.argv) > 2 else "gpt-oss:120b"
    topic = sys.argv[3] if len(sys.argv) > 3 else None
    sys.exit(run_team(provider, model_id, topic=topic))


if __name__ == "__main__":
    main()
