"""Shared identifiers, base contracts, and run context.

Traceability rules:
  - BaseContract → top-level containers. Carries run_id and created_at.
  - NestedContract → children nested inside a container. No run_id.

Rationale: a child inherits its run_id from its container. Duplicating
run_id on every nested object weakens the contract and forces the LLM
to fill redundant data it will get wrong.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import NewType
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

RunId = NewType("RunId", str)
StoryId = NewType("StoryId", str)
SourceId = NewType("SourceId", str)
ClaimId = NewType("ClaimId", str)
EvidenceId = NewType("EvidenceId", str)
PublicationId = NewType("PublicationId", str)


def new_run_id() -> str:
    return f"run_{uuid4().hex[:12]}"


def new_story_id() -> str:
    return f"story_{uuid4().hex[:12]}"


def new_claim_id() -> str:
    return f"claim_{uuid4().hex[:10]}"


def new_evidence_id() -> str:
    return f"ev_{uuid4().hex[:10]}"


def new_publication_id() -> str:
    return f"pub_{uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BaseContract(BaseModel):
    """Top-level container contract. Carries the run_id and created_at."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    run_id: str = Field(..., description="Run identifier shared across the chain")
    created_at: datetime = Field(default_factory=utcnow)


class NestedContract(BaseModel):
    """Nested child contract. Inherits run_id from its container."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )
