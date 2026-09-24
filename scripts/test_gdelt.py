"""GDELT tests — deterministic (mocked) plus optional live.

Run deterministic:  python -m scripts.test_gdelt
Run with live:      python -m scripts.test_gdelt --live
"""

from __future__ import annotations

import json
import sys
from unittest.mock import patch

import httpx

from core.exceptions import (
    SourceConnectionError,
    SourceParseError,
    SourceRateLimitError,
    SourceValidationError,
)
from sources.gdelt import GDELTClient

SAMPLE = {
    "articles": [
        {
            "url": "https://example.com/a?utm_source=x",
            "title": "Example headline",
            "seendate": "20260924T120000Z",
            "domain": "example.com",
            "language": "English",
            "sourcecountry": "United States",
            "socialimage": "https://example.com/img.jpg",
        }
    ]
}

_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def _resp(status=200, text="", headers=None):
    return httpx.Response(
        status_code=status,
        text=text,
        headers=headers or {},
        request=httpx.Request("GET", _API_URL),
    )


def test_success_normalizes_without_fabricated_description():
    with patch.object(httpx.Client, "get", return_value=_resp(text=json.dumps(SAMPLE))):
        client = GDELTClient()
        result = client.search("anything", max_results=5)

    assert result.source == "gdelt"
    assert len(result.items) == 1
    item = result.items[0]
    assert item.title == "Example headline"
    assert item.canonical_url == "https://example.com/a"
    assert item.source_domain == "example.com"
    # Spec §16: description must not be fabricated from socialimage.
    assert item.description is None
    assert item.metadata["gdelt"]["socialimage"] == "https://example.com/img.jpg"
    assert item.published_at is not None
    assert item.published_at.tzinfo is not None


def test_empty_body_is_valid_empty():
    with patch.object(httpx.Client, "get", return_value=_resp(text="")):
        client = GDELTClient()
        result = client.search("nothing")
    assert result.items == []


def test_plaintext_error_body_raises_parse_error():
    with patch.object(httpx.Client, "get", return_value=_resp(text="<html>bad query</html>")):
        client = GDELTClient()
        try:
            client.search("bad")
        except SourceParseError:
            return
    raise AssertionError("expected SourceParseError")


def test_timeout_translated():
    with patch.object(httpx.Client, "get", side_effect=httpx.TimeoutException("t")):
        client = GDELTClient()
        try:
            client.search("x")
        except SourceConnectionError:
            return
    raise AssertionError("expected SourceConnectionError")


def test_network_error_translated():
    with patch.object(httpx.Client, "get", side_effect=httpx.ConnectError("nope")):
        client = GDELTClient()
        try:
            client.search("x")
        except SourceConnectionError:
            return
    raise AssertionError("expected SourceConnectionError")


def test_rate_limit_translated():
    with patch.object(
        httpx.Client, "get",
        return_value=_resp(status=429, headers={"Retry-After": "5"}),
    ):
        client = GDELTClient()
        client.max_attempts = 1  # skip retries in deterministic test
        try:
            client.search("x")
        except SourceRateLimitError as exc:
            assert exc.status_code == 429
            return
    raise AssertionError("expected SourceRateLimitError")


def test_invalid_params():
    client = GDELTClient()
    for kwargs in ({}, {"max_results": 0}, {"max_results": 1000}):
        try:
            client.search(kwargs.pop("query", ""), **kwargs)
        except SourceValidationError:
            continue
        raise AssertionError("expected SourceValidationError")


def test_live_search():
    """LIVE — hits api.gdeltproject.org. May 429."""
    with GDELTClient() as client:
        result = client.search("OpenAI", max_results=3, timespan="7d")
    assert result.source == "gdelt"


if __name__ == "__main__":
    from scripts._runner import run_module
    live = "--live" in sys.argv
    ns = {k: v for k, v in globals().items() if not (k == "test_live_search" and not live)}
    rc = run_module(ns, title="test_gdelt")
    if not live:
        print("  (skipped live tests; pass --live to run them)")
    sys.exit(rc)