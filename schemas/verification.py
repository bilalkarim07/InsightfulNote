"""Verification contract — claim-level support assessment."""
from __future__ import annotations

from enum import Enum

from pydantic import Field

from schemas.common import BaseContract, NestedContract


class VerificationStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    SUPPORTED_AS_ATTRIBUTED = "SUPPORTED_AS_ATTRIBUTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNCERTAIN = "UNCERTAIN"


class ClaimVerification(NestedContract):
    claim_id: str
    status: VerificationStatus
    evidence_ids: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    notes: str = ""


class VerificationResult(BaseContract):
    story_id: str
    verifications: list[ClaimVerification] = Field(default_factory=list)
    blocking: bool = False
    escalate: bool = False
    notes: str = ""
