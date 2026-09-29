"""Source Intelligence contract — assess quality and independence."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

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


def normalize_source_intelligence_payload(
    payload: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Repair safe source-assessment omissions before contract validation."""
    normalized = dict(payload)
    context = context or {}
    story_id = normalized.get("story_id") or context.get("story_id")
    if not normalized.get("story_id") and story_id:
        normalized["story_id"] = story_id

    assessments = normalized.get("assessments")
    if not isinstance(assessments, list):
        return normalized

    source_records = {
        row["source_id"]: row
        for row in context.get("source_inputs", [])
        if isinstance(row, dict)
        and isinstance(row.get("source_id"), str)
        and isinstance(row.get("source_url"), str)
        and row["source_url"]
    }
    safe_defaults = {
        "source_url": "",
        "source_name": "",
        "source_type": SourceType.UNKNOWN.value,
        "authority": "",
        "independence": "UNKNOWN",
        "conflicts": [],
        "uncertainty": [],
    }
    normalized_assessments = []
    for assessment in assessments:
        if not isinstance(assessment, dict):
            normalized_assessments.append(assessment)
            continue

        item = dict(assessment)
        if not item.get("story_id") and story_id:
            item["story_id"] = story_id
        for field, default in safe_defaults.items():
            if item.get(field) is None:
                item[field] = default

        source_id = item.get("source_id")
        source = source_records.get(source_id) if isinstance(source_id, str) else None
        if source is not None:
            item["source_url"] = source["source_url"]
            item["source_name"] = source.get("source_identity") or ""
            documented_type = source.get("documented_source_type") or "UNKNOWN"
            if documented_type != SourceType.UNKNOWN.value:
                item["source_type"] = documented_type
            item["authority"] = str(source.get("documented_authority") or "")
        normalized_assessments.append(item)

    normalized["assessments"] = normalized_assessments
    return normalized
