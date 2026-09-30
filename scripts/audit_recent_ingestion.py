"""Print recent story quality and discovery metadata from the configured database."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402
from core.tools.database import stories as db  # noqa: E402


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("metadata")
    return value if isinstance(value, dict) else {}


def _unique(values: list[str]) -> str:
    return ", ".join(dict.fromkeys(value for value in values if value)) or "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if args.hours <= 0 or args.limit <= 0:
        parser.error("--hours and --limit must be positive")

    if not db.is_production():
        print("ERROR: ingestion audit requires the configured production Supabase backend.")
        return 2

    stories = db.get_recent_stories(hours=args.hours, limit=args.limit)
    for story in stories:
        story_metadata = _metadata(story)
        sources = db.get_story_sources(str(story.get("id") or ""))
        source_metadata = [_metadata(source) for source in sources]
        categories = story.get("categories") or story_metadata.get("categories") or []
        if isinstance(categories, str):
            categories = [categories]
        publishers = [
            str(meta.get("publisher_domain") or meta.get("publisher_name") or "")
            for meta in source_metadata
        ]
        providers = [
            str(meta.get("discovery_provider") or meta.get("provider") or "")
            for meta in source_metadata
        ]
        queries = [str(meta.get("discovery_query") or "") for meta in source_metadata]
        dates = [str(source.get("published_at") or "") for source in sources]
        published = next(
            (date for date in dates if date),
            str(story_metadata.get("published_at") or ""),
        )
        print("-" * 50)
        print("TITLE: " + str(story.get("title") or "(untitled)"))
        print("PRIMARY: " + str(story_metadata.get("primary_category") or "uncategorized"))
        print("CATEGORIES: " + (", ".join(map(str, categories)) if categories else "uncategorized"))
        print("PUBLISHER: " + _unique(publishers))
        print("PROVIDER: " + _unique(providers))
        print("QUERY: " + _unique(queries))
        print("PUBLISHED: " + (published or "unknown"))
        print("SOURCES: " + str(len(sources)))
        print("TOPIC_FIT: " + ("PASS" if story_metadata.get("topic_fit") is True else "FAIL"))
        print("NEWSWORTHINESS: " + ("PASS" if story_metadata.get("newsworthiness") is True else "FAIL"))
        print("-" * 50)

    if not stories:
        print(f"No stories found in the last {args.hours} hour(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
