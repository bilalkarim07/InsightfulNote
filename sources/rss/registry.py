"""Validated configuration loader for direct publisher RSS/Atom feeds."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from schemas.taxonomy import PRODUCTION_CATEGORY_ALLOWLIST


@dataclass(frozen=True)
class RSSFeed:
    id: str
    name: str
    url: str
    category: str
    publisher_domain: str
    priority: int
    active: bool


def load_rss_registry() -> tuple[RSSFeed, ...]:
    registry_path = Path(__file__).with_name("feeds.json")
    raw_feeds = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(raw_feeds, list):
        raise ValueError("RSS registry must contain a JSON list")

    feeds: list[RSSFeed] = []
    ids: set[str] = set()
    for raw in raw_feeds:
        if not isinstance(raw, dict):
            raise ValueError("RSS registry entries must be JSON objects")
        feed = RSSFeed(**raw)
        if not feed.id or feed.id in ids:
            raise ValueError(f"RSS feed id is empty or duplicated: {feed.id!r}")
        parsed_url = urlparse(feed.url)
        if parsed_url.scheme != "https" or not parsed_url.hostname:
            raise ValueError(f"RSS feed must use an HTTPS URL: {feed.id}")
        if feed.category not in PRODUCTION_CATEGORY_ALLOWLIST:
            raise ValueError(f"RSS feed category is not allowed: {feed.category}")
        if not feed.publisher_domain or parsed_url.hostname.endswith("google.com"):
            raise ValueError(
                f"RSS feed must identify its direct publisher: {feed.id}"
            )
        if type(feed.priority) is not int or feed.priority < 1:
            raise ValueError(f"RSS feed priority must be a positive integer: {feed.id}")
        if type(feed.active) is not bool:
            raise ValueError(f"RSS feed active must be a boolean: {feed.id}")
        ids.add(feed.id)
        if feed.active:
            feeds.append(feed)

    return tuple(sorted(feeds, key=lambda feed: (feed.priority, feed.id)))
