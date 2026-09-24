"""Generic RSS/Atom parser using feedparser."""

from datetime import datetime
from typing import List

import feedparser

from core.exceptions import SourceParseError
from extraction.canonicalization.url import canonicalize_url
from schemas.sources import NewsItem


def parse_feed(content: bytes, source_name: str = "rss") -> List[NewsItem]:
    """Parse RSS/Atom bytes into a list of NewsItem objects."""
    feed = feedparser.parse(content)

    # feedparser sets bozo=1 on error but may still have entries.
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
            published_at = None
            if getattr(entry, "published_parsed", None):
                published_at = datetime(*entry.published_parsed[:6])
            elif getattr(entry, "updated_parsed", None):
                published_at = datetime(*entry.updated_parsed[:6])

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
        except Exception as exc:
            raise SourceParseError(
                f"Failed to parse entry from {source_name}: {exc}"
            ) from exc

    return items