"""Deterministic search-result compactor.

Search tools return rich payloads (title, url, description, canonical_url,
retrieved_at, etc). Feeding all of that to the LLM causes:
  - prompt overflow
  - structured-output drift (the LLM invents field names)
  - irrelevant content mixed with relevant

This module extracts a small, clean evidence package deterministically.
No LLM. No drift.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

MAX_EVIDENCE_ITEMS = 5
MAX_DESCRIPTION_CHARS = 300
MAX_TITLE_CHARS = 120


def _parse_search_payload(raw: Any) -> dict[str, Any]:
    """Parse whatever search_web returned into a dict.

    Accepts:
      - a dict (already parsed)
      - a JSON string
      - a Python-dict-literal string (single quotes)
      - anything else: returns an empty parse result, which is not treated as evidence
    """
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {"_raw": str(raw)}
    text = raw.strip()
    if not text:
        return {}
    # Try strict JSON first.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try Python literal (single-quoted dicts).
    try:
        parsed = ast.literal_eval(text)
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, SyntaxError):
        pass
    # Give up — retain raw text for diagnostics, never as evidence.
    return {"_raw": text}


def _extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the list of items regardless of provider payload shape."""
    items = payload.get("items")
    if isinstance(items, list):
        return items
    results = payload.get("results")
    if isinstance(results, list):
        return results
    return []


def _truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def compact_search_results(
    raw: Any,
    *,
    max_items: int = MAX_EVIDENCE_ITEMS,
    max_description_chars: int = MAX_DESCRIPTION_CHARS,
) -> list[dict[str, Any]]:
    """Return a compact list of evidence items.

    Each item: {evidence_id, source_id, title, url, quote}
    Sorted by original order (relevance), deduped by canonical_url.
    """
    payload = _parse_search_payload(raw)
    items = _extract_items(payload)

    # Provider error text or snippets without provenance are not evidence.
    if not items:
        return []

    seen_urls: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("canonical_url") or item.get("url") or ""
        parsed_url = urlsplit(str(url))
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            continue
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)

        title = _truncate(str(item.get("title", "")), MAX_TITLE_CHARS)
        desc = _truncate(str(item.get("description", "")), max_description_chars)
        quote_parts = [p for p in (title, desc) if p]
        quote = " — ".join(quote_parts)
        if not quote:
            continue

        identity = hashlib.sha256(str(url).encode("utf-8")).hexdigest()[:20]
        out.append({
            "evidence_id": f"ev_{identity}",
            "source_id": f"src_{identity}",
            "title": title,
            "url": url or None,
            "quote": quote,
        })
        if len(out) >= max_items:
            break
    return out


def render_evidence_block(items: list[dict[str, Any]]) -> str:
    """Render a compact, LLM-friendly evidence block (deterministic format)."""
    lines: list[str] = []
    for item in items:
        lines.append(
            f'- evidence_id={item["evidence_id"]!r} '
            f'source_id={item["source_id"]!r} '
            f'url={item["url"]!r}'
        )
        lines.append(f'  quote: {item["quote"]}')
    return "\n".join(lines)


def total_chars(items: list[dict[str, Any]]) -> int:
    return sum(len(item.get("quote", "")) for item in items)
