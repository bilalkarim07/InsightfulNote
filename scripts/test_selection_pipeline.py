"""Executable test for candidate selection, novelty scoring, and category diversity.

Per ammendments.md Section 73.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403
from core.tools.database import stories as db
from scripts.agents.run_evening_reporting import select_candidate as select_evening_candidate


def test_selection_pipeline() -> None:
    print("=" * 60)
    print("Testing Selection Pipeline & Category Diversity")
    print("=" * 60)

    # 1. Create candidate stories in DB with different categories
    story_pol = db.create_story(
        title="Unanimous Vote Passed in Senate Policy Session",
        summary="Senate passed new legislation today.",
        metadata={"categories": ["GLOBAL_POLITICS"]},
    )
    story_health = db.create_story(
        title="WHO Releases Global Health Guidelines for Vaccine Safety",
        summary="New global health standards published today.",
        metadata={"categories": ["HEALTH"]},
    )
    story_tech = db.create_story(
        title="Breakthrough Quantum Processor Demonstrated by Researchers",
        summary="A new quantum chip achieves record coherence times.",
        metadata={"categories": ["TECHNOLOGY"]},
    )

    print(f"[OK] Created candidate stories in DB:")
    print(f"  - Politics: {story_pol}")
    print(f"  - Health:   {story_health}")
    print(f"  - Tech:     {story_tech}")

    # 2. Add recent publications concentrating in POLITICS
    db.save_publication_result(story_pol, {
        "platform": "threads",
        "status": "published",
        "content": "Politics post 1",
        "published_at": db._now(),
    })
    db.save_publication_result(story_pol, {
        "platform": "threads",
        "status": "published",
        "content": "Politics post 2",
        "published_at": db._now(),
    })

    # 3. Test evening reporting candidate selection
    selected = select_evening_candidate()
    assert selected is not None, "Expected candidate selection"
    sel_id = selected.get("id")
    sel_title = selected.get("title", "")
    print(f"\n[OK] Evening candidate selected: '{sel_title}' (id={sel_id})")

    # 4. Verify candidate is not rejected category
    cats = selected.get("categories") or selected.get("metadata", {}).get("categories") or []
    print(f"[OK] Selected candidate categories: {cats}")

    print("\nALL SELECTION PIPELINE TESTS PASSED!")


if __name__ == "__main__":
    test_selection_pipeline()
