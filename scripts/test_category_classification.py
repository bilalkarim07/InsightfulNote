"""Executable test for category classification, taxonomy normalization, and filtering.

Per ammendments.md Section 71.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from schemas.taxonomy import (
    Category, is_rejected_category, normalize_category, normalize_categories,
)


def test_category_classification() -> None:
    print("=" * 60)
    print("Testing Category Taxonomy & Classification")
    print("=" * 60)

    # 1. Test canonical Category mappings
    test_cases = [
        ("AI", Category.ARTIFICIAL_INTELLIGENCE),
        ("Artificial Intelligence", Category.ARTIFICIAL_INTELLIGENCE),
        ("tech", Category.TECHNOLOGY),
        ("Software", Category.TECHNOLOGY),
        ("US Politics", Category.GLOBAL_POLITICS),
        ("Government", Category.GLOBAL_POLITICS),
        ("Markets", Category.FINANCE),
        ("Financial markets", Category.FINANCE),
        ("Healthcare", Category.HEALTH),
        ("Space", Category.SCIENCE),
        ("Climate Change", Category.CLIMATE_ENVIRONMENT),
        ("World News", Category.WORLD_EVENTS),
    ]

    for raw, expected in test_cases:
        result = normalize_category(raw)
        assert result == expected, f"Expected {expected} for {raw!r}, got {result}"
        print(f"  [OK] {raw!r:25} -> {result.value}")

    # 2. Test multi-category list normalization
    raw_list = ["AI", "technology", "sports", "celebrity", "Global Politics"]
    normalized = normalize_categories(raw_list)
    print(f"\n[OK] Multi-category input: {raw_list}")
    print(f"[OK] Multi-category output (rejected items filtered out): {normalized}")
    assert Category.ARTIFICIAL_INTELLIGENCE.value in normalized
    assert Category.TECHNOLOGY.value in normalized
    assert Category.GLOBAL_POLITICS.value in normalized
    assert "SPORTS" not in normalized
    assert "CELEBRITY" not in normalized

    # 3. Test rejection of unwanted categories
    rejected_inputs = ["sports", "sports_news", "celebrity", "gaming", "tv_schedules", "weather", "hollywood"]
    for item in rejected_inputs:
        assert is_rejected_category(item), f"Expected {item} to be flagged as rejected"
        assert normalize_category(item) is None, f"Expected {item} to normalize to None"
        print(f"  [OK] Rejected category correctly blocked: {item!r}")

    print("\nALL CATEGORY CLASSIFICATION TESTS PASSED!")


if __name__ == "__main__":
    test_category_classification()
