"""Discovery contract — candidate stories identified from the ETL pool."""
from __future__ import annotations

from typing import Optional

from pydantic import Field

from schemas.common import BaseContract, NestedContract


class CandidateStory(NestedContract):
    story_id: str
    title: str
    summary: str = ""
    topic: str = ""
    source_ids: list[str] = Field(default_factory=list)
    is_breaking: bool = False
    is_emerging: bool = False
    independent_source_count: int = 0
    first_seen_at: Optional[str] = None
    discovery_rationale: str = ""


class DiscoveryResult(BaseContract):
    candidates: list[CandidateStory] = Field(default_factory=list)
    notes: str = ""
