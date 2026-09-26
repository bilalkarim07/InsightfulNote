"""Pydantic models for model capability tracking.

Declared vs verified capabilities are SEPARATE. A model must not be marked
"verified" until an executable benchmark proves it.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CapabilityStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PASS = "PASS"
    FAIL = "FAIL"


class ModelCapabilities(BaseModel):
    provider: str
    model: str

    declared_tool_calling: bool = False
    declared_structured_output: bool = False
    declared_reasoning: bool = False
    declared_long_context: bool = False
    declared_max_context: Optional[int] = None

    verified_basic_invocation: CapabilityStatus = CapabilityStatus.UNVERIFIED
    verified_pydantic_output: CapabilityStatus = CapabilityStatus.UNVERIFIED
    verified_tool_calling: CapabilityStatus = CapabilityStatus.UNVERIFIED
    verified_tool_plus_structure: CapabilityStatus = CapabilityStatus.UNVERIFIED
    verified_newsroom_contracts: CapabilityStatus = CapabilityStatus.UNVERIFIED

    preferred_structured_method: Optional[str] = None

    reliability_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    notes: str = ""

    def is_eligible_for(self, *required: str) -> bool:
        checks = {
            "tool_calling": self.verified_tool_calling == CapabilityStatus.PASS,
            "structured_output": self.verified_pydantic_output == CapabilityStatus.PASS,
            "tool_plus_structure": self.verified_tool_plus_structure == CapabilityStatus.PASS,
            "newsroom_contracts": self.verified_newsroom_contracts == CapabilityStatus.PASS,
            "basic_invocation": self.verified_basic_invocation == CapabilityStatus.PASS,
        }
        return all(checks.get(r, False) for r in required)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._caps: dict[str, ModelCapabilities] = {}

    def _key(self, provider: str, model: str) -> str:
        return f"{provider}/{model}"

    def register(self, caps: ModelCapabilities) -> None:
        self._caps[self._key(caps.provider, caps.model)] = caps

    def get(self, provider: str, model: str) -> Optional[ModelCapabilities]:
        return self._caps.get(self._key(provider, model))

    def all(self) -> list[ModelCapabilities]:
        return list(self._caps.values())

    def eligible_for(self, *required: str) -> list[ModelCapabilities]:
        return [c for c in self._caps.values() if c.is_eligible_for(*required)]
