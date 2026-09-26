"""Editorial contract — what exactly are we saying."""
from __future__ import annotations

from pydantic import Field

from schemas.common import BaseContract


class EditorialDecision(BaseContract):
    story_id: str
    central_event: str
    allowed_claim_ids: list[str] = Field(default_factory=list)
    blocked_claim_ids: list[str] = Field(default_factory=list)
    must_include: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)
    do_not_include: list[str] = Field(default_factory=list)
    attribution_notes: str = ""
    uncertainty_notes: str = ""
    framing: str = ""
