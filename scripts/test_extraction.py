"""Extraction pipeline tests — deterministic plus optional live."""

from __future__ import annotations

import sys
from unittest.mock import patch

import httpx

from extraction.canonicalization.url import canonicalize_url, dedupe_urls
from extraction.cleaners.text import clean_text
from extraction.normalizers.article import extract_article
from extraction.parsers.html import parse_html


def test_canonicalize_strips_tracking_and_sorts_query():
    got = canonicalize_url("HTTPS://Example.com:443/Path/?utm_source=x&b=2&a=1#frag")
    assert got == "https://example.com/Path?a=1&b=2"


def test_canonicalize_invalid():
    assert canonicalize_url("not a url") is None
    assert canonicalize_url("") is None


def test_dedupe_urls():
    urls = ["https://a.com/x?utm_source=1", "https://a.com/x", "https://b.com/y"]
    assert dedupe_urls(urls) == ["https://a.com/x", "https://b.com/y"]


def test_clean_text():
    assert clean_text("hello   world\n\n\n\nbye") == "hello world\n\nbye"


def test_parse_html_basic():
    html = """
    <html><head><title>Title</title>
      <meta property="og:title" content="OG Title"/>
      <meta property="article:published_time" content="2026-09-24T00:00:00Z"/>
    </head>
    <body>
      <nav>menu</nav>
      <article>
        <h1>Headline</h1>
        <p>First paragraph long enough to be counted as content by the heuristic.</p>
        <p>Second paragraph with additional detail.</p>
      </article>
      <footer>footer</footer>
    </body></html>
    """
    parsed = parse_html(html, url="https://a.com/x")
    assert parsed.title == "OG Title"
    assert "First paragraph" in parsed.text
    assert "menu" not in parsed.text
    assert "footer" not in parsed.text


def test_extract_article_rejects_non_html():
    fake_response = httpx.Response(
        status_code=200,
        headers={"Content-Type": "application/pdf"},
        content=b"%PDF-1.4",
        request=httpx.Request("GET", "https://a.com/x.pdf"),
    )
    with patch("httpx.Client.get", return_value=fake_response):
        try:
            extract_article("https://a.com/x.pdf")
        except Exception as exc:
            assert "Unsupported content type" in str(exc)
            return
    raise AssertionError("expected SourceParseError")


def test_live_extract_wikipedia():
    """LIVE — fetches Wikipedia."""
    item = extract_article("https://en.wikipedia.org/wiki/OpenAI")
    assert item.url
    assert item.content and len(item.content) > 500
    assert item.canonical_url


if __name__ == "__main__":
    from scripts._runner import run_module
    live = "--live" in sys.argv
    ns = {k: v for k, v in globals().items() if not (k.startswith("test_live") and not live)}
    rc = run_module(ns, title="test_extraction")
    if not live:
        print("  (skipped live tests; pass --live to run them)")
    sys.exit(rc)