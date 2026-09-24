"""DDGS (DuckDuckGo Search) client — text and news search."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from core.exceptions import (
    SourceConnectionError,
    SourceParseError,
    SourceRateLimitError,
    SourceTimeoutError,
    SourceValidationError,
)
from extraction.canonicalization.url import canonicalize_url
from schemas.sources import NewsItem, SourceResult

try:  # current package name
    from ddgs import DDGS  # type: ignore
except Exception as exc:  # pragma: no cover
    raise ImportError(
        "The 'ddgs' package is required. Install with: pip install ddgs"
    ) from exc


def _parse_date(value: Any) -> Optional[datetime]:
    """Best-effort parse of DDGS date strings to timezone-aware UTC.

    DDGS providers return dates in several formats (ISO 8601, date-only,
    occasionally relative). We accept what we can and return ``None`` for
    anything unparseable. Never fabricate a timestamp.
    """
    if value is None:
        return None

    # Already a datetime.
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    if not isinstance(value, str):
        return None

    s = value.strip()
    if not s:
        return None

    # ISO 8601, with or without offset / Z.
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass

    # Common date-only and human-readable formats.
    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d %b %Y",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue

    return None


def _translate_exception(exc: BaseException, operation: str) -> Exception:
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return SourceTimeoutError(
            f"DDGS {operation} timed out",
            source="ddgs",
            operation=operation,
            cause=exc,
        )
    if "rate" in name and "limit" in name:
        return SourceRateLimitError(
            f"DDGS {operation} rate-limited",
            source="ddgs",
            operation=operation,
            cause=exc,
        )
    return SourceConnectionError(
        f"DDGS {operation} failed: {exc}",
        source="ddgs",
        operation=operation,
        cause=exc,
    )


class DDGSClient:
    """Thin wrapper around the ``ddgs`` package.

    The backend rotates between third-party search providers (Brave, Bing,
    etc.). Under transient congestion any of them can be slow; the
    ``timeout`` parameter lets the caller tune how long to wait before the
    client fails with a structured ``SourceTimeoutError``.
    """

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout
        self._ddgs: Optional[DDGS] = None

    def _backend(self) -> DDGS:
        if self._ddgs is None:
            try:
                # Recent ddgs versions accept ``timeout`` in the constructor.
                self._ddgs = DDGS(timeout=self.timeout)
            except TypeError:
                # Older versions do not; fall back to default behaviour.
                self._ddgs = DDGS()
        return self._ddgs

    # --- text -----------------------------------------------------------

    def text_search(
        self,
        query: str,
        max_results: int = 10,
        region: str = "us-en",
        safesearch: str = "moderate",
        timelimit: Optional[str] = None,
        domains: Optional[List[str]] = None,
    ) -> SourceResult:
        return self._search(
            kind="text",
            query=query,
            max_results=max_results,
            region=region,
            safesearch=safesearch,
            timelimit=timelimit,
            domains=domains,
        )

    def news_search(
        self,
        query: str,
        max_results: int = 10,
        region: str = "us-en",
        safesearch: str = "moderate",
        timelimit: Optional[str] = None,
        domains: Optional[List[str]] = None,
    ) -> SourceResult:
        return self._search(
            kind="news",
            query=query,
            max_results=max_results,
            region=region,
            safesearch=safesearch,
            timelimit=timelimit,
            domains=domains,
        )

    # --- shared ---------------------------------------------------------

    def _search(
        self,
        *,
        kind: str,
        query: str,
        max_results: int,
        region: str,
        safesearch: str,
        timelimit: Optional[str],
        domains: Optional[List[str]],
    ) -> SourceResult:
        if not query or not query.strip():
            raise SourceValidationError(
                "query must be a non-empty string",
                source="ddgs",
                operation=kind,
                parameter="query",
                value=query,
            )
        if max_results <= 0:
            raise SourceValidationError(
                "max_results must be > 0",
                source="ddgs",
                operation=kind,
                parameter="max_results",
                value=max_results,
            )

        q = query.strip()
        if domains:
            domain_clause = " OR ".join(f"site:{d.strip()}" for d in domains if d.strip())
            if domain_clause:
                q = f"{q} ({domain_clause})"

        backend = self._backend()
        kwargs: dict[str, Any] = {
            "region": region,
            "safesearch": safesearch,
            "max_results": max_results,
        }
        if timelimit:
            kwargs["timelimit"] = timelimit

        try:
            if kind == "text":
                raw_results = backend.text(q, **kwargs)
            else:
                raw_results = backend.news(q, **kwargs)
        except Exception as exc:
            raise _translate_exception(exc, kind) from exc

        if raw_results is None:
            raw_results = []

        items: List[NewsItem] = []
        for raw in raw_results:
            try:
                items.append(self._normalize(raw, kind))
            except Exception as exc:
                raise SourceParseError(
                    f"Malformed DDGS {kind} result",
                    source="ddgs",
                    operation=kind,
                    context={
                        "raw_keys": list(raw.keys()) if isinstance(raw, dict) else None,
                    },
                    cause=exc,
                ) from exc

        return SourceResult(source="ddgs", source_type="api", query=query, items=items)

    def _normalize(self, raw: dict, kind: str) -> NewsItem:
        if not isinstance(raw, dict):
            raise ValueError("raw result must be a dict")

        if kind == "text":
            url = raw.get("href") or raw.get("url") or ""
            title = raw.get("title") or ""
            snippet = raw.get("body") or raw.get("snippet")
            published_at = None
            source_name = None
        else:
            url = raw.get("url") or raw.get("href") or ""
            title = raw.get("title") or ""
            snippet = raw.get("body") or raw.get("excerpt")
            source_name = raw.get("source")
            # Parse the date; never pass a raw string into published_at.
            published_at = _parse_date(raw.get("date"))

        if not url or not title:
            raise ValueError("result missing url or title")

        return NewsItem(
            title=title,
            url=url,
            canonical_url=canonicalize_url(url),
            description=snippet,
            snippet=snippet,
            source_name=source_name,
            published_at=published_at,
            metadata={"ddgs_kind": kind, "raw": raw},
        )

    def close(self) -> None:
        # ddgs does not expose a close(); kept for API symmetry.
        self._ddgs = None

    def __enter__(self) -> "DDGSClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()