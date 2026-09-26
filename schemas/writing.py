"""Writer contract — draft produced only from approved claims."""
from __future__ import annotations

from pydantic import Field

from schemas.common import BaseContract
from schemas.tone import ToneType


class WriterDraft(BaseContract):
    story_id: str
    headline: str = ""
    body: str
    source_reference: str = ""
    claim_ids: list[str] = Field(default_factory=list)
    tone: ToneType = ToneType.INFORMATIVE
    warnings: list[str] = Field(default_factory=list)
