"""Typed NewsRoom state passed across agent stages."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from schemas.common import new_run_id, utcnow


class NewsroomState(BaseModel):
    run_id: str = Field(default_factory=new_run_id)
    story_id: Optional[str] = None
    current_stage: str = "init"

    inputs: dict[str, Any] = Field(default_factory=dict)
    research: Optional[dict[str, Any]] = None
    verification: Optional[dict[str, Any]] = None
    editorial: Optional[dict[str, Any]] = None
    tone: Optional[dict[str, Any]] = None
    draft: Optional[dict[str, Any]] = None
    platform_post: Optional[dict[str, Any]] = None
    validation: Optional[dict[str, Any]] = None
    publication: Optional[dict[str, Any]] = None

    errors: list[str] = Field(default_factory=list)
    escalation: Optional[str] = None
    updated_at: str = Field(default_factory=lambda: utcnow().isoformat())

    def advance(self, stage: str) -> None:
        self.current_stage = stage
        self.updated_at = utcnow().isoformat()

    def record_error(self, message: str) -> None:
        self.errors.append(message)
        self.updated_at = utcnow().isoformat()
