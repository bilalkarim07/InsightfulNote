from langchain_core.tools import tool

from extraction.normalizers.article import extract_article


@tool
def web_extract(url: str) -> dict:
    """Fetch and extract readable article content from a URL.

    Args:
        url: Absolute http(s) URL of an article page.
    """
    item = extract_article(url)
    return item.model_dump(mode="json")