"""LangChain tools: publish and reply on Threads.

Publishing tools are intentionally separated from read tools so that
NewsRoom can assign them only to agents with the appropriate
responsibility.
"""

from __future__ import annotations

from langchain_core.tools import tool

from ._api_factory import build_threads_api


@tool
def threads_create_post(text: str) -> dict:
    """Create and publish a new text post on Threads.

    The tool never accepts credentials – authentication is handled
    internally by the :class:`ThreadsAPI`.

    Args:
        text: The body of the post. Must not be empty.
    """
    if not text or not text.strip():
        return {"error": "validation_error", "message": "Post text must not be empty."}

    api = build_threads_api()
    try:
        result = api.create_post(text=text)
    finally:
        api.close()

    return {
        "source": "threads",
        "operation": "create_post",
        "result": result,
    }


@tool
def threads_reply_to_post(post_id: str, text: str) -> dict:
    """Reply to an existing Threads post.

    Args:
        post_id: The ID of the post to reply to.
        text: The body of the reply. Must not be empty.
    """
    if not post_id:
        return {"error": "validation_error", "message": "post_id must not be empty."}
    if not text or not text.strip():
        return {"error": "validation_error", "message": "Reply text must not be empty."}

    api = build_threads_api()
    try:
        result = api.reply_to_post(post_id=post_id, text=text)
    finally:
        api.close()

    return {
        "source": "threads",
        "operation": "reply_to_post",
        "post_id": post_id,
        "result": result,
    }