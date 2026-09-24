"""Centralized lazy Supabase client factory."""
from __future__ import annotations

import os
from functools import lru_cache

from supabase import Client, create_client


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Return a cached Supabase client using backend credentials."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SECRET_KEY must be set in environment."
        )
    return create_client(url, key)