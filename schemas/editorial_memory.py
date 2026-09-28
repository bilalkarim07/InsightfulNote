"""Editorial Memory contract per ammendments.md (Sections 15-25).

Persistent memory object built from Supabase state for agent graph context.
"""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class RecentPublication(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str
    story_id: str
    platform: str = "threads"
    content: str
    published_at: Optional[str] = None
    status: str = "published"
    external_post_id: Optional[str] = None
    title: Optional[str] = None
    categories: list[str] = Field(default_factory=list)


class RecentStory(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str
    title: str
    summary: Optional[str] = None
    categories: list[str] = Field(default_factory=list)
    first_seen_at: Optional[str] = None
    status: Optional[str] = None


class SimilarStory(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str
    title: str
    categories: list[str] = Field(default_factory=list)
    relationship: str = "RELATED"  # DUPLICATE | REPETITIVE | MATERIAL_UPDATE | RELATED
    score: float = 0.0
    published_at: Optional[str] = None


class EditorialMemory(BaseModel):
    """Memory object passed to agents to prevent duplicate reporting and ensure novelty/diversity."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recent_publications: list[RecentPublication] = Field(default_factory=list)
    recent_stories: list[RecentStory] = Field(default_factory=list)
    similar_stories: list[SimilarStory] = Field(default_factory=list)
    category_distribution: dict[str, int] = Field(default_factory=dict)
    repetition_warnings: list[str] = Field(default_factory=list)
