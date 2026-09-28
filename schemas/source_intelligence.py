"""Source Intelligence contract — assess quality and independence."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field, field_validator

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
    source_url: str = ""
    source_name: str = ""
    source_type: SourceType = SourceType.UNKNOWN
    authority: str = ""
    independence: str = "UNKNOWN"
    attribution: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    conflicts: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_unknown_confidence(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().upper() in ("", "UNKNOWN", "N/A"):
            return None
        return value

    @field_validator("conflicts", "uncertainty", mode="before")
    @classmethod
    def normalize_text_lists(cls, value: object) -> object:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [value]
        return value


class SourceIntelligenceResult(BaseContract):
    run_id: str = ""
    story_id: str
    assessments: list[SourceAssessment] = Field(default_factory=list)
    independent_reporting: Optional[bool] = None
    copying_detected: bool = False
    notes: str = ""
