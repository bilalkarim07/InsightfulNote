"""Safe authentication schemas for agent consumption."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ThreadsTokenStatusSchema(BaseModel):
    """Safe token status – never exposes the raw access token."""

    authenticated: bool
    username: Optional[str] = None
    user_id: Optional[str] = None
    token_type: Optional[str] = None
    expires_at: Optional[datetime] = None
    days_remaining: Optional[int] = None
    expired: bool = False
    scopes: list[str] = Field(default_factory=list)