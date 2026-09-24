from typing import List, Optional

from langchain_core.tools import tool

from sources.tavily import TavilyClient


@tool
def tavily_search(
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
    include_domains: Optional[List[str]] = None,
    exclude_domains: Optional[List[str]] = None,
    topic: str = "general",
) -> dict:
    """Search the web via Tavily.

    Args:
        query: Search query.
        max_results: Maximum number of results.
        search_depth: "basic" or "advanced".
        include_domains: Optional domains to include.
        exclude_domains: Optional domains to exclude.
        topic: "general" or "news".
    """
    with TavilyClient() as client:
        result = client.search(
            query=query, max_results=max_results,
            search_depth=search_depth, topic=topic,
            include_domains=include_domains, exclude_domains=exclude_domains,
        )
    return result.model_dump(mode="json")


@tool
def tavily_extract(urls: List[str], extract_depth: str = "basic") -> dict:
    """Extract full content from URLs via Tavily.

    Args:
        urls: List of URLs to extract.
        extract_depth: "basic" or "advanced".
    """
    with TavilyClient() as client:
        result = client.extract(urls=urls, extract_depth=extract_depth)
    return result.model_dump(mode="json")