"""Publishing contract — final publication record."""
from __future__ import annotations

from typing import Optional

from pydantic import Field

from schemas.common import BaseContract, new_publication_id


class PublishResult(BaseContract):
    story_id: str
    publication_id: str = Field(default_factory=new_publication_id)
    platform: str = "threads"
    external_id: Optional[str] = None
    url: Optional[str] = None
    published_at: Optional[str] = None
    status: str = "PENDING"
    error: Optional[str] = None
