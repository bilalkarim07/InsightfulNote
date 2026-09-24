from typing import List, Optional

from langchain_core.tools import tool

from sources.google_news import GoogleNewsClient


@tool
def google_news_search(
    query: str,
    max_results: int = 10,
    domains: Optional[List[str]] = None,
) -> dict:
    """Search Google News via RSS.

    Args:
        query: Search query.
        max_results: Maximum number of results.
        domains: Optional list of publisher domains to restrict to.
    """
    with GoogleNewsClient() as client:
        result = client.search(query=query, max_results=max_results, domains=domains)
    return result.model_dump(mode="json")