"""Tone contract — presentation tone, never facts."""
from __future__ import annotations

from enum import Enum

from pydantic import Field

from schemas.common import BaseContract


class ToneType(str, Enum):
    SERIOUS = "SERIOUS"
    INFORMATIVE = "INFORMATIVE"
    ANALYTICAL = "ANALYTICAL"
    CONVERSATIONAL = "CONVERSATIONAL"
    ENTHUSIASTIC = "ENTHUSIASTIC"
    HUMOROUS = "HUMOROUS"
    SARCASTIC = "SARCASTIC"


class ToneDecision(BaseContract):
    story_id: str
    tone: ToneType
    rationale: str = ""
    constraints: list[str] = Field(default_factory=list)
