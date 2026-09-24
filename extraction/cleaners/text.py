"""Text cleaning helpers."""

from __future__ import annotations

import re

_WS_RE = re.compile(r"[ \t\u00a0]+")
_NL_RE = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = _WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = _NL_RE.sub("\n\n", text)
    return text.strip()