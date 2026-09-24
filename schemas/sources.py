"""Common normalized models for all discovery and extraction sources."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def _utcnow() -> datetime:
    """Single source of truth for 'now' in the normalized contract."""
    return datetime.now(timezone.utc)


def _validate_http_url(value: Optional[str], *, field: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    value = value.strip()
    if not value:
        raise ValueError(f"{field} must not be empty")
    if not value.startswith(("http://", "https://")):
        raise ValueError(f"{field} must use http/https scheme: {value!r}")
    if any(ch.isspace() for ch in value):
        raise ValueError(f"{field} must not contain whitespace: {value!r}")
    return value


class NewsItem(BaseModel):
    """A single normalized news or web item.

    All timestamps are timezone-aware UTC. ``id`` is deterministic:
    when the source does not provide one, it is derived from
    ``canonical_url or url`` via a stable hash, so repeated retrievals
    of the same article share the same identifier.
    """

    id: Optional[str] = None
    title: str
    url: str
    canonical_url: Optional[str] = None
    description: Optional[str] = None
    snippet: Optional[str] = None
    source_name: Optional[str] = None
    source_domain: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    discovered_at: datetime = Field(default_factory=_utcnow)
    content: Optional[str] = None
    language: Optional[str] = None
    country: Optional[str] = None
    categories: List[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return _validate_http_url(v, field="url")  # type: ignore[return-value]

    @field_validator("canonical_url")
    @classmethod
    def _check_canonical_url(cls, v: Optional[str]) -> Optional[str]:
        return _validate_http_url(v, field="canonical_url")

    @field_validator("published_at", "discovered_at")
    @classmethod
    def _require_tz(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return None
        if v.tzinfo is None:
            # Naive datetimes are assumed UTC (never local) — spec §13.
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _ensure_id(self) -> "NewsItem":
        if not self.id:
            basis = self.canonical_url or self.url
            if basis:
                self.id = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
        return self


class SourceResult(BaseModel):
    """Container for a source query result."""

    source: str
    source_type: str
    query: Optional[str] = None
    retrieved_at: datetime = Field(default_factory=_utcnow)
    items: List[NewsItem] = Field(default_factory=list)