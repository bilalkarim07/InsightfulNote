"""Generic RSS/Atom parser using feedparser."""

from datetime import datetime, timezone
from typing import List

import feedparser

from core.exceptions import SourceParseError
from extraction.canonicalization.url import canonicalize_url
from schemas.sources import NewsItem


def _struct_to_utc(struct) -> datetime | None:
    """Convert a feedparser time.struct_time (UTC) to aware UTC datetime."""
    if not struct:
        return None
    try:
        return datetime(*struct[:6], tzinfo=timezone.utc)
    except Exception:
        return None


def parse_feed(content: bytes, source_name: str = "rss") -> List[NewsItem]:
    """Parse RSS/Atom bytes into a list of NewsItem objects.

    A single malformed entry is skipped, not fatal: only a completely
    unparseable feed raises ``SourceParseError``.
    """
    feed = feedparser.parse(content)

    if feed.bozo and not feed.entries:
        raise SourceParseError(
            f"Feed parsing failed for {source_name}: {feed.bozo_exception}"
        )

    items: List[NewsItem] = []
    for entry in feed.entries:
        try:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue

            description = entry.get("description") or entry.get("summary")

            published_at = (
                _struct_to_utc(getattr(entry, "published_parsed", None))
                or _struct_to_utc(getattr(entry, "updated_parsed", None))
            )

            author = entry.get("author")
            guid = entry.get("id") or entry.get("guid")
            categories = [
                tag.get("term")
                for tag in entry.get("tags", [])
                if tag.get("term")
            ]

            item = NewsItem(
                id=guid,
                title=title,
                url=link,
                canonical_url=canonicalize_url(link),
                description=description,
                snippet=description,
                source_name=source_name,
                author=author,
                published_at=published_at,
                categories=categories,
                metadata={"feed_entry": dict(entry)},
            )
            items.append(item)
        except Exception:
            # One bad entry must not abort the entire feed.
            continue

    return items