"""Selection contract — decide whether a story proceeds."""
from __future__ import annotations

from enum import Enum

from pydantic import Field

from schemas.common import BaseContract


class SelectionState(str, Enum):
    SELECT = "SELECT"
    DEFER = "DEFER"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"


class SelectionDecision(BaseContract):
    story_id: str
    state: SelectionState
    reason: str = ""
    priority: int = 100
    topic: str = ""
    novelty_score: float = 0.0
    previous_publication_ids: list[str] = Field(default_factory=list)
    notes: str = ""
