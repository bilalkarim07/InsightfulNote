"""Tone examples — demonstrated style per tone.

Each example shows the SAME factual shape under different presentation.
Tone changes presentation, not facts. Attribution is preserved.
"""
from __future__ import annotations


TONES: dict[str, dict[str, str]] = {
    "SERIOUS": {
        "description": "Restrained, weighty. Required for death, disaster, war, sensitive politics.",
        "example": "At least 47 people have died following the collapse of a residential building in Nairobi. Authorities have confirmed that search and rescue operations are ongoing.",
    },
    "INFORMATIVE": {
        "description": "Neutral, declarative, no editorializing.",
        "example": "Apple reported Q4 revenue of $94.9 billion, up 6% year over year. iPhone revenue reached $46.2 billion, above the consensus estimate of $43.1 billion.",
    },
    "ANALYTICAL": {
        "description": "Interpretive. Shows cause and effect. For business, finance, policy.",
        "example": "Apple's Q4 beat is driven by three factors: stronger iPhone replacement demand in China, favorable foreign exchange, and higher-margin services revenue. Each is likely to persist into Q1.",
    },
    "CONVERSATIONAL": {
        "description": "Direct, friendly. Short sentences, contractions.",
        "example": "Apple just posted its Q4 numbers. Revenue hit $94.9 billion — up 6% from a year ago. iPhone sales crushed expectations at $46.2 billion.",
    },
    "ENTHUSIASTIC": {
        "description": "Positive but not exaggerated. Never invents superlatives.",
        "example": "Apple's Q4 is in — and it's a strong one. Revenue climbed 6% to $94.9 billion, with iPhone sales beating expectations.",
    },
    "HUMOROUS": {
        "description": "Light, wry. NEVER for tragedy, war, disaster, death, or sensitive politics.",
        "example": "Apple's Q4 earnings are out, and yes — the iPhone still prints money. $46.2 billion in iPhone revenue alone, beating expectations by roughly $3 billion.",
    },
    "SARCASTIC": {
        "description": "Ironic edge. NEVER for tragedy, war, disaster, death, or sensitive politics.",
        "example": "Apple reported $94.9 billion in revenue, up 6% year over year. Shocking absolutely no one who has watched the last fifteen years of iPhone sales.",
    },
}


SENSITIVE_TONES = {"SERIOUS", "INFORMATIVE", "ANALYTICAL"}
LIGHT_TONES = {"INFORMATIVE", "ANALYTICAL", "CONVERSATIONAL", "ENTHUSIASTIC"}


def allowed_tones(subject: str, sensitive: bool) -> list[str]:
    """Return the list of tones allowed for the given subject."""
    if sensitive:
        return sorted(SENSITIVE_TONES)
    return sorted(LIGHT_TONES | {"HUMOROUS", "SARCASTIC"})


def example_for(tone: str) -> str:
    return TONES.get(tone, TONES["INFORMATIVE"])["example"]


def description_for(tone: str) -> str:
    return TONES.get(tone, TONES["INFORMATIVE"])["description"]