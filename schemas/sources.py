"""Common normalized models for all discovery and extraction sources."""

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    """A single normalized news or web item."""

    id: Optional[str] = None
    title: str
    url: str
    canonical_url: Optional[str] = None
    description: Optional[str] = None
    snippet: Optional[str] = None
    source_name: Optional[str] = None
    source_domain: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    content: Optional[str] = None
    language: Optional[str] = None
    country: Optional[str] = None
    categories: List[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceResult(BaseModel):
    """Container for a source query result."""

    source: str
    source_type: str
    query: Optional[str] = None
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
    items: List[NewsItem] = Field(default_factory=list)