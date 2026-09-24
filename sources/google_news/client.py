"""Google News adapter over the generic RSS infrastructure."""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import urlencode

from core.exceptions import SourceValidationError
from schemas.sources import SourceResult
from sources.rss.client import RSSClient

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


class GoogleNewsClient:
    """Search Google News via its RSS endpoint."""

    def __init__(
        self,
        timeout: float = 30.0,
        hl: str = "en-US",
        gl: str = "US",
        ceid: str = "US:en",
        rss_client: Optional[RSSClient] = None,
    ) -> None:
        self.hl = hl
        self.gl = gl
        self.ceid = ceid
        self._rss = rss_client or RSSClient(timeout=timeout)

    def search(
        self,
        query: str,
        max_results: int = 10,
        domains: Optional[List[str]] = None,
        language: Optional[str] = None,
        country: Optional[str] = None,
    ) -> SourceResult:
        if not query or not query.strip():
            raise SourceValidationError(
                "query must be a non-empty string",
                source="google_news",
                operation="search",
                parameter="query",
                value=query,
            )
        if max_results <= 0:
            raise SourceValidationError(
                "max_results must be > 0",
                source="google_news",
                operation="search",
                parameter="max_results",
                value=max_results,
                expected="positive integer",
            )

        q = query.strip()
        if domains:
            site_filter = " OR ".join(f"site:{d.strip()}" for d in domains if d.strip())
            if site_filter:
                q = f"({q}) ({site_filter})"

        params = {
            "q": q,
            "hl": language or self.hl,
            "gl": country or self.gl,
            "ceid": self.ceid,
        }
        url = f"{GOOGLE_NEWS_RSS}?{urlencode(params)}"
        rss_result = self._rss.fetch(url)
        items = rss_result.items[:max_results]
        return SourceResult(
            source="google_news",
            source_type="rss",
            query=query,
            items=items,
        )

    def close(self) -> None:
        self._rss.close()

    def __enter__(self) -> "GoogleNewsClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()