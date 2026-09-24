from langchain_core.tools import tool

from extraction.fetchers.http import HTTPFetcher


@tool
def web_fetch(url: str, max_chars: int = 20000) -> dict:
    """Fetch a URL and return status, content type and text (truncated).

    Args:
        url: Absolute http(s) URL.
        max_chars: Maximum number of characters to return from the body.
    """
    with HTTPFetcher() as fetcher:
        result = fetcher.fetch(url)
    return {
        "url": result.url,
        "final_url": result.final_url,
        "status_code": result.status_code,
        "content_type": result.content_type,
        "text": (result.text or "")[:max_chars],
    }