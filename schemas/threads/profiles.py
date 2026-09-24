"""Normalised Threads profile schema."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ThreadsProfile(BaseModel):
    id: str
    username: Optional[str] = None
    name: Optional[str] = None
    biography: Optional[str] = None
    profile_picture_url: Optional[str] = None
    follower_count: Optional[int] = None
    following_count: Optional[int] = None
    is_verified: Optional[bool] = None
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "ThreadsProfile":
        return cls(
            id=str(data.get("id", "")),
            username=data.get("username"),
            name=data.get("name"),
            biography=data.get("biography"),
            profile_picture_url=data.get("profile_picture_url"),
            follower_count=data.get("follower_count"),
            following_count=data.get("following_count"),
            is_verified=data.get("is_verified"),
            raw=data,
        )