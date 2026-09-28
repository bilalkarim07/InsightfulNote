"""Executable test for Editorial Memory and repetition/material-update detection.

Per ammendments.md Section 72.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403
from core.tools.database import stories as db
from schemas.editorial_memory import EditorialMemory


def test_editorial_memory() -> None:
    print("=" * 60)
    print("Testing Editorial Memory & Story Repetition Detection")
    print("=" * 60)

    title_a = "Apple announces new artificial intelligence features at WWDC"
    title_b = "Apple unveils its latest artificial intelligence features"
    title_c = "Apple delays artificial intelligence features following security audit"

    # 1. Create and publish Story A
    story_a_id = db.create_story(title=title_a, summary="Initial AI announcement.")
    db.save_publication_result(story_a_id, {
        "platform": "threads",
        "status": "published",
        "content": title_a,
        "external_post_id": "threads_post_123",
        "published_at": db._now(),
    })
    print(f"[OK] Published Story A: '{title_a}' ({story_a_id})")

    # 2. Search for similar stories for Story B (should detect REPETITIVE/DUPLICATE)
    similar_b = db.find_similar_recent_stories(title_b, hours=24, limit=5)
    assert len(similar_b) > 0, "Expected similar story detection for Story B"
    top_rel_b = similar_b[0]["relationship"]
    print(f"[OK] Story B similarity detection: top match '{similar_b[0]['title'][:50]}...' -> relationship={top_rel_b} (score={similar_b[0]['score']:.2f})")
    assert top_rel_b in ("DUPLICATE", "REPETITIVE"), f"Expected DUPLICATE or REPETITIVE, got {top_rel_b}"

    # 3. Search for similar stories for Story C (material update)
    similar_c = db.find_similar_recent_stories(title_c, hours=24, limit=5)
    assert len(similar_c) > 0, "Expected similar story detection for Story C"
    top_rel_c = similar_c[0]["relationship"]
    print(f"[OK] Story C similarity detection: top match '{similar_c[0]['title'][:50]}...' -> relationship={top_rel_c} (score={similar_c[0]['score']:.2f})")

    # 4. Build complete EditorialMemory object
    memory_dict = db.build_editorial_memory(story_id=story_a_id, query_title=title_b)
    memory = EditorialMemory.model_validate(memory_dict)

    assert len(memory.recent_publications) > 0, "Expected non-empty recent publications"
    assert len(memory.repetition_warnings) > 0, "Expected repetition warning for repetitive title"

    print(f"[OK] EditorialMemory constructed successfully:")
    print(f"  - Recent publications: {len(memory.recent_publications)}")
    print(f"  - Recent stories: {len(memory.recent_stories)}")
    print(f"  - Category distribution: {memory.category_distribution}")
    print(f"  - Repetition warnings: {len(memory.repetition_warnings)}")

    print("\nALL EDITORIAL MEMORY TESTS PASSED!")


if __name__ == "__main__":
    test_editorial_memory()
