"""Deterministic tests for the generic RSS parser."""

from __future__ import annotations

from datetime import timezone

from schemas.sources import NewsItem
from sources.rss.parser import parse_feed

SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>Headline One</title>
      <link>https://example.com/a?utm_source=x</link>
      <description>Summary of one.</description>
      <pubDate>Wed, 24 Sep 2026 12:00:00 GMT</pubDate>
      <guid>tag:example.com,2026:a</guid>
    </item>
    <item>
      <title>Headline Two</title>
      <link>https://example.com/b</link>
      <pubDate>Wed, 24 Sep 2026 13:30:00 +0200</pubDate>
    </item>
  </channel>
</rss>
"""

BROKEN_RSS = b"this is not rss at all"


def test_success():
    items = parse_feed(SAMPLE_RSS, source_name="example")
    assert len(items) == 2
    assert all(isinstance(i, NewsItem) for i in items)
    first = items[0]
    assert first.title == "Headline One"
    assert first.canonical_url == "https://example.com/a"
    assert first.id == "tag:example.com,2026:a"


def test_timestamps_aware_utc():
    items = parse_feed(SAMPLE_RSS, source_name="example")
    for item in items:
        assert item.published_at is not None
        assert item.published_at.tzinfo is not None
        assert item.published_at.utcoffset().total_seconds() == 0


def test_id_deterministic_when_missing():
    items = parse_feed(SAMPLE_RSS, source_name="example")
    second = items[1]  # no guid in feed
    assert second.id is not None
    again = parse_feed(SAMPLE_RSS, source_name="example")[1]
    assert second.id == again.id


def test_malformed_feed_raises():
    from core.exceptions import SourceParseError
    try:
        parse_feed(BROKEN_RSS, source_name="broken")
    except SourceParseError:
        return
    raise AssertionError("expected SourceParseError")


if __name__ == "__main__":
    import sys
    from scripts._runner import run_module
    sys.exit(run_module(globals(), title="test_rss"))