"""Tavily client — search and extract."""

from __future__ import annotations

import os
from typing import Any, List, Optional

from core.exceptions import (
    SourceAuthenticationError,
    SourceConnectionError,
    SourceParseError,
    SourceRateLimitError,
    SourceTimeoutError,
    SourceValidationError,
)
from extraction.canonicalization.url import canonicalize_url
from schemas.sources import NewsItem, SourceResult

try:
    from tavily import TavilyClient as _TavilyAPIClient  # type: ignore
except Exception as exc:  # pragma: no cover
    raise ImportError(
        "The 'tavily-python' package is required. Install with: pip install tavily-python"
    ) from exc


class TavilyClient:
    """Native Tavily client with ``search`` and ``extract``."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        resolved = api_key or os.getenv("TAVILY_API_KEY")
        if not resolved:
            raise SourceAuthenticationError(
                "TAVILY_API_KEY is not set",
                source="tavily",
                operation="init",
                credential_name="TAVILY_API_KEY",
            )
        self._api_key = resolved
        self.timeout = timeout
        self._client = _TavilyAPIClient(api_key=resolved)

    # --- search ---------------------------------------------------------

    def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        topic: str = "general",
        include_answer: bool = False,
        include_raw_content: bool = False,
    ) -> SourceResult:
        if not query or not query.strip():
            raise SourceValidationError(
                "query must be a non-empty string",
                source="tavily",
                operation="search",
                parameter="query",
                value=query,
            )
        if max_results <= 0:
            raise SourceValidationError(
                "max_results must be > 0",
                source="tavily",
                operation="search",
                parameter="max_results",
                value=max_results,
            )

        payload: dict[str, Any] = {
            "query": query.strip(),
            "max_results": max_results,
            "search_depth": search_depth,
            "topic": topic,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
        }
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains

        try:
            response = self._client.search(**payload)
        except Exception as exc:
            raise self._translate("search", exc) from exc

        return self._normalize_search(query, response)

    # --- extract --------------------------------------------------------

    def extract(
        self,
        urls: List[str],
        extract_depth: str = "basic",
    ) -> SourceResult:
        if not urls:
            raise SourceValidationError(
                "urls must be a non-empty list",
                source="tavily",
                operation="extract",
                parameter="urls",
                value=urls,
            )

        try:
            response = self._client.extract(urls=urls, extract_depth=extract_depth)
        except Exception as exc:
            raise self._translate("extract", exc) from exc

        results = response.get("results") or []
        items: List[NewsItem] = []
        for raw in results:
            if not isinstance(raw, dict):
                continue
            url = raw.get("url")
            if not url:
                continue
            content = raw.get("raw_content") or raw.get("content")
            items.append(
                NewsItem(
                    title=raw.get("title") or url,
                    url=url,
                    canonical_url=canonicalize_url(url),
                    content=content,
                    metadata={"tavily_extract": True},
                )
            )

        return SourceResult(
            source="tavily",
            source_type="api",
            query=None,
            items=items,
        )

    # --- helpers --------------------------------------------------------

    def _normalize_search(self, query: str, response: dict) -> SourceResult:
        results = response.get("results") or []
        items: List[NewsItem] = []
        for raw in results:
            if not isinstance(raw, dict):
                continue
            url = raw.get("url")
            if not url:
                continue
            items.append(
                NewsItem(
                    title=raw.get("title") or url,
                    url=url,
                    canonical_url=canonicalize_url(url),
                    description=raw.get("content"),
                    snippet=raw.get("content"),
                    content=raw.get("raw_content"),
                    metadata={
                        "tavily_score": raw.get("score"),
                        "tavily_published_date": raw.get("published_date"),
                    },
                )
            )
        return SourceResult(
            source="tavily",
            source_type="api",
            query=query,
            items=items,
        )

    def _translate(self, operation: str, exc: BaseException) -> Exception:
        message = str(exc).lower()
        if "unauthorized" in message or "api key" in message or "401" in message:
            return SourceAuthenticationError(
                "Tavily authentication failed",
                source="tavily",
                operation=operation,
                credential_name="TAVILY_API_KEY",
                cause=exc,
            )
        if "rate limit" in message or "429" in message:
            return SourceRateLimitError(
                "Tavily rate limit exceeded",
                source="tavily",
                operation=operation,
                cause=exc,
            )
        if "timeout" in message:
            return SourceTimeoutError(
                "Tavily request timed out",
                source="tavily",
                operation=operation,
                timeout=self.timeout,
                cause=exc,
            )
        return SourceConnectionError(
            f"Tavily {operation} failed: {exc}",
            source="tavily",
            operation=operation,
            cause=exc,
        )

    def close(self) -> None:
        self._client = None  # type: ignore[assignment]

    def __enter__(self) -> "TavilyClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()