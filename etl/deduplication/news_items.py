"""In-memory batch deduplication of news items.

IMPORTANT: This handles duplicates WITHIN a single ingestion batch only.
Cross-run idempotency is handled by the Supabase upsert
(on_conflict="id") — see etl/persistence/news_items.py.
"""
from __future__ import annotations

from etl.models import PersistedNewsItem


def deduplicate_items(items: list[PersistedNewsItem]) -> list[PersistedNewsItem]:
    """Remove duplicates from a single batch. First-seen item wins.

    Deduplication signals, evaluated in order:
        0. id            — application identity (primary)
        1. canonical_url — normalized URL identity
        2. content_hash  — normalized content identity

    All checks are performed BEFORE any key is committed to a seen-set,
    so a rejected item cannot pollute the deduplication state.
    """
    seen_id: set[str] = set()
    seen_canonical: set[str] = set()
    seen_content_hash: set[str] = set()
    result: list[PersistedNewsItem] = []

    for item in items:
        # --- Evaluate all signals before mutating any state ---
        is_duplicate = False
        if item.id and item.id in seen_id:
            is_duplicate = True
        elif item.canonical_url and item.canonical_url in seen_canonical:
            is_duplicate = True
        elif item.content_hash and item.content_hash in seen_content_hash:
            is_duplicate = True

        if is_duplicate:
            continue

        # --- Commit all keys atomically for accepted items only ---
        if item.id:
            seen_id.add(item.id)
        if item.canonical_url:
            seen_canonical.add(item.canonical_url)
        if item.content_hash:
            seen_content_hash.add(item.content_hash)

        result.append(item)

    return result