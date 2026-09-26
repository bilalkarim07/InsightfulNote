"""Validation contract — deterministic final QA result."""
from __future__ import annotations

from enum import Enum

from pydantic import Field

from schemas.common import BaseContract


class ValidationState(str, Enum):
    PASS = "PASS"
    BLOCK = "BLOCK"
    RETRY = "RETRY"
    ESCALATE = "ESCALATE"


class ValidationResult(BaseContract):
    story_id: str
    state: ValidationState
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    notes: str = ""
