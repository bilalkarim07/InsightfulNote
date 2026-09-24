"""LangChain tool: discover public Threads profiles."""

from __future__ import annotations

from langchain_core.tools import tool

from schemas.threads.posts import ThreadsPost

from ._api_factory import build_threads_api


@tool
def threads_profile_discovery(
    username: str,
    limit: int = 20,
) -> dict:
    """Discover recent public posts from a Threads profile.

    Args:
        username: The exact Threads username to inspect.
        limit: Maximum number of posts to return (capped at 100).
    """
    api = build_threads_api()
    try:
        items = api.get_profile_posts(
            username=username,
            limit=min(limit, 100),
        )
    finally:
        api.close()

    posts = [ThreadsPost.from_api(item) for item in items]
    return {
        "source": "threads",
        "operation": "profile_discovery",
        "username": username,
        "posts": [p.model_dump(mode="json") for p in posts],
    }