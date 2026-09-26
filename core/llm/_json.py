"""JSON extraction utilities — strip markdown fences, find first JSON object."""
from __future__ import annotations

import json
import re
from typing import Any, Optional

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def strip_markdown_fences(text: str) -> str:
    """If text is wrapped in ```json ... ``` fences, return inner content."""
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


_THOUGHT_BLOCK = re.compile(r"<thought>.*?</thought>", re.DOTALL | re.IGNORECASE)


def strip_thinking_blocks(text: str) -> str:
    """Remove <thought>...</thought> blocks emitted by some reasoning models."""
    if not text:
        return text
    return _THOUGHT_BLOCK.sub("", text).strip()


def extract_first_json(text: str) -> Optional[dict[str, Any]]:
    """Find and parse the first JSON object in text."""
    text = strip_thinking_blocks(text)
    text = strip_markdown_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None
