"""High-level ingestion pipeline: transform → dedupe → resolve source → persist."""
from __future__ import annotations

from typing import Optional

from schemas.sources import NewsItem
from etl.models import IngestionSummary, PersistedNewsItem
from etl.transform.news_item import transform_news_item
from etl.deduplication.news_items import deduplicate_items
from etl.persistence.supabase import get_supabase
from etl.persistence.sources import get_or_create_source
from etl.persistence.news_items import upsert_news_item


class IngestionPipeline:
    def __init__(self, client=None):
        self.client = client or get_supabase()

    def ingest(
        self,
        items: list[NewsItem],
        *,
        source_name: str,
        source_type: str,
        source_domain: Optional[str] = None,
    ) -> IngestionSummary:
        summary = IngestionSummary(discovered=len(items))

        # --- 1. Transform (per-item, failure-isolated) ---
        transformed: list[PersistedNewsItem] = []
        for item in items:
            try:
                transformed.append(transform_news_item(item))
                summary.transformed += 1
            except Exception as exc:
                summary.failed += 1
                summary.errors.append(f"Transform failed for {item.url}: {exc}")

        # --- 2. Batch deduplication (in-memory, per-run) ---
        before = len(transformed)
        transformed = deduplicate_items(transformed)
        summary.skipped += before - len(transformed)

        # --- 3. Source resolution (infrastructure op — may raise) ---
        source_id = get_or_create_source(
            self.client,
            name=source_name,
            source_type=source_type,
            domain=source_domain,
        )

        # --- 4. Persist (per-item, failure-isolated) ---
        # Pre-check on `id` — the SAME field used by the upsert's
        # on_conflict. This makes inserted/updated counts truthful.
        for item in transformed:
            try:
                existing = (
                    self.client.table("news_items")
                    .select("id")
                    .eq("id", item.id)
                    .execute()
                )
                upsert_news_item(self.client, item, source_id=source_id)

                if existing.data:
                    summary.updated += 1
                else:
                    summary.inserted += 1
            except Exception as exc:
                summary.failed += 1
                summary.errors.append(f"Persist failed for {item.url}: {exc}")

        return summary