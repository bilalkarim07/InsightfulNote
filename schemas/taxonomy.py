"""Category taxonomy, normalization, and category discovery configuration.

Enforces strict controlled taxonomy identifiers:
  - GLOBAL_POLITICS
  - FINANCE
  - BUSINESS
  - TECHNOLOGY
  - ARTIFICIAL_INTELLIGENCE
  - HEALTH
  - SCIENCE
  - CLIMATE_ENVIRONMENT
  - WORLD_EVENTS
"""
from __future__ import annotations

from enum import Enum
from typing import Optional


class Category(str, Enum):
    GLOBAL_POLITICS = "GLOBAL_POLITICS"
    FINANCE = "FINANCE"
    BUSINESS = "BUSINESS"
    TECHNOLOGY = "TECHNOLOGY"
    ARTIFICIAL_INTELLIGENCE = "ARTIFICIAL_INTELLIGENCE"
    HEALTH = "HEALTH"
    SCIENCE = "SCIENCE"
    CLIMATE_ENVIRONMENT = "CLIMATE_ENVIRONMENT"
    WORLD_EVENTS = "WORLD_EVENTS"


# Unwanted categories that should be filtered out from newsroom processing
REJECTED_CATEGORIES = {
    "SPORTS", "CELEBRITY", "ENTERTAINMENT", "GAMING", "WEATHER",
    "LOCAL_LIFESTYLE", "TV_SCHEDULES", "LIFESTYLE", "HOLLYWOOD",
    "GAMING_NEWS", "SPORTS_NEWS"
}

# Synonyms and mapping rules for normalization
_CATEGORY_MAPPINGS: dict[str, Category] = {
    # Artificial Intelligence
    "ai": Category.ARTIFICIAL_INTELLIGENCE,
    "artificial intelligence": Category.ARTIFICIAL_INTELLIGENCE,
    "artificial-intelligence": Category.ARTIFICIAL_INTELLIGENCE,
    "ai news": Category.ARTIFICIAL_INTELLIGENCE,
    "machine learning": Category.ARTIFICIAL_INTELLIGENCE,
    "llm": Category.ARTIFICIAL_INTELLIGENCE,
    "generative ai": Category.ARTIFICIAL_INTELLIGENCE,

    # Technology
    "tech": Category.TECHNOLOGY,
    "technology": Category.TECHNOLOGY,
    "software": Category.TECHNOLOGY,
    "hardware": Category.TECHNOLOGY,
    "cybersecurity": Category.TECHNOLOGY,
    "gadgets": Category.TECHNOLOGY,

    # Global Politics
    "politics": Category.GLOBAL_POLITICS,
    "global politics": Category.GLOBAL_POLITICS,
    "us politics": Category.GLOBAL_POLITICS,
    "government": Category.GLOBAL_POLITICS,
    "geopolitics": Category.GLOBAL_POLITICS,
    "international politics": Category.GLOBAL_POLITICS,
    "policy": Category.GLOBAL_POLITICS,

    # Finance
    "finance": Category.FINANCE,
    "economy": Category.FINANCE,
    "markets": Category.FINANCE,
    "financial markets": Category.FINANCE,
    "banking": Category.FINANCE,
    "investing": Category.FINANCE,
    "stocks": Category.FINANCE,

    # Business
    "business": Category.BUSINESS,
    "companies": Category.BUSINESS,
    "corporate news": Category.BUSINESS,
    "startups": Category.BUSINESS,
    "commerce": Category.BUSINESS,
    "industry": Category.BUSINESS,

    # Health
    "health": Category.HEALTH,
    "medicine": Category.HEALTH,
    "healthcare": Category.HEALTH,
    "medical news": Category.HEALTH,
    "public health": Category.HEALTH,

    # Science
    "science": Category.SCIENCE,
    "scientific research": Category.SCIENCE,
    "space": Category.SCIENCE,
    "astronomy": Category.SCIENCE,
    "physics": Category.SCIENCE,
    "biology": Category.SCIENCE,

    # Climate / Environment
    "climate": Category.CLIMATE_ENVIRONMENT,
    "environment": Category.CLIMATE_ENVIRONMENT,
    "climate change": Category.CLIMATE_ENVIRONMENT,
    "global warming": Category.CLIMATE_ENVIRONMENT,
    "clean energy": Category.CLIMATE_ENVIRONMENT,

    # World Events
    "world news": Category.WORLD_EVENTS,
    "world events": Category.WORLD_EVENTS,
    "international news": Category.WORLD_EVENTS,
    "global news": Category.WORLD_EVENTS,
    "breaking news": Category.WORLD_EVENTS,
}

# Category-specific discovery queries (Section 9 of ammendments.md)
CATEGORY_DISCOVERY_QUERIES: dict[Category, list[str]] = {
    Category.GLOBAL_POLITICS: [
        "global politics latest",
        "international politics latest",
        "US politics latest",
        "government policy latest",
    ],
    Category.FINANCE: [
        "markets latest",
        "economy latest",
        "financial markets latest",
    ],
    Category.BUSINESS: [
        "companies latest",
        "corporate news latest",
        "business latest",
    ],
    Category.TECHNOLOGY: [
        "technology latest",
        "technology companies latest",
    ],
    Category.ARTIFICIAL_INTELLIGENCE: [
        "artificial intelligence latest",
        "AI companies latest",
        "AI models latest",
    ],
    Category.HEALTH: [
        "health latest",
        "medical news latest",
        "healthcare latest",
    ],
    Category.SCIENCE: [
        "science latest",
        "scientific research latest",
    ],
    Category.CLIMATE_ENVIRONMENT: [
        "climate latest",
        "environment latest",
    ],
    Category.WORLD_EVENTS: [
        "world events latest",
        "international news latest",
    ],
}


def normalize_category(
    val: str,
    *,
    allow_partial: bool = True,
) -> Optional[Category]:
    """Normalize a category, optionally skipping fuzzy partial matching."""
    if not val or not isinstance(val, str):
        return None
    cleaned = val.strip().lower().replace("_", " ")
    if cleaned in REJECTED_CATEGORIES or val.upper() in REJECTED_CATEGORIES:
        return None

    # Check exact enum value
    try:
        return Category(val.upper().replace(" ", "_").replace("-", "_"))
    except ValueError:
        pass

    # Check mapping
    if cleaned in _CATEGORY_MAPPINGS:
        return _CATEGORY_MAPPINGS[cleaned]

    if allow_partial:
        for key, mapped_cat in _CATEGORY_MAPPINGS.items():
            if key in cleaned or cleaned in key:
                return mapped_cat

    return None


def normalize_categories(vals: list[str]) -> list[str]:
    """Normalize a list of category strings into deduplicated canonical Category value strings."""
    result: set[str] = set()
    for item in vals:
        cat = normalize_category(item)
        if cat is not None:
            result.add(cat.value)
    return sorted(list(result))


def is_rejected_category(val: str) -> bool:
    """Return True if category string corresponds to an unwanted category (sports, celebrity, etc.)."""
    if not val:
        return False
    cleaned = val.strip().upper().replace(" ", "_")
    return cleaned in REJECTED_CATEGORIES
