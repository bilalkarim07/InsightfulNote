"""LangChain tools: authenticated user's posts and replies."""

from __future__ import annotations

from langchain_core.tools import tool

from schemas.threads.posts import ThreadsPost
from schemas.threads.replies import ThreadsReply

from ._api_factory import build_threads_api


@tool
def threads_get_my_posts(
    limit: int = 20,
) -> dict:
    """Retrieve the authenticated user's own Threads posts.

    Args:
        limit: Maximum number of posts to return (capped at 100).
    """
    api = build_threads_api()
    try:
        items = api.get_my_posts(limit=min(limit, 100))
    finally:
        api.close()

    posts = [ThreadsPost.from_api(item) for item in items]
    return {
        "source": "threads",
        "operation": "get_my_posts",
        "posts": [p.model_dump(mode="json") for p in posts],
    }


@tool
def threads_get_my_replies(
    limit: int = 20,
) -> dict:
    """Retrieve the authenticated user's own Threads replies.

    Args:
        limit: Maximum number of replies to return (capped at 100).
    """
    api = build_threads_api()
    try:
        items = api.get_my_replies(limit=min(limit, 100))
    finally:
        api.close()

    replies = [ThreadsReply.from_api(item) for item in items]
    return {
        "source": "threads",
        "operation": "get_my_replies",
        "replies": [r.model_dump(mode="json") for r in replies],
    }