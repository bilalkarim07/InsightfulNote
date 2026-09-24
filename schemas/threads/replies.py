"""Normalised Threads reply model + provider-independent SocialReply."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ThreadsReply(BaseModel):
    id: str
    text: Optional[str] = None
    username: Optional[str] = None
    timestamp: Optional[datetime] = None
    permalink: Optional[str] = None
    media_type: Optional[str] = None
    is_reply: Optional[bool] = None
    is_reply_owned_by_me: Optional[bool] = None
    root_post: Optional[str] = None
    replied_to: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "ThreadsReply":
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
            timestamp=parsed_ts,
            permalink=data.get("permalink"),
            media_type=data.get("media_type"),
            is_reply=data.get("is_reply"),
            is_reply_owned_by_me=data.get("is_reply_owned_by_me"),
            root_post=data.get("root_post"),
            replied_to=data.get("replied_to"),
            raw=data,
        )


class SocialReply(BaseModel):
    """Provider-independent social reply for the NewsRoom evidence layer."""

    id: str
    platform: str = "threads"
    post_id: Optional[str] = None
    author_id: Optional[str] = None
    author_username: Optional[str] = None
    text: str = ""
    created_at: Optional[datetime] = None
    permalink: Optional[str] = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_threads_reply(
        cls, reply: ThreadsReply, parent_post_id: Optional[str] = None
    ) -> "SocialReply":
        return cls(
            id=reply.id,
            platform="threads",
            post_id=parent_post_id or reply.root_post,
            author_username=reply.username,
            text=reply.text or "",
            created_at=reply.timestamp,
            permalink=reply.permalink,
            raw_metadata={
                "is_reply_owned_by_me": reply.is_reply_owned_by_me,
                "replied_to": reply.replied_to,
            },
        )