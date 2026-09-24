"""Google News adapter tests — deterministic (mocked) plus optional live."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

from core.exceptions import SourceValidationError
from schemas.sources import NewsItem, SourceResult
from sources.google_news import GoogleNewsClient


def test_search_builds_url_and_normalizes():
    fake_rss = MagicMock()
    fake_rss.fetch.return_value = SourceResult(
        source="rss",
        source_type="rss",
        items=[NewsItem(title="T", url="https://news.example/a")],
    )
    client = GoogleNewsClient(rss_client=fake_rss)
    result = client.search("openai", max_results=3, domains=["cnn.com"])

    called_url = fake_rss.fetch.call_args.args[0]
    assert "news.google.com/rss/search" in called_url
    assert "site%3Acnn.com" in called_url or "site:cnn.com" in called_url
    assert result.source == "google_news"
    assert len(result.items) == 1


def test_empty_query_rejected():
    client = GoogleNewsClient(rss_client=MagicMock())
    try:
        client.search("")
    except SourceValidationError:
        return
    raise AssertionError("expected SourceValidationError")


def test_zero_max_results_rejected():
    client = GoogleNewsClient(rss_client=MagicMock())
    try:
        client.search("x", max_results=0)
    except SourceValidationError:
        return
    raise AssertionError("expected SourceValidationError")


def test_live_search():
    """LIVE — hits news.google.com."""
    with GoogleNewsClient() as client:
        result = client.search("OpenAI", max_results=5)
    assert result.source == "google_news"
    assert len(result.items) > 0


def test_live_publisher_restricted():
    """LIVE — publisher-restricted search."""
    with GoogleNewsClient() as client:
        result = client.search("announcement", max_results=5, domains=["cnn.com"])
    # Titles should reference CNN; URLs are gnews wrappers by design.
    assert result.source == "google_news"


if __name__ == "__main__":
    from scripts._runner import run_module
    live = "--live" in sys.argv
    ns = {k: v for k, v in globals().items() if not (k.startswith("test_live") and not live)}
    rc = run_module(ns, title="test_google_news")
    if not live:
        print("  (skipped live tests; pass --live to run them)")
    sys.exit(rc)