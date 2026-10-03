"""Deterministic regression checks for ingestion extraction and source handling."""
from __future__ import annotations

from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extraction.normalizers.article import extract_article  # noqa: E402
from extraction.fetchers.http import FetchResult  # noqa: E402
from schemas.sources import NewsItem  # noqa: E402
from scripts import run_news_ingestion as ingestion  # noqa: E402
from schemas.taxonomy import infer_categories_from_text  # noqa: E402
from sources.rss.client import RSSClient  # noqa: E402
from core.exceptions import SourceConnectionError  # noqa: E402


def _test_string_categories_in_rejection_metrics() -> None:
    category_text = {
        "GLOBAL_POLITICS": "The president signed new legislation after the election.",
        "ARTIFICIAL_INTELLIGENCE": (
            "OpenAI announced a new artificial intelligence model."
        ),
        "FINANCE": "The central bank cut interest rates amid inflation.",
        "WAR_CONFLICT": (
            "The military operation escalated the armed conflict."
        ),
    }
    ingestion.TAXONOMY_REJECTED.clear()
    for expected, text in category_text.items():
        inferred = infer_categories_from_text(text)
        assert all(isinstance(category, str) for category in inferred)
        assert expected in inferred
        ingestion._record_rejected_taxonomy_metrics(text)
        assert ingestion.TAXONOMY_REJECTED[expected] == 1
    print("[PASS] rejection metrics handle canonical string categories")


def _test_extraction_budget_uses_feed_priority_and_recency() -> None:
    now = datetime.now(timezone.utc).isoformat()
    older = "2026-01-01T00:00:00+00:00"
    title = "Government announces a major new climate policy"
    base_item = {
        "title": title,
        "url": "https://publisher.example.org/news/real-article",
        "description": "The government announced a climate policy today.",
        "published_at": now,
    }
    items = {
        "low_priority": [dict(base_item)],
        "high_priority": [dict(base_item)],
        "older": [{**base_item, "published_at": older}],
    }
    selected = ingestion._extraction_candidates(
        items,
        max_extracts=2,
        feed_by_id={
            "low_priority": {"priority": 8},
            "high_priority": {"priority": 1},
            "older": {"priority": 1},
        },
    )
    assert ("high_priority", 0) in selected
    assert ("low_priority", 0) in selected
    assert ("older", 0) not in selected
    print("[PASS] extraction budget prioritizes recency and RSS feed priority")


def _test_article_survives_extraction_failure_and_keeps_metadata() -> None:
    item = {
        "url": "https://publisher.example.org/politics/major-policy-announcement",
        "canonical_url": (
            "https://publisher.example.org/politics/major-policy-announcement"
        ),
        "title": "Government announces a major climate policy",
        "description": (
            "The government announced a national climate policy to cut carbon "
            "emissions by 20 percent beginning in 2027, according to officials."
        ),
        "snippet": (
            "The government announced a national climate policy to cut carbon "
            "emissions by 20 percent beginning in 2027, according to officials."
        ),
        "published_at": datetime.now(timezone.utc).isoformat(),
        "source_name": "Publisher",
        "publisher_name": "Publisher",
        "publisher_domain": "publisher.example.org",
    }
    with patch(
        "extraction.normalizers.article.extract_article",
        side_effect=RuntimeError("simulated extraction outage"),
    ):
        enriched = ingestion._enrich_article(item, "bbc")
    assert ingestion._reject_reason(enriched, "bbc") is None

    enriched["metadata"] = {
        "article_extraction": {
            "extraction_method": "newspaper4k",
            "newspaper4k": {"meta_description": "Publisher metadata"},
        },
    }
    payload = ingestion._build_news_item(
        enriched,
        "bbc",
        "test-source-id",
    )
    assert payload is not None
    extraction = payload["metadata"]["article_extraction"]
    assert extraction["extraction_method"] == "newspaper4k"
    assert extraction["newspaper4k"]["meta_description"] == "Publisher metadata"
    print("[PASS] extraction outages do not discard valid RSS metadata")


def _test_enrichment_uses_richer_newspaper_content() -> None:
    current = {
        "url": "https://publisher.example.org/science/story",
        "canonical_url": "https://publisher.example.org/science/story",
        "title": "Short RSS title",
        "description": "A useful description about scientific research.",
        "snippet": "A useful description about scientific research.",
        "content": "Short RSS excerpt.",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "source_name": "Publisher",
        "publisher_name": "Publisher",
        "publisher_domain": "publisher.example.org",
        "metadata": {"feed_priority": 2},
    }
    full_content = "A detailed article about scientific research. " * 20
    extracted = NewsItem(
        title="Full extracted article title",
        url=current["url"],
        canonical_url=current["url"],
        content=full_content,
        author="Reporter",
        published_at=datetime.now(timezone.utc),
        metadata={
            "extraction_method": "newspaper4k",
            "newspaper4k": {"meta_description": "Article metadata"},
        },
    )
    with patch(
        "extraction.normalizers.article.extract_article",
        return_value=extracted,
    ):
        enriched = ingestion._enrich_article(current, "bbc")

    assert enriched["title"] == "Full extracted article title"
    assert enriched["content"] == full_content
    assert enriched["author"] == "Reporter"
    assert enriched["publisher_name"] == "Publisher"
    assert enriched["publisher_domain"] == "publisher.example.org"
    assert enriched["metadata"]["article_extraction"]["newspaper4k"][
        "meta_description"
    ] == "Article metadata"
    print("[PASS] extracted full content and metadata enrich RSS records")


