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

    text = ""
    title: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[str] = None
    canonical_url: Optional[str] = None
    language: Optional[str] = None
    extraction_method = "empty"
    fallback_errors: list[str] = []

    try:
        import trafilatura
        from trafilatura import metadata as trafilatura_metadata

        extracted_text = trafilatura.extract(
            result.text,
            url=result.final_url,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
        extracted_metadata = trafilatura_metadata.extract_metadata(
            result.text,
            url=result.final_url,
        )
        if extracted_text:
            text = clean_text(extracted_text)
            if text:
                extraction_method = "trafilatura"
        if extracted_metadata:
            title = extracted_metadata.title
            author = extracted_metadata.author
            published_at = extracted_metadata.date
            canonical_url = extracted_metadata.url
    except ImportError as exc:
        fallback_errors.append(f"trafilatura unavailable: {exc}")
    except Exception as exc:
        fallback_errors.append(f"trafilatura failed: {type(exc).__name__}: {exc}")

    if len(text) < 200:
        try:
            from newspaper import Article

            article = Article(result.final_url, language="en")
            article.set_html(result.text)
            article.parse()
            newspaper_text = clean_text(article.text or "")
            if len(newspaper_text) > len(text):
                text = newspaper_text
                extraction_method = "newspaper4k"
            title = title or article.title or None
            author = author or ", ".join(article.authors) or None
            published_at = published_at or (
                article.publish_date.isoformat() if article.publish_date else None
            )
        except ImportError as exc:
            fallback_errors.append(f"newspaper4k unavailable: {exc}")
        except Exception as exc:
            fallback_errors.append(f"newspaper4k failed: {type(exc).__name__}: {exc}")

    if len(text) < 200:
        try:
            parsed = parse_html(result.text, url=result.final_url)
            parser_text = clean_text(parsed.text)
            if len(parser_text) > len(text):
                text = parser_text
                extraction_method = "html_parser"
            title = title or parsed.title
            author = author or parsed.author
            published_at = published_at or parsed.published_at
            canonical_url = canonical_url or parsed.canonical_url
            language = parsed.language
        except Exception as exc:
            fallback_errors.append(
                f"HTML parser failed: {type(exc).__name__}: {exc}"
            )

    canonical = canonicalize_url(canonical_url or result.final_url or resolved_url)

    return NewsItem(
        title=title or resolved_url,
        url=result.final_url or resolved_url,
        canonical_url=canonical,
        content=text,
        author=author,
        published_at=_parse_iso_date(published_at),
        language=language,
        discovered_at=datetime.now(timezone.utc),
        metadata={
            "original_url": original_url,
            "resolved_url": resolved_url,
            "resolver_error": resolver_error,
            "http_status": result.status_code,
            "content_type": result.content_type,
            "raw_title": title,
            "canonical_from_html": canonical_url,
            "extraction_method": extraction_method,
            "fallback_errors": fallback_errors,
        },
    )