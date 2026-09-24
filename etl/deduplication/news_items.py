"""In-memory deduplication of news items."""
from __future__ import annotations

from etl.models import PersistedNewsItem


def deduplicate_items(items: list[PersistedNewsItem]) -> list[PersistedNewsItem]:
    """Remove duplicates by canonical_url, then by content_hash.

    Preserves first-seen order.
    """
    seen_canonical: set[str] = set()
    seen_content_hash: set[str] = set()
    result: list[PersistedNewsItem] = []

    for item in items:
        # Level 1 & 2: canonical URL dedup
        if item.canonical_url:
            if item.canonical_url in seen_canonical:
                continue
            seen_canonical.add(item.canonical_url)

        # Level 3: content hash dedup (only if no canonical URL collision)
        if item.content_hash:
            if item.content_hash in seen_content_hash:
                continue
            seen_content_hash.add(item.content_hash)

        result.append(item)

    return result