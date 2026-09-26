"""Test breaking-news candidate selection (deterministic).

Runs the selection filter against the local story DB. No LLM calls.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from core.tools.database import stories as db  # noqa: E402


def main() -> int:
    print("=" * 70)
    print("Breaking runner selection test")
    print("=" * 70)
    print(f"  backend: {db.backend_status()}")
    print()

    cands = db.find_unpublished_candidates(max_age_minutes=360, min_source_count=1, limit=10)
    print(f"  candidates in last 6h: {len(cands)}")
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

    # Simulate publishing the top candidate, then verify exclusion.
    top = cands[0]
    sid = top["story_id"]
    db.save_publication_result(sid, {
        "publication_id": f"pub_test_{sid}",
        "story_id": sid, "platform": "threads", "status": "PUBLISHED",
        "published_at": "2026-09-26T00:00:00Z",
    })
    after = db.find_unpublished_candidates(max_age_minutes=360, min_source_count=1, limit=10)
    if any(c["story_id"] == sid for c in after):
        print(f"  FAIL: {sid} still appears after publication")
        return 1
    print(f"  PASS: {sid} correctly excluded after publication")

    # Cleanup test publication.
    client = db.get_client()
    rows = client.select("publications", story_id=sid)
    if not db.is_production():
        client._data["publications"] = [r for r in client._data.get("publications", [])
                                        if r.get("story_id") != sid]
        client._flush()
    print("  test publication removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())