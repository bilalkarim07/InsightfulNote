"""Idempotent upsert of news_items."""
from __future__ import annotations

from typing import Optional

from supabase import Client

from etl.models import PersistedNewsItem


def upsert_news_item(
    client: Client,
    item: PersistedNewsItem,
    source_id: Optional[str] = None,
) -> dict:
    """Upsert a news item using canonical_url as conflict key.

    Returns the persisted row dict.
    """
    if source_id:
        item.source_id = source_id

    row = item.model_dump(mode="json")
    # Supabase expects camelCase? No – it uses column names directly.
    # Ensure UUID is stringified
    if row.get("source_id"):
        row["source_id"] = str(row["source_id"])

    # Upsert on canonical_url if present, else on url
    conflict_key = "canonical_url" if item.canonical_url else "url"

    resp = (
        client.table("news_items")
        .upsert(row, on_conflict=conflict_key)
        .execute()
    )
    if not resp.data:
        raise RuntimeError(f"Supabase upsert returned no data for {item.id}")
    return resp.data[0]