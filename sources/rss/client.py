"""Generic HTTP client for RSS/Atom feeds."""

from typing import Optional

import httpx

from core.exceptions import (
    SourceConnectionError,
    SourceParseError,
    SourceValidationError,
)
from schemas.sources import SourceResult
from .parser import parse_feed


class RSSClient:
    """Fetch and parse RSS/Atom feeds."""

    def __init__(
        self,
        timeout: float = 30.0,
        user_agent: Optional[str] = None,
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent or "InsightfullNote/0.1 RSS Client"
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": self.user_agent},
        )

    def fetch(self, feed_url: str) -> SourceResult:
        """Fetch a feed URL and return a normalized SourceResult."""
        if not feed_url or not feed_url.startswith(("http://", "https://")):
            raise SourceValidationError(f"Invalid feed URL: {feed_url}")

        try:
            response = self._client.get(feed_url)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise SourceConnectionError(
                f"Timeout fetching {feed_url}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise SourceConnectionError(
                f"HTTP {exc.response.status_code} fetching {feed_url}"
            ) from exc
        except httpx.RequestError as exc:
            raise SourceConnectionError(
                f"Network error fetching {feed_url}: {exc}"
            ) from exc

        try:
            items = parse_feed(response.content, source_name=feed_url)
        except Exception as exc:
            raise SourceParseError(
                f"Failed to parse feed {feed_url}: {exc}"
            ) from exc

        return SourceResult(
            source=feed_url,
            source_type="rss",
            query=None,
            items=items,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RSSClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()