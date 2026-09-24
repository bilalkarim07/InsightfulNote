"""GDELT DOC 2.0 client for news/document discovery."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse, urlencode

import httpx

from core.exceptions import (
    SourceConnectionError,
    SourceParseError,
    SourceRateLimitError,
    SourceTimeoutError,
    SourceValidationError,
)
from extraction.canonicalization.url import canonicalize_url
from schemas.sources import NewsItem, SourceResult

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"


def _parse_seendate(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # e.g. 20240115T120000Z
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class GDELTClient:
    """Minimal GDELT client supporting ``search()``."""

    #: Number of HTTP attempts per search call (includes the first try).
    max_attempts: int = 3
    #: Base backoff in seconds; multiplied by the attempt number on 429/5xx/network.
    backoff_base: float = 5.0

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "InsightfullNote/0.1 GDELT Client"},
        )

    def search(
        self,
        query: str,
        max_results: int = 10,
        timespan: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        language: Optional[str] = None,
        country: Optional[str] = None,
        domains: Optional[List[str]] = None,
    ) -> SourceResult:
        if not query or not query.strip():
            raise SourceValidationError(
                "query must be a non-empty string",
                source="gdelt",
                operation="search",
                parameter="query",
                value=query,
            )
        if max_results <= 0 or max_results > 250:
            raise SourceValidationError(
                "max_results must be between 1 and 250",
                source="gdelt",
                operation="search",
                parameter="max_results",
                value=max_results,
                expected="1..250",
            )

        q = query.strip()
        if language:
            q += f" sourcelang:{language}"
        if country:
            q += f" sourcecountry:{country}"
        if domains:
            domain_clause = " OR ".join(f"domain:{d.strip()}" for d in domains if d.strip())
            if domain_clause:
                q = f"({q}) ({domain_clause})"

        params = {
            "query": q,
            "mode": "artlist",
            "format": "json",
            "maxrecords": str(max_results),
            "sort": "hybridrel",
        }
        if timespan:
            params["timespan"] = timespan
        if start_date:
            params["startdatetime"] = start_date
        if end_date:
            params["enddatetime"] = end_date

        url = f"{GDELT_DOC_API}?{urlencode(params)}"

        # --- retry loop: handles 429 / 5xx / transient network errors ------
        response: Optional[httpx.Response] = None
        last_exc: Optional[BaseException] = None

        for attempt in range(1, self.max_attempts + 1):
            response = None
            last_exc = None
            try:
                response = self._client.get(url)
            except httpx.TimeoutException as exc:
                last_exc = exc
            except httpx.RequestError as exc:
                last_exc = exc

            # Success path (including 4xx that we do not retry below).
            if response is not None and response.status_code < 400:
                break

            # 429 — respect Retry-After if present, else exponential backoff.
            if response is not None and response.status_code == 429:
                if attempt < self.max_attempts:
                    wait = _parse_retry_after(response.headers.get("Retry-After")) \
                        or self.backoff_base * attempt
                    time.sleep(wait)
                    continue
                # Out of attempts — fall through to error handling below.

            # 5xx — retry.
            if response is not None and response.status_code >= 500:
                if attempt < self.max_attempts:
                    time.sleep(self.backoff_base * attempt)
                    continue
                # Out of attempts — fall through.

            # Other 4xx — do not retry.
            if response is not None and 400 <= response.status_code < 500:
                break

            # Network-level failure — retry.
            if response is None and attempt < self.max_attempts:
                time.sleep(self.backoff_base * attempt)
                continue

            # Out of attempts.
            break

        # --- translate the final outcome -----------------------------------
        if response is None:
            if isinstance(last_exc, httpx.TimeoutException):
                raise SourceTimeoutError(
                    "GDELT request timed out",
                    source="gdelt",
                    operation="search",
                    url=url,
                    timeout=self.timeout,
                    cause=last_exc,
                )
            raise SourceConnectionError(
                "GDELT network error",
                source="gdelt",
                operation="search",
                url=url,
                cause=last_exc,
            )

        if response.status_code == 429:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            raise SourceRateLimitError(
                f"GDELT rate limit exceeded (after {self.max_attempts} attempts)",
                source="gdelt",
                operation="search",
                status_code=429,
                retry_after=retry_after,
                url=url,
            )
        if response.status_code >= 500:
            raise SourceConnectionError(
                "GDELT server error",
                source="gdelt",
                operation="search",
                url=url,
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise SourceConnectionError(
                "GDELT client error",
                source="gdelt",
                operation="search",
                url=url,
                status_code=response.status_code,
            )

        text = response.text.strip()
        if not text:
            # GDELT returns empty body for zero results.
            return SourceResult(source="gdelt", source_type="api", query=query, items=[])

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            # GDELT returns plaintext error messages on invalid queries.
            snippet = text[:200].replace("\n", " ")
            raise SourceParseError(
                f"GDELT returned non-JSON response: {snippet!r}",
                source="gdelt",
                operation="search",
                url=url,
                content_type=response.headers.get("Content-Type"),
                payload_size=len(text),
                cause=exc,
            ) from exc

        articles = payload.get("articles") or []
        items: List[NewsItem] = []
        for raw in articles:
            if not isinstance(raw, dict):
                continue
            link = raw.get("url")
            title = raw.get("title")
            if not link or not title:
                continue
            domain = raw.get("domain") or urlparse(link).netloc

            # NOTE: GDELT's artlist mode does not return a description field.
            # The previous implementation incorrectly mapped `socialimage`
            # (an image URL) into `description`. That is a semantic error:
            # an image URL is not a description. `description` is left as
            # None, and the image URL is preserved inside metadata instead.
            item = NewsItem(
                title=title,
                url=link,
                canonical_url=canonicalize_url(link),
                description=None,
                snippet=None,
                source_name=domain,
                source_domain=domain,
                published_at=_parse_seendate(raw.get("seendate")),
                language=raw.get("language"),
                country=raw.get("sourcecountry"),
                metadata={
                    "gdelt": {
                        "url_mobile": raw.get("url_mobile"),
                        "socialimage": raw.get("socialimage"),
                    }
                },
            )
            items.append(item)

        return SourceResult(source="gdelt", source_type="api", query=query, items=items)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GDELTClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()