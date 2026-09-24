"""ETL boundary models for persistence and ingestion summaries."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PersistedNewsItem(BaseModel):
    id: str
    source_id: Optional[UUID] = None
    title: str
    url: str
    canonical_url: Optional[str] = None
    description: Optional[str] = None
    snippet: Optional[str] = None
    source_name: Optional[str] = None
    source_domain: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    discovered_at: datetime
    content: Optional[str] = None
    language: Optional[str] = None
    country: Optional[str] = None
    categories: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_hash: Optional[str] = None
    canonical_hash: Optional[str] = None


class IngestionSummary(BaseModel):
    discovered: int = 0
    transformed: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = Field(default_factory=list)

    def print_summary(self) -> None:
        print("=" * 40)
        print("NewsRoom ETL Summary")
        print("=" * 40)
        print(f"Discovered : {self.discovered}")
        print(f"Transformed: {self.transformed}")
        print(f"Inserted   : {self.inserted}")
        print(f"Updated    : {self.updated}")
        print(f"Skipped    : {self.skipped}")
        print(f"Failed     : {self.failed}")
        if self.errors:
            print("\nErrors:")
            for err in self.errors:
                print(f"  - {err}")
        print("=" * 40)