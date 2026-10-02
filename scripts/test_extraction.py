"""Extraction pipeline tests — deterministic plus optional live."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import SimpleNamespace
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


def test_extract_article_prefers_trafilatura():
    url = "https://example.com/article"
    response = SimpleNamespace(
        text="<html><body><article>Article</article></body></html>",
        final_url=url,
        status_code=200,
        content_type="text/html",
    )
    fetcher = SimpleNamespace(fetch=lambda _url: response)
    extracted_text = "A verified article paragraph with useful details. " * 8
    metadata = SimpleNamespace(
        title="Example article",
        author="Reporter",
        date=None,
        url=url,
    )
    with (
        patch("trafilatura.extract", return_value=extracted_text),
        patch("trafilatura.metadata.extract_metadata", return_value=metadata),
        patch("newspaper.Article") as newspaper_article,
    ):
        item = extract_article(url, fetcher=fetcher)
    assert item.content == clean_text(extracted_text)
    assert item.metadata["extraction_method"] == "trafilatura"
    newspaper_article.assert_not_called()


def test_extract_article_uses_newspaper_before_html_parser():
    url = "https://example.com/article"
    response = SimpleNamespace(
        text="<html><body><article>Article</article></body></html>",
        final_url=url,
        status_code=200,
        content_type="text/html",
    )
    fetcher = SimpleNamespace(fetch=lambda _url: response)
    newspaper_text = "A longer publisher article body with reported details. " * 8

    class FakeArticle:
        def __init__(self, *_args, **_kwargs):
            self.text = ""
            self.title = "Example article"
            self.authors = ["Reporter"]
            self.publish_date = datetime.now(timezone.utc)

        def set_html(self, _html):
            pass

        def parse(self):
            self.text = newspaper_text

    with (
        patch("trafilatura.extract", return_value="short"),
        patch("trafilatura.metadata.extract_metadata", return_value=None),
        patch("newspaper.Article", FakeArticle),
        patch("extraction.normalizers.article.parse_html") as html_parser,
    ):
        item = extract_article(url, fetcher=fetcher)
    assert item.content == clean_text(newspaper_text)
    assert item.metadata["extraction_method"] == "newspaper4k"
    html_parser.assert_not_called()


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