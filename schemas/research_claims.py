"""Claims-only output from the research LLM.

The Research agent builds Evidence deterministically (from compact search
results) and asks the LLM to produce only claims. This avoids the LLM
failing to faithfully copy evidence JSON back — a job code should do.

The final ResearchResult is assembled in code:
    ResearchResult = code_evidence + llm_claims
"""
from __future__ import annotations

from pydantic import Field

from schemas.common import NestedContract
from schemas.research import Claim


class ResearchClaims(NestedContract):
    """LLM output for the research stage. Claims only, no evidence."""

    claims: list[Claim] = Field(default_factory=list)
    notes: str = ""
