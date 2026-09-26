"""Source Intelligence contract — assess quality and independence."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field

from schemas.common import BaseContract, NestedContract


class SourceType(str, Enum):
    PRIMARY = "PRIMARY"
    OFFICIAL = "OFFICIAL"
    SECONDARY = "SECONDARY"
    AGGREGATOR = "AGGREGATOR"
    OPINION = "OPINION"
    UNKNOWN = "UNKNOWN"


class SourceAssessment(NestedContract):
    story_id: str
    source_id: str
    source_name: str = ""
    source_type: SourceType = SourceType.UNKNOWN
    authority: str = ""
    independence: str = ""
    attribution: str = ""
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    conflicts: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)


class SourceIntelligenceResult(BaseContract):
    story_id: str
    assessments: list[SourceAssessment] = Field(default_factory=list)
    independent_reporting: bool = False
    copying_detected: bool = False
    notes: str = ""
