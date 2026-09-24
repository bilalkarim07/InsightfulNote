"""Normalised Threads post model + provider-independent SocialPost."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ThreadsPost(BaseModel):
    """Provider-specific Threads post."""

    id: str
    text: Optional[str] = None
    username: Optional[str] = None
    permalink: Optional[str] = None
    timestamp: Optional[datetime] = None
    media_type: Optional[str] = None
    media_url: Optional[str] = None
    shortcode: Optional[str] = None
    has_replies: Optional[bool] = None
    is_quote_post: Optional[bool] = None
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "ThreadsPost":
        ts = data.get("timestamp")
        parsed_ts = None
        if ts:
            try:
                parsed_ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                parsed_ts = None
        return cls(
            id=str(data.get("id", "")),
            text=data.get("text"),
            username=data.get("username"),
            permalink=data.get("permalink"),
            timestamp=parsed_ts,
            media_type=data.get("media_type"),
            media_url=data.get("thumbnail_url") or data.get("media_url"),
            shortcode=data.get("shortcode"),
            has_replies=data.get("has_replies"),
            is_quote_post=data.get("is_quote_post"),
            raw=data,
        )


class SocialPost(BaseModel):
    """Provider-independent social post for the NewsRoom evidence layer.

    Threads, X, and Reddit will all normalise into this shape so the
    research/editorial agents never see provider-specific payloads.
    """

    id: str
    platform: str = "threads"
    author_id: Optional[str] = None
    author_username: Optional[str] = None
    text: str = ""
    created_at: Optional[datetime] = None
    permalink: Optional[str] = None
    like_count: Optional[int] = None
    reply_count: Optional[int] = None
    repost_count: Optional[int] = None
    quote_count: Optional[int] = None
    media: list[dict[str, Any]] = Field(default_factory=list)
    source_url: Optional[str] = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_threads_post(cls, post: ThreadsPost) -> "SocialPost":
        media: list[dict[str, Any]] = []
        if post.media_url:
            media.append({"type": post.media_type or "unknown", "url": post.media_url})
        return cls(
            id=post.id,
            platform="threads",
            author_username=post.username,
            text=post.text or "",
            created_at=post.timestamp,
            permalink=post.permalink,
            media=media,
            source_url=post.permalink,
            raw_metadata={
                "media_type": post.media_type,
                "shortcode": post.shortcode,
                "has_replies": post.has_replies,
                "is_quote_post": post.is_quote_post,
            },
        )