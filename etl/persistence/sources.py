"""Idempotent source resolution using DB-level uniqueness."""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from supabase import Client


def get_or_create_source(
    client: Client,
    *,
    name: str,
    source_type: str,
    domain: Optional[str] = None,
    base_url: Optional[str] = None,
) -> UUID:
    """Return the source UUID, using DB upsert on (name, source_type).

    Relies on the existing UNIQUE (name, source_type) constraint.
    No SELECT-then-INSERT race window.
    """
    payload = {
        "name": name,
        "source_type": source_type,
        "domain": domain,
        "base_url": base_url,
        "is_active": True,
    }

    resp = (
        client.table("sources")
        .upsert(payload, on_conflict="name,source_type")
        .execute()
    )

    if not resp.data:
        raise RuntimeError(
            f"Source upsert returned no data for ({name!r}, {source_type!r})"
        )
    return UUID(resp.data[0]["id"])