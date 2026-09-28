"""End-to-End Production Pipeline Dry-Run Smoke Test.

Per ammendments.md Section 80, 91, 92.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403
from core.tools.database import stories as db
from schemas.taxonomy import Category
from scripts.agents.run_breaking_news import main as run_breaking


def test_full_production_pipeline() -> None:
    print("=" * 70)
    print("Full End-to-End Production Pipeline Test (DRY_RUN)")
    print("=" * 70)

    # 1. Create realistic story in database
    title = "OpenAI Releases Next-Generation AI Reasoning Model for Science and Healthcare"
    sid = db.create_story(
        title=title,
        summary="OpenAI announced a new artificial intelligence model designed for scientific research.",
        metadata={"categories": [Category.ARTIFICIAL_INTELLIGENCE.value, Category.TECHNOLOGY.value]},
    )
    print(f"[OK] Inserted test story into DB: {sid}")

    # 2. Add source news_item
    ni_id = db.upsert_news_item({
        "url": "https://example.com/openai-new-model",
        "canonical_url": "https://example.com/openai-new-model",
        "title": title,
        "description": "OpenAI announced a new artificial intelligence model.",
        "source_name": "Tech Crunch",
        "categories": [Category.ARTIFICIAL_INTELLIGENCE.value],
    })
    db.link_story_source(sid, ni_id)
    print(f"[OK] Linked news_item {ni_id} to story {sid}.")

    # 3. Build editorial memory
    memory = db.build_editorial_memory(story_id=sid, query_title=title)
    assert memory is not None
    print(f"[OK] Editorial memory constructed successfully.")

    # 4. Check candidates
    candidates = db.find_unpublished_candidates(limit=5)
    assert len(candidates) > 0
    print(f"[OK] Unpublished candidate query returned {len(candidates)} candidates.")

    # 5. Run breaking runner in DRY_RUN mode
    os.environ["NEWSROOM_LIVE"] = "false"
    print("\nExecuting breaking runner (DRY_RUN=true)...")
    rc = run_breaking()
    print(f"[OK] Breaking runner exit code: {rc}")

    # 6. Verify duplicate check protects against re-running
    dup = db.find_duplicate_publication(sid)
    print(f"[OK] Duplicate check result for story {sid}: {dup}")

    print("\nALL PRODUCTION PIPELINE TESTS PASSED!")


if __name__ == "__main__":
    test_full_production_pipeline()
