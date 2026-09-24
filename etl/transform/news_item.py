"""Transform an extracted NewsItem into a PersistedNewsItem."""
from __future__ import annotations

from schemas.sources import NewsItem
from etl.models import PersistedNewsItem
from etl.transform.hashing import compute_content_hash, compute_canonical_hash
from extraction.canonicalization.url import canonicalize_url


def transform_news_item(item: NewsItem) -> PersistedNewsItem:
    """Convert a NewsItem into a persistence-ready model."""
    # Canonical URL: reuse existing or compute from raw URL
    canonical = item.canonical_url or canonicalize_url(item.url)

    # Content hash
    content_hash = compute_content_hash(item.content)

    # Canonical hash
    canonical_hash = compute_canonical_hash(canonical)

    # Merge ETL metadata without destroying existing
    metadata = dict(item.metadata)
    metadata["etl"] = {
        "transformed": True,
        "transform_version": "1",
    }

    return PersistedNewsItem(
        id=item.id,
        source_id=None,  # resolved later
        title=item.title,
        url=item.url,
        canonical_url=canonical,
        description=item.description,
        snippet=item.snippet,
        source_name=item.source_name,
        source_domain=item.source_domain,
        author=item.author,
        published_at=item.published_at,
        discovered_at=item.discovered_at,
        content=item.content,
        language=item.language,
        country=item.country,
        categories=item.categories,
        metadata=metadata,
        content_hash=content_hash,
        canonical_hash=canonical_hash,
    )