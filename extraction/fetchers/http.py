"""Generic HTTP fetcher with retries and safe defaults."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import httpx

from core.exceptions import (
    SourceConnectionError,
    SourceTimeoutError,
    SourceValidationError,
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; InsightfullNote/0.1; +https://example.local)"
)


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content_type: Optional[str]
    text: str


class HTTPFetcher:
    """Fetch an HTTP document with bounded retries."""

    def __init__(
        self,
        timeout: float = 30.0,
        user_agent: str = DEFAULT_USER_AGENT,
        max_retries: int = 2,
        backoff: float = 0.5,
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_retries = max_retries
        self.backoff = backoff
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    def fetch(self, url: str) -> FetchResult:
        if not url or not url.startswith(("http://", "https://")):
            raise SourceValidationError(
                "url must be a valid http(s) URL",
                source="http",
                operation="fetch",
                parameter="url",
                value=url,
            )

        last_exc: Optional[BaseException] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.get(url)
                response.raise_for_status()
                return FetchResult(
                    url=url,
                    final_url=str(response.url),
                    status_code=response.status_code,
                    content_type=response.headers.get("Content-Type"),
                    text=response.text,
                )
            except httpx.TimeoutException as exc:
                last_exc = exc
            except httpx.HTTPStatusError as exc:
                # Do not retry 4xx.
                if 400 <= exc.response.status_code < 500:
                    raise SourceConnectionError(
                        f"HTTP {exc.response.status_code} fetching {url}",
                        source="http",
                        operation="fetch",
                        url=url,
                        status_code=exc.response.status_code,
                        cause=exc,
                    ) from exc
                last_exc = exc
            except httpx.RequestError as exc:
                last_exc = exc

            if attempt < self.max_retries:
                time.sleep(self.backoff * (2 ** attempt))

        if isinstance(last_exc, httpx.TimeoutException):
            raise SourceTimeoutError(
                f"Timeout fetching {url}",
                source="http",
                operation="fetch",
                url=url,
                timeout=self.timeout,
                cause=last_exc,
            )
        raise SourceConnectionError(
            f"Failed to fetch {url}: {last_exc}",
            source="http",
            operation="fetch",
            url=url,
            cause=last_exc,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HTTPFetcher":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()