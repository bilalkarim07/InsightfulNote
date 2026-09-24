from typing import List, Optional

from langchain_core.tools import tool

from sources.ddgs import DDGSClient


@tool
def ddgs_text_search(
    query: str,
    max_results: int = 10,
    region: str = "us-en",
    timelimit: Optional[str] = None,
    domains: Optional[List[str]] = None,
) -> dict:
    """Search the web via DDGS text search.

    Args:
        query: Search query.
        max_results: Maximum number of results.
        region: Region code, e.g. "us-en".
        timelimit: Optional timelimit (d/w/m/y).
        domains: Optional list of domains to restrict to.
    """
    with DDGSClient() as client:
        result = client.text_search(
            query=query, max_results=max_results,
            region=region, timelimit=timelimit, domains=domains,
        )
    return result.model_dump(mode="json")


@tool
def ddgs_news_search(
    query: str,
    max_results: int = 10,
    region: str = "us-en",
    timelimit: Optional[str] = None,
    domains: Optional[List[str]] = None,
) -> dict:
    """Search news via DDGS news search.

    Args:
        query: Search query.
        max_results: Maximum number of results.
        region: Region code, e.g. "us-en".
        timelimit: Optional timelimit (d/w/m/y).
        domains: Optional list of domains to restrict to.
    """
    with DDGSClient() as client:
        result = client.news_search(
            query=query, max_results=max_results,
            region=region, timelimit=timelimit, domains=domains,
        )
    return result.model_dump(mode="json")