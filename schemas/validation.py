"""Validation contract — deterministic final QA result."""
from __future__ import annotations

from enum import Enum

from pydantic import Field

from schemas.common import BaseContract, NestedContract


class ValidationState(str, Enum):
    PASS = "PASS"
    BLOCK = "BLOCK"
    RETRY = "RETRY"
    ESCALATE = "ESCALATE"


class SentenceClaimMapping(NestedContract):
    sentence: str
    claim_ids: list[str] = Field(default_factory=list)


class ValidationResult(BaseContract):
    story_id: str
    state: ValidationState
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sentence_claims: list[SentenceClaimMapping] = Field(default_factory=list)
    failed_sentences: list[str] = Field(default_factory=list)
    notes: str = ""
