"""LangChain tools: read Threads posts and conversations."""

from __future__ import annotations

from langchain_core.tools import tool

from schemas.threads.posts import ThreadsPost
from schemas.threads.replies import ThreadsReply

from ._api_factory import build_threads_api


@tool
def threads_read_post(post_id: str) -> dict:
    """Read a specific Threads post by its ID.

    Args:
        post_id: The unique Threads post identifier.
    """
    api = build_threads_api()
    try:
        raw = api.get_post(post_id)
    finally:
        api.close()

    post = ThreadsPost.from_api(raw)
    return {
        "source": "threads",
        "operation": "read_post",
        "post": post.model_dump(mode="json"),
    }


@tool
def threads_read_conversation(
    post_id: str,
    limit: int = 50,
) -> dict:
    """Read the full conversation tree associated with a Threads post.

    This returns the complete conversation including nested replies –
    use :func:`threads_read_post` for just the top-level post.

    Args:
        post_id: The unique Threads post identifier.
        limit: Maximum number of replies to return (capped at 100).
    """
    api = build_threads_api()
    try:
        items = api.get_conversation(post_id, limit=min(limit, 100))
    finally:
        api.close()

    replies = [ThreadsReply.from_api(item) for item in items]
    return {
        "source": "threads",
        "operation": "read_conversation",
        "post_id": post_id,
        "replies": [r.model_dump(mode="json") for r in replies],
    }