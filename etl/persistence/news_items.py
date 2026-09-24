"""Idempotent upsert of news_items — aligned on NewsItem.id."""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from supabase import Client

from etl.models import PersistedNewsItem


def upsert_news_item(
    client: Client,
    item: PersistedNewsItem,
    source_id: Optional[UUID | str] = None,
) -> dict:
    """Upsert a news_item using `id` as the conflict key."""
    if source_id is not None:
        # Normalize to UUID so Pydantic serializes cleanly.
        item.source_id = source_id if isinstance(source_id, UUID) else UUID(str(source_id))

    row = item.model_dump(mode="json")

    resp = (
        client.table("news_items")
        .upsert(row, on_conflict="id")
        .execute()
    )

    if not resp.data:
        raise RuntimeError(f"news_items upsert returned no data for id={item.id}")
    return resp.data[0]