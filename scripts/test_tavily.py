"""Tavily client tests — deterministic (fakes) plus optional live."""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

from core.exceptions import (
    SourceAuthenticationError,
    SourceRateLimitError,
    SourceValidationError,
)
from sources.tavily import TavilyClient


class _FakeTavily:
    def __init__(self, search_response=None, extract_response=None, raises=None):
        self._search = search_response or {"results": []}
        self._extract = extract_response or {"results": []}
        self._raises = raises

    def search(self, **kwargs):
        if self._raises:
            raise self._raises
        return self._search

    def extract(self, **kwargs):
        if self._raises:
            raise self._raises
        return self._extract


class _FakeInvalidAPIKeyError(Exception):
    pass
_FakeInvalidAPIKeyError.__module__ = "tavily.errors"


class _FakeUsageLimitExceededError(Exception):
    pass
_FakeUsageLimitExceededError.__module__ = "tavily.errors"


def _client_with(fake):
    with patch("sources.tavily.client._TavilyAPIClient", return_value=fake):
        return TavilyClient(api_key="test")


def test_search_normalizes():
    fake = _FakeTavily(search_response={
        "results": [{"title": "T", "url": "https://a.com/x", "content": "c", "score": 0.9}],
    })
    client = _client_with(fake)
    result = client.search("openai")
    assert result.items[0].url == "https://a.com/x"


def test_extract_normalizes():
    fake = _FakeTavily(extract_response={
        "results": [{"url": "https://a.com/x", "raw_content": "hello"}],
    })
    client = _client_with(fake)
    result = client.extract(["https://a.com/x"])
    assert result.items[0].content == "hello"


def test_missing_api_key_raises_auth():
    os.environ.pop("TAVILY_API_KEY", None)
    try:
        TavilyClient(api_key=None)
    except SourceAuthenticationError:
        return
    raise AssertionError("expected SourceAuthenticationError")


def test_structured_auth_error_translated():
    client = _client_with(_FakeTavily(raises=_FakeInvalidAPIKeyError("bad key")))
    try:
        client.search("x")
    except SourceAuthenticationError:
        return
    raise AssertionError("expected SourceAuthenticationError")


def test_structured_rate_limit_translated():
    client = _client_with(_FakeTavily(raises=_FakeUsageLimitExceededError("quota")))
    try:
        client.search("x")
    except SourceRateLimitError:
        return
    raise AssertionError("expected SourceRateLimitError")


def test_invalid_query():
    client = _client_with(_FakeTavily())
    try:
        client.search("")
    except SourceValidationError:
        return
    raise AssertionError("expected SourceValidationError")


def test_live_search():
    """LIVE — requires TAVILY_API_KEY."""
    if not os.getenv("TAVILY_API_KEY"):
        print("    SKIPPED — TAVILY_API_KEY not configured")
        return
    with TavilyClient() as client:
        result = client.search("OpenAI", max_results=3, topic="news")
    assert result.source == "tavily"


def test_live_extract():
    """LIVE — requires TAVILY_API_KEY."""
    if not os.getenv("TAVILY_API_KEY"):
        print("    SKIPPED — TAVILY_API_KEY not configured")
        return
    with TavilyClient() as client:
        result = client.extract(["https://example.com"])
    assert result.source == "tavily"


if __name__ == "__main__":
    from scripts._runner import run_module
    live = "--live" in sys.argv
    ns = {k: v for k, v in globals().items() if not (k.startswith("test_live") and not live)}
    rc = run_module(ns, title="test_tavily")
    if not live:
        print("  (skipped live tests; pass --live to run them)")
    sys.exit(rc)