def _test_publisher_identity_uses_resolved_article_domain() -> None:
    article = {
        "url": "https://abcnews.go.com/politics/article",
        "canonical_url": "https://abcnews.go.com/politics/article",
        "title": "Government announces a major climate policy",
        "description": (
            "The government announced a national climate policy to cut carbon "
            "emissions by 20 percent beginning in 2027, according to officials."
        ),
        "snippet": (
            "The government announced a national climate policy to cut carbon "
            "emissions by 20 percent beginning in 2027, according to officials."
        ),
        "published_at": datetime.now(timezone.utc).isoformat(),
        "source_name": "Google News",
        "publisher_name": "Google News",
        "publisher_domain": "news.google.com",
    }
    payload = ingestion._build_news_item(
        article,
        "google_news",
        "test-source-id",
    )
    assert payload is not None
    assert payload["source_name"] == "abcnews.go.com"
    assert payload["source_domain"] == "abcnews.go.com"
    print("[PASS] Google News wrappers do not persist as publisher identity")


def _test_newspaper4k_fallback() -> None:
    trafilatura = ModuleType("trafilatura")
    trafilatura.extract = lambda *_args, **_kwargs: "short"
    trafilatura_metadata = ModuleType("trafilatura.metadata")
    trafilatura_metadata.extract_metadata = lambda *_args, **_kwargs: SimpleNamespace(
        title="A useful article title",
        author=None,
        date=None,
        url=None,
    )
    trafilatura.metadata = trafilatura_metadata

    class FakeArticle:
        def __init__(self, *_args, **_kwargs) -> None:
            self.text = ""
            self.title = "Newspaper4k article title"
            self.authors = ["Reporter"]
            self.publish_date = datetime(2026, 10, 2, tzinfo=timezone.utc)
            self.meta_data = {"og:type": "article"}
            self.meta_description = "A newspaper metadata description"
            self.meta_keywords = ["news", "science"]
            self.keywords = {"science"}
            self.tags = {"research"}

        def set_html(self, _html: str) -> None:
            pass

        def parse(self) -> None:
            self.text = (
                "A verified scientific article body with enough useful detail. "
                * 12
            )

    newspaper = ModuleType("newspaper")
    newspaper.Article = FakeArticle

    class FakeFetcher:
        def fetch(self, url: str) -> FetchResult:
            return FetchResult(
                url=url,
                final_url=url,
                status_code=200,
                content_type="text/html",
                text="<html><body><p>article</p></body></html>",
            )

    with patch.dict(
        sys.modules,
        {
            "trafilatura": trafilatura,
            "trafilatura.metadata": trafilatura_metadata,
            "newspaper": newspaper,
        },
    ):
        result = extract_article(
            "https://publisher.example.org/article",
            fetcher=FakeFetcher(),
        )

    assert result.metadata["extraction_method"] == "newspaper4k"
    assert result.title == "Newspaper4k article title"
    assert result.author == "Reporter"
    assert len(result.content or "") > 200
    assert result.metadata["newspaper4k"]["meta_data"]["og:type"] == "article"
    assert result.metadata["newspaper4k"]["keywords"] == ["science"]
    print("[PASS] Newspaper4k supplies article content and metadata fallback")


def _test_rss_redirect_and_transient_retry() -> None:
    requested: list[str] = []
    feed_xml = b"""<?xml version="1.0"?>
    <rss><channel><title>Publisher</title><item>
    <title>Publisher reports a significant new development</title>
    <link>https://publisher.example.org/story</link>
    </item></channel></rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if len(requested) == 1:
            raise httpx.ConnectError("temporary connection reset", request=request)
        if str(request.url) == "https://feeds.example.org/rss":
            return httpx.Response(
                301,
                headers={"Location": "https://feeds.example.org/current"},
                request=request,
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "application/rss+xml"},
            content=feed_xml,
            request=request,
        )

    client = RSSClient(timeout=1)
    assert client._client.follow_redirects is True
    client._client.close()
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    )
    try:
        result = client.fetch("https://feeds.example.org/rss")
    finally:
        client.close()

    assert result.items
    assert requested.count("https://feeds.example.org/rss") == 2
    assert "https://feeds.example.org/current" in requested
    print("[PASS] RSS client retries transient errors and follows redirects")

    failed_requests = 0

    def not_found(request: httpx.Request) -> httpx.Response:
        nonlocal failed_requests
        failed_requests += 1
        return httpx.Response(404, request=request)

    client = RSSClient(timeout=1)
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(not_found))
    try:
        try:
            client.fetch("https://feeds.example.org/missing")
        except SourceConnectionError as exc:
            assert "HTTP 404" in str(exc)
        else:
            raise AssertionError("HTTP 404 did not fail")
    finally:
        client.close()
    assert failed_requests == 1
    print("[PASS] RSS client does not retry permanent HTTP errors")


def main() -> None:
    _test_string_categories_in_rejection_metrics()
    _test_extraction_budget_uses_feed_priority_and_recency()
    _test_article_survives_extraction_failure_and_keeps_metadata()
    _test_enrichment_uses_richer_newspaper_content()
    _test_publisher_identity_uses_resolved_article_domain()
    _test_newspaper4k_fallback()
    _test_rss_redirect_and_transient_retry()
    print("All ingestion resilience checks passed")


if __name__ == "__main__":
    main()
