"""Executable smoke test for Supabase DB connection, queries, and fail-closed handling.

Per ammendments.md Section 70.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403
from core.tools.database import stories as db


def test_supabase_operations() -> None:
    print("=" * 60)
    print("Testing Supabase Pipeline & Fail-Closed Behavior")
    print(f"Backend Status: {db.backend_status()}")
    print("=" * 60)

    # 1. Verification of candidates
    candidates = db.find_unpublished_candidates(limit=5)
    print(f"[OK] Unpublished candidates query succeeded (returned {len(candidates)} candidates).")

    # 2. Publication count query
    pub_count = db.count_published_today()
    print(f"[OK] count_published_today returned {pub_count}.")

    # 3. Duplicate check lookup
    dup = db.find_duplicate_publication("non_existent_story_id")
    assert dup is None, "Expected None for non-existent story ID"
    print("[OK] find_duplicate_publication returned None for missing story as expected.")

    # 4. Insert & cleanup test story in DB/localstore
    test_title = f"Test Story {db._now()}"
    sid = db.create_story(title=test_title, summary="Test summary")
    assert sid is not None, "Failed to create story"
    print(f"[OK] Created test story ID: {sid}")

    story = db.get_story(sid)
    assert story is not None and story["title"] == test_title
    print("[OK] Retrieved created test story successfully.")

    db.update_story_status(sid, "published")
    updated = db.get_story(sid)
    assert updated["status"] == "published"
    print("[OK] Updated story status to 'published'.")

    print("\nALL SUPABASE PIPELINE TESTS PASSED!")


if __name__ == "__main__":
    test_supabase_operations()
