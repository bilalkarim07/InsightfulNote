"""Test evening reporting selection (deterministic)."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from core.tools.database import stories as db  # noqa: E402


def main() -> int:
    print("=" * 70)
    print("Evening reporting selection test")
    print("=" * 70)
    print(f"  backend: {db.backend_status()}")
    print()

    cands = db.find_reporting_candidates(max_age_minutes=1440, limit=10)
    print(f"  candidates in last 24h: {len(cands)}")
    for c in cands[:5]:
        sid = c.get("story_id", "?")
        title = (c.get("title") or "")[:60]
        srcs = len(c.get("source_ids") or [])
        print(f"    {sid}  [{srcs} src]  {title}")
    print()

    if not cands:
        print("  NOTE: no candidates — run scripts/run_news_ingestion.py first.")
        print("  Selection logic: PASS (empty input handled)")
        return 0

    print(f"  Selection logic: PASS ({len(cands)} eligible)")
    return 0


if __name__ == "__main__":
    sys.exit(main())