"""DDGS client tests — deterministic (fakes) plus optional live."""

from __future__ import annotations

import sys

from core.exceptions import (
    SourceConnectionError,
    SourceParseError,
    SourceValidationError,
)
from schemas.sources import SourceResult
from sources.ddgs import DDGSClient


class _FakeDDGS:
    def __init__(self, results=None, raises=None):
        self._results = results or []
        self._raises = raises

    def text(self, *a, **k):
        if self._raises:
            raise self._raises
        return self._results

    def news(self, *a, **k):
        if self._raises:
            raise self._raises
        return self._results


def test_text_search_normalizes():
    client = DDGSClient()
    client._ddgs = _FakeDDGS([{"title": "T", "href": "https://a.com/x", "body": "B"}])
    result = client.text_search("openai")
    assert isinstance(result, SourceResult)
    assert result.items[0].url == "https://a.com/x"
    assert result.items[0].canonical_url == "https://a.com/x"


def test_news_search_parses_date_to_aware_utc():
    client = DDGSClient()
    client._ddgs = _FakeDDGS([{
        "title": "N",
        "url": "https://n.com/1",
        "body": "B",
        "source": "N",
        "date": "2026-09-24T05:03:58+00:00",
    }])
    result = client.news_search("openai")
    item = result.items[0]
    assert item.source_name == "N"
    assert item.published_at is not None
    assert item.published_at.tzinfo is not None


def test_news_search_bad_date_becomes_none():
    client = DDGSClient()
    client._ddgs = _FakeDDGS([{
        "title": "N",
        "url": "https://n.com/1",
        "date": "not-a-date",
    }])
    result = client.news_search("openai")
    assert result.items[0].published_at is None


def test_empty_results():
    client = DDGSClient()
    client._ddgs = _FakeDDGS([])
    assert client.text_search("openai").items == []


def test_malformed_result_raises():
    client = DDGSClient()
    client._ddgs = _FakeDDGS([{"no_title": True}])
    try:
        client.text_search("openai")
    except SourceParseError:
        return
    raise AssertionError("expected SourceParseError")


def test_timeout_translated():
    class DDGSTimeout(Exception):
        pass
    client = DDGSClient()
    client._ddgs = _FakeDDGS(raises=DDGSTimeout("timed out"))
    try:
        client.text_search("openai")
    except SourceConnectionError:
        return
    raise AssertionError("expected SourceConnectionError")


def test_invalid_query():
    client = DDGSClient()
    client._ddgs = _FakeDDGS([])
    try:
        client.text_search("")
    except SourceValidationError:
        return
    raise AssertionError("expected SourceValidationError")


def test_live_text():
    """LIVE — hits DuckDuckGo."""
    with DDGSClient() as client:
        result = client.text_search("OpenAI", max_results=3)
    assert result.source == "ddgs"


def test_live_news():
    """LIVE — hits DuckDuckGo news."""
    with DDGSClient() as client:
        result = client.news_search("OpenAI", max_results=3)
    assert result.source == "ddgs"


if __name__ == "__main__":
    from scripts._runner import run_module
    live = "--live" in sys.argv
    ns = {k: v for k, v in globals().items() if not (k.startswith("test_live") and not live)}
    rc = run_module(ns, title="test_ddgs")
    if not live:
        print("  (skipped live tests; pass --live to run them)")
    sys.exit(rc)