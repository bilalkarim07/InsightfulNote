"""Executable test for category classification, taxonomy normalization, and filtering.

Per ammendments.md Section 71.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from schemas.taxonomy import (
    Category, classify_article, is_rejected_category, normalize_category,
    normalize_categories, is_publication_current,
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
    assert Category.SPORTS.value in normalized
    assert "CELEBRITY" not in normalized

    # 3. Test rejection of unwanted categories
    rejected_inputs = ["sports_news", "celebrity", "gaming", "tv_schedules", "weather", "hollywood"]
    for item in rejected_inputs:
        assert is_rejected_category(item), f"Expected {item} to be flagged as rejected"
        assert normalize_category(item) is None, f"Expected {item} to normalize to None"
        print(f"  [OK] Rejected category correctly blocked: {item!r}")

    valid_sports_input = "sports"
    assert normalize_category(valid_sports_input) == Category.SPORTS
    assert not is_rejected_category(valid_sports_input)
    print(f"  [OK] Valid category kept in scope: {valid_sports_input!r}")

    classification_cases = [
        (
            "OpenAI announces a new AI model",
            Category.ARTIFICIAL_INTELLIGENCE,
            True,
        ),
        (
            "Federal Reserve announces interest-rate decision",
            Category.FINANCE,
            True,
        ),
        (
            "Major clinical trial reports results",
            Category.MEDICAL,
            True,
        ),
        (
            "Ceasefire agreement announced after negotiations",
            Category.WAR_CONFLICT,
            True,
        ),
        (
            "Major semiconductor company announces new chip",
            Category.TECHNOLOGY,
            True,
        ),
        (
            "Champions League final result",
            Category.SPORTS,
            True,
        ),
    ]
    for title, expected, newsworthy in classification_cases:
        quality = classify_article(title=title, source_name="Google News")
        assert expected.value in quality["categories"], (
            f"Expected {expected.value} for {title!r}: {quality}"
        )
        assert quality["primary_category"] == expected.value, (
            f"Unexpected primary category for {title!r}: {quality}"
        )
        assert quality["newsworthiness"] is newsworthy, (
            f"Unexpected newsworthiness for {title!r}: {quality}"
        )
        print(f"  [OK] Article classified: {title!r} -> {expected.value}")

    rejected_articles = [
        "Actor gives interview about upcoming film",
        "Celebrity shares lifestyle advice",
        "Best products to buy this month",
        "Artist discusses new exhibition",
    ]
    for title in rejected_articles:
        quality = classify_article(title=title, description=title)
        assert quality["topic_fit"] is False, (
            f"Expected out-of-scope article to be rejected: {title!r} ({quality})"
        )
        assert quality["newsworthiness"] is False, (
            f"Expected non-development article to be rejected: {title!r} ({quality})"
        )
        print(f"  [OK] Out-of-scope article rejected: {title!r}")

    evergreen_articles = [
        (
            "Golfers With the Most Wins in Major Championships",
            "Historical statistics list the golfers with the most career wins.",
        ),
        (
            "Golf Tournaments: results",
            "Browse tournament results and historical scorecards.",
        ),
        (
            "The Paris Agreement",
            "The treaty was adopted in 2015 and entered into force in 2016.",
        ),
    ]
    for title, description in evergreen_articles:
        quality = classify_article(title=title, description=description)
        assert quality["newsworthiness"] is False, (
            f"Evergreen content must not pass the newsworthiness gate: {quality}"
        )

    # The discovery query is deliberately not an input to the classifier.
    unrelated = classify_article(
        title="Artist gives interview about a new exhibition",
        description="The artist discusses the exhibition and upcoming film.",
        snippet="Interview and lifestyle coverage.",
    )
    assert unrelated["categories"] == []
    assert unrelated["primary_category"] is None
    assert unrelated["topic_fit"] is False
    assert unrelated["newsworthiness"] is False
    print("  [OK] Unrelated article remains out of scope under a politics query")

    from scripts.run_news_ingestion import _build_news_item, _reject_reason

    assert is_publication_current(datetime.now(timezone.utc).isoformat())
    assert not is_publication_current(None)
    assert not is_publication_current("2020-01-01T00:00:00Z")

    current_article = {
        "url": "https://example.com/semiconductor-expansion",
        "title": "Semiconductor company announces $1 billion expansion",
        "description": "The company announced a semiconductor facility expansion today.",
        "published_at": "2026-09-29T12:00:00Z",
    }
    assert _reject_reason(current_article, "tavily") is None
    assert _reject_reason(
        {
            "url": "https://example.com/undated-announcement",
            "title": "Company announces a major semiconductor expansion",
            "description": "The company announced a new facility expansion.",
        },
        "tavily",
    ) == "INSUFFICIENT_METADATA"
    assert _reject_reason(
        {
            "url": "https://example.com/dated-announcement",
            "title": "Company announces a major semiconductor expansion",
            "description": "The company announced a new facility expansion.",
            "metadata": {
                "tavily_published_date": datetime.now(timezone.utc).isoformat()
            },
        },
        "tavily",
    ) is None
    assert _reject_reason(
        {
            "url": "https://example.com/artist-interview",
            "title": "Artist gives interview about a new exhibition",
            "description": "The artist discusses the exhibition.",
        },
        "google_news",
    ) == "OPINION_CONTENT"

    mismatched_query = _build_news_item(
        {
            "url": "https://example.com/artist-interview",
            "title": "Artist gives interview about a new exhibition",
            "description": "The artist discusses an exhibition and an upcoming film.",
            "categories": ["GLOBAL_POLITICS"],
            "discovery_query": "global politics latest",
        },
        "google_news",
        "source-test",
    )
    assert mismatched_query is None, (
        "An unrelated article must not inherit query/provider categories"
    )

    article_based = _build_news_item(
        {
            "url": "https://example.com/openai-model",
            "title": "OpenAI announces a new AI model",
            "description": "OpenAI announced the model at a company event today.",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "categories": ["GLOBAL_POLITICS"],
            "discovery_query": "global politics latest",
        },
        "google_news",
        "source-test",
    )
    assert article_based is not None
    assert article_based["categories"] == [Category.ARTIFICIAL_INTELLIGENCE.value]
    assert article_based["metadata"]["primary_category"] == Category.ARTIFICIAL_INTELLIGENCE.value
    assert article_based["metadata"]["discovery_query"] == "global politics latest"
    print("  [OK] Production ingestion classifies article content, not discovery metadata")

    print("\nALL CATEGORY CLASSIFICATION TESTS PASSED!")


if __name__ == "__main__":
    test_category_classification()
