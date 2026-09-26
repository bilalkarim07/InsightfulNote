"""Deterministic content compressor.

When a post exceeds the platform limit (Threads = 500 chars), drop the
lowest-value sentences until it fits. No LLM. No drift.

Scoring heuristic (higher = more important):
  +3  contains a number, date, or percent
  +3  contains an attribution cue ("said", "according to", "reported",
      "expects", "forecast", "announced")
  +2  contains a proper noun (capitalized, not sentence-start, not pronoun)
  +1  contains a claim_id token (claim_1, claim_2, ...)
  -1  is longer than 200 chars (usually a run-on)

The first sentence is always kept — it usually carries the lede.
Sentences are then added in score order until the character budget is full.
"""
from __future__ import annotations

import re
from typing import Iterable

_ATTRIBUTION_CUES = {
    "said", "says", "reported", "according", "announced", "expects",
    "forecast", "forecasted", "projects", "estimates", "confirmed",
    "revealed", "stated", "noted", "cited",
}
_PRONOUNS = {
    "the", "a", "an", "this", "that", "these", "those", "it", "he", "she",
    "they", "we", "you", "i", "his", "her", "their", "our", "your",
}
_NUMBER_RE = re.compile(r"\b\d[\d,.]*\b|\bpercent\b|\b%\b|\b20\d{2}\b")
_CLAIM_TOKEN_RE = re.compile(r"\bclaim_\d+\b")


def _split_sentences(text: str) -> list[str]:
    """Naive sentence splitter — good enough for English news text."""
    text = text.strip()
    if not text:
        return []
    # Split on . ! ? followed by whitespace or end.
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _score_sentence(s: str, first: bool = False) -> int:
    score = 0
    lower = s.lower()
    if _NUMBER_RE.search(s):
        score += 3
    if any(cue in lower for cue in _ATTRIBUTION_CUES):
        score += 3
    # Proper noun detection: capitalized word that isn't sentence-start and isn't a pronoun.
    words = s.split()
    for i, w in enumerate(words):
        if i == 0:
            continue
        core = w.strip(".,;:!?\"'()[]{}")
        if core and core[0].isupper() and core.lower() not in _PRONOUNS:
            score += 2
            break
    if _CLAIM_TOKEN_RE.search(s):
        score += 1
    if len(s) > 200:
        score -= 1
    if first:
        score += 100  # lede is always kept
    return score


def compress_to_limit(text: str, limit: int = 500, ellipsis: str = "…") -> str:
    """Return text <= limit, preserving the lede and highest-value sentences."""
    text = text.strip()
    if len(text) <= limit:
        return text

    sentences = _split_sentences(text)
    if not sentences:
        return text[: limit - 1] + ellipsis

    # Score every sentence. First sentence always wins.
    scored = [(i, _score_sentence(s, first=(i == 0)), s)
              for i, s in enumerate(sentences)]
    scored.sort(key=lambda t: (-t[1], t[0]))

    chosen: list[tuple[int, str]] = []
    budget = limit - len(ellipsis)
    for idx, _score, s in scored:
        candidate_len = len(s) + (1 if chosen else 0)  # space separator
        if sum(len(c[1]) for c in chosen) + candidate_len + len(ellipsis) > limit:
            continue
        chosen.append((idx, s))
        if sum(len(c[1]) for c in chosen) + len(ellipsis) >= limit:
            break

    # Re-order by original position so the output reads naturally.
    chosen.sort(key=lambda t: t[0])
    rebuilt = " ".join(c[1] for c in chosen)

    # If even the first sentence alone exceeds the limit, hard-truncate it.
    if len(rebuilt) > limit:
        rebuilt = rebuilt[: limit - 1].rsplit(" ", 1)[0]

    return rebuilt + ellipsis


def compress_iter(text: str, limit: int = 500) -> Iterable[str]:
    """Yield successive truncations (useful for debugging)."""
    yield compress_to_limit(text, limit)
