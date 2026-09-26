"""Research contract — evidence package built by the Research Agent.

Design: claims and evidence are siblings, not nested.
  - Claim.evidence_ids → ["ev_abc", "ev_def"]
  - Evidence.evidence_id → "ev_abc"

This decoupling lets a single piece of evidence support multiple claims.
"""
from __future__ import annotations

from typing import Optional

from pydantic import Field

from schemas.common import BaseContract, NestedContract, new_claim_id, new_evidence_id


class Evidence(NestedContract):
    evidence_id: str = Field(default_factory=new_evidence_id)
    source_id: str
    quote: str = ""
    url: Optional[str] = None
    retrieved_at: Optional[str] = None
    context: str = ""


class Claim(NestedContract):
    claim_id: str = Field(default_factory=new_claim_id)
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    attribution: str = ""
    uncertainty: str = ""
    is_forecast: bool = False
    is_allegation: bool = False
    is_opinion: bool = False


class ResearchResult(BaseContract):
    story_id: str
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    conflicting_claims: list[str] = Field(default_factory=list)
    notes: str = ""
