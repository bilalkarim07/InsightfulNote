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
import json
import re
from typing import Any

MAX_EVIDENCE_ITEMS = 5
MAX_DESCRIPTION_CHARS = 300
MAX_TITLE_CHARS = 120


def _parse_search_payload(raw: Any) -> dict[str, Any]:
    """Parse whatever search_web returned into a dict.

    Accepts:
      - a dict (already parsed)
      - a JSON string
      - a Python-dict-literal string (single quotes)
      - anything else: returns {} with a raw fallback
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
    # Give up — return raw so callers can decide.
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

    # Fallback: treat raw text as a single evidence item.
    if not items:
        text = payload.get("_raw") or (str(raw) if raw else "")
        text = _truncate(text, max_description_chars)
        if not text:
            return []
        return [{
            "evidence_id": "ev_1",
            "source_id": "s1",
            "title": "",
            "url": None,
            "quote": text,
        }]

    seen_urls: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("canonical_url") or item.get("url") or ""
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

        idx = len(out) + 1
        out.append({
            "evidence_id": f"ev_{idx}",
            "source_id": f"s{idx}",
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
