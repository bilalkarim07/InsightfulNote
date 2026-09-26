"""Platform contract — final post text adapted to a target platform."""
from __future__ import annotations

from pydantic import Field

from schemas.common import BaseContract


class PlatformPost(BaseContract):
    story_id: str
    platform: str = "threads"
    text: str
    char_count: int = 0
    claim_ids: list[str] = Field(default_factory=list)
    source_reference: str = ""
    warnings: list[str] = Field(default_factory=list)
