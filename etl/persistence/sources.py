"""Idempotent source resolution."""
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
    """Return source UUID, creating it if it doesn't exist.

    Uniqueness is based on (name, source_type).
    """
    # Try to fetch existing
    resp = (
        client.table("sources")
        .select("id")
        .eq("name", name)
        .eq("source_type", source_type)
        .execute()
    )
    if resp.data:
        return UUID(resp.data[0]["id"])

    # Create new
    insert_resp = (
        client.table("sources")
        .insert({
            "name": name,
            "source_type": source_type,
            "domain": domain,
            "base_url": base_url,
            "is_active": True,
        })
        .execute()
    )
    if not insert_resp.data:
        raise RuntimeError(f"Failed to create source: {name} ({source_type})")
    return UUID(insert_resp.data[0]["id"])