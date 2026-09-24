"""LangChain tool: search Threads posts."""

from __future__ import annotations

from typing import Literal

from langchain_core.tools import tool

from schemas.threads.search import ThreadsSearchResult

from ._api_factory import build_threads_api


@tool
def threads_search(
    query: str,
    search_type: Literal["TOP", "RECENT"] = "RECENT",
    search_mode: Literal["KEYWORD", "TAG"] = "KEYWORD",
    limit: int = 20,
) -> dict:
    """Search public Threads posts by keyword or supported tag.

    Args:
        query: The search term or tag to look for.
        search_type: ``TOP`` for popular results, ``RECENT`` for the newest.
        search_mode: ``KEYWORD`` for keyword search, ``TAG`` for tag search.
        limit: Maximum number of results to return (capped at 100).
    """
    api = build_threads_api()
    try:
        items = api.search(
            query=query,
            search_type=search_type,
            search_mode=search_mode,
            limit=min(limit, 100),
        )
    finally:
        api.close()

    result = ThreadsSearchResult.from_api(
        query=query,
        search_type=search_type,
        search_mode=search_mode,
        items=items,
    )
    return {
        "source": "threads",
        "operation": "search",
        "query": query,
        "search_type": search_type,
        "search_mode": search_mode,
        "results": [post.model_dump(mode="json") for post in result.results],
    }