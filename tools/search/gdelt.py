from langchain_core.tools import tool

from sources.gdelt import GDELTClient


@tool
def gdelt_search(query: str, max_results: int = 10, timespan: str | None = None) -> dict:
    """Search GDELT for news and document results.

    Args:
        query: Search query.
        max_results: Maximum number of results (1..250).
        timespan: Optional GDELT timespan, e.g. "24h", "7d".
    """
    with GDELTClient() as client:
        result = client.search(query=query, max_results=max_results, timespan=timespan)
    return result.model_dump(mode="json")