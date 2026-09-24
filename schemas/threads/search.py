"""Normalised Threads search result schema."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .posts import ThreadsPost


class ThreadsSearchResult(BaseModel):
    query: str
    search_type: str = "RECENT"
    search_mode: str = "KEYWORD"
    results: list[ThreadsPost] = Field(default_factory=list)

    @classmethod
    def from_api(
        cls,
        *,
        query: str,
        search_type: str,
        search_mode: str,
        items: list[dict],
    ) -> "ThreadsSearchResult":
        return cls(
            query=query,
            search_type=search_type,
            search_mode=search_mode,
            results=[ThreadsPost.from_api(item) for item in items],
        )