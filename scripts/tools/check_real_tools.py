"""Check which real tools the agent layer successfully wired."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from core.tools.search import real_tools_status, ALL_SEARCH_TOOLS  # noqa: E402
from core.tools.publishing import threads_status  # noqa: E402


def main() -> None:
    print("=" * 70)
    print("Real tool wiring status")
    print("=" * 70)
    print(f"  search:  {real_tools_status()}")
    print(f"  threads: {threads_status()}")
    print()
    print(f"  search tools loaded: {len(ALL_SEARCH_TOOLS)}")
    for t in ALL_SEARCH_TOOLS:
        print(f"    - {getattr(t, 'name', '?')}")
    print()


if __name__ == "__main__":
    main()
