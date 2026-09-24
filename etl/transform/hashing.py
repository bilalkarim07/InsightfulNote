"""Deterministic hashing for news items."""
from __future__ import annotations

import hashlib
from typing import Optional

from extraction.cleaners.text import clean_text


def compute_content_hash(content: Optional[str]) -> Optional[str]:
    """SHA-256 of normalized content. Returns None if content is empty."""
    if not content:
        return None
    normalized = clean_text(content)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_canonical_hash(canonical_url: Optional[str]) -> Optional[str]:
    """SHA-256 of canonical URL. Returns None if URL is missing."""
    if not canonical_url:
        return None
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()