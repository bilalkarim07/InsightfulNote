"""Production run request — what the graph receives in real execution.

Synthetic testing still passes a topic. Production passes story_id + mode.
"""
from __future__ import annotations
from typing import Literal, Optional

from pydantic import BaseModel, Field


class NewsRunRequest(BaseModel):
    run_id: str
    story_id: Optional[str] = None       # production: real story from Supabase
    topic: Optional[str] = None          # synthetic: freely chosen topic
    mode: Literal["breaking", "reporting", "synthetic"] = "synthetic"
    platform: Literal["threads"] = "threads"
    dry_run: bool = True
    metadata: dict = Field(default_factory=dict)

    def is_production(self) -> bool:
        return self.mode in ("breaking", "reporting")