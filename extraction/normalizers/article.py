"""End-to-end URL → normalized article pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from core.exceptions import SourceConnectionError, SourceError, SourceParseError
from extraction.canonicalization.url import canonicalize_url
from extraction.cleaners.text import clean_text
from extraction.fetchers.http import HTTPFetcher
from extraction.fetchers.resolvers import (
    is_google_news_redirect,
    resolve_google_news_url,
)
from extraction.parsers.html import parse_html
from schemas.sources import NewsItem


def _parse_iso_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        v = value.replace("Z", "+00:00")
        return datetime.fromisoformat(v)
    except Exception:
        return None


def extract_article(
    url: str,
    *,
    fetcher: Optional[HTTPFetcher] = None,
) -> NewsItem:
    """Fetch, parse, clean and normalize a single URL into a NewsItem.

    If ``url`` is a Google News RSS wrapper URL, it is first resolved to the
    underlying publisher URL. If resolution fails, extraction proceeds against
    the original URL so the caller still gets a structured NewsItem (possibly
    with empty content).
    """
    original_url = url
    resolved_url = url
    resolver_error: Optional[str] = None

    if is_google_news_redirect(url):
        try:
            resolved_url = resolve_google_news_url(url)
        except SourceError as exc:
            resolver_error = str(exc)
            resolved_url = url

    owns_fetcher = fetcher is None
    fetcher = fetcher or HTTPFetcher()
    try:
        result = fetcher.fetch(resolved_url)
    finally:
        if owns_fetcher:
            fetcher.close()

    # Guard: only HTML/XHTML/text documents.
    ctype = (result.content_type or "").lower()
    if ctype and not any(k in ctype for k in ("html", "xml", "text/")):
        raise SourceParseError(
            f"Unsupported content type for article extraction: {ctype}",
            source="extraction",
            operation="extract",
            url=result.final_url,
            content_type=ctype,
        )

    try:
        parsed = parse_html(result.text, url=result.final_url)
    except Exception as exc:
        raise SourceParseError(
            f"Failed to parse HTML: {exc}",
            source="extraction",
            operation="extract",
            url=result.final_url,
            payload_size=len(result.text or ""),
            cause=exc,
        ) from exc

    canonical = canonicalize_url(parsed.canonical_url or result.final_url or resolved_url)

    return NewsItem(
        title=parsed.title or resolved_url,
        url=result.final_url or resolved_url,
        canonical_url=canonical,
        content=clean_text(parsed.text),
        author=parsed.author,
        published_at=_parse_iso_date(parsed.published_at),
        language=parsed.language,
        discovered_at=datetime.now(timezone.utc),
        metadata={
            "original_url": original_url,
            "resolved_url": resolved_url,
            "resolver_error": resolver_error,
            "http_status": result.status_code,
            "content_type": result.content_type,
            "raw_title": parsed.title,
            "canonical_from_html": parsed.canonical_url,
        },
    )