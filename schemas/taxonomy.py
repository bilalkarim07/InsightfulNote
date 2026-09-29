"""Category taxonomy, normalization, and category discovery configuration.

Enforces a strict controlled taxonomy for the newsroom editorial scope:
  - GLOBAL_POLITICS
  - WORLD_EVENTS
  - WAR_CONFLICT
  - ARTIFICIAL_INTELLIGENCE
  - TECHNOLOGY
  - SCIENCE
  - HEALTH
  - MEDICAL
  - FINANCE
  - BUSINESS
  - INVESTMENTS
  - CLIMATE_ENVIRONMENT
  - SPORTS
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional


class Category(str, Enum):
    GLOBAL_POLITICS = "GLOBAL_POLITICS"
    WORLD_EVENTS = "WORLD_EVENTS"
    WAR_CONFLICT = "WAR_CONFLICT"
    ARTIFICIAL_INTELLIGENCE = "ARTIFICIAL_INTELLIGENCE"
    TECHNOLOGY = "TECHNOLOGY"
    SCIENCE = "SCIENCE"
    HEALTH = "HEALTH"
    MEDICAL = "MEDICAL"
    FINANCE = "FINANCE"
    BUSINESS = "BUSINESS"
    INVESTMENTS = "INVESTMENTS"
    CLIMATE_ENVIRONMENT = "CLIMATE_ENVIRONMENT"
    SPORTS = "SPORTS"


# Unwanted categories that should be filtered out from newsroom processing.
# These are non-news or out-of-scope content forms that should never become
# normal candidates unless explicitly allowed elsewhere.
REJECTED_CATEGORIES = {
    "CELEBRITY", "ENTERTAINMENT", "GAMING", "WEATHER",
    "LOCAL_LIFESTYLE", "TV_SCHEDULES", "LIFESTYLE", "HOLLYWOOD",
    "GAMING_NEWS", "SPORTS_NEWS", "QUIZ", "HOROSCOPE", "RECIPE",
    "COUPON", "SHOPPING", "DEALS", "OPINION", "EDITORIAL", "OBITUARY",
    "WELLNESS", "FITNESS", "DIET", "PODCAST", "NEWSLETTER"
}

# Synonyms and mapping rules for normalization.
_CATEGORY_MAPPINGS: dict[str, Category] = {
    # War and conflict
    "war": Category.WAR_CONFLICT,
    "conflict": Category.WAR_CONFLICT,
    "armed conflict": Category.WAR_CONFLICT,
    "military conflict": Category.WAR_CONFLICT,
    "war conflict": Category.WAR_CONFLICT,
    "ceasefire": Category.WAR_CONFLICT,
    "peace talks": Category.WAR_CONFLICT,
    "ukraine war": Category.WAR_CONFLICT,
    "israel gaza": Category.WAR_CONFLICT,
    "iran war": Category.WAR_CONFLICT,
    "sudan conflict": Category.WAR_CONFLICT,
    "middle east conflict": Category.WAR_CONFLICT,
    "military escalation": Category.WAR_CONFLICT,

    # Global politics / world affairs
    "politics": Category.GLOBAL_POLITICS,
    "global politics": Category.GLOBAL_POLITICS,
    "us politics": Category.GLOBAL_POLITICS,
    "government": Category.GLOBAL_POLITICS,
    "geopolitics": Category.GLOBAL_POLITICS,
    "international politics": Category.GLOBAL_POLITICS,
    "foreign policy": Category.GLOBAL_POLITICS,
    "diplomacy": Category.GLOBAL_POLITICS,
    "policy": Category.GLOBAL_POLITICS,
    "election": Category.GLOBAL_POLITICS,
    "sanctions": Category.GLOBAL_POLITICS,
    "government policy": Category.GLOBAL_POLITICS,
    "world affairs": Category.WORLD_EVENTS,
    "world news": Category.WORLD_EVENTS,
    "world events": Category.WORLD_EVENTS,
    "international news": Category.WORLD_EVENTS,
    "global news": Category.WORLD_EVENTS,
    "breaking news": Category.WORLD_EVENTS,

    # Artificial Intelligence
    "ai": Category.ARTIFICIAL_INTELLIGENCE,
    "artificial intelligence": Category.ARTIFICIAL_INTELLIGENCE,
    "artificial-intelligence": Category.ARTIFICIAL_INTELLIGENCE,
    "ai news": Category.ARTIFICIAL_INTELLIGENCE,
    "machine learning": Category.ARTIFICIAL_INTELLIGENCE,
    "llm": Category.ARTIFICIAL_INTELLIGENCE,
    "generative ai": Category.ARTIFICIAL_INTELLIGENCE,
    "ai model": Category.ARTIFICIAL_INTELLIGENCE,
    "ai regulation": Category.ARTIFICIAL_INTELLIGENCE,
    "ai research": Category.ARTIFICIAL_INTELLIGENCE,

    # Technology
    "tech": Category.TECHNOLOGY,
    "technology": Category.TECHNOLOGY,
    "software": Category.TECHNOLOGY,
    "hardware": Category.TECHNOLOGY,
    "cybersecurity": Category.TECHNOLOGY,
    "gadgets": Category.TECHNOLOGY,
    "semiconductor": Category.TECHNOLOGY,
    "chip": Category.TECHNOLOGY,
    "cloud": Category.TECHNOLOGY,
    "data center": Category.TECHNOLOGY,
    "telecom": Category.TECHNOLOGY,
    "internet infrastructure": Category.TECHNOLOGY,

    # Finance
    "finance": Category.FINANCE,
    "economy": Category.FINANCE,
    "markets": Category.FINANCE,
    "financial markets": Category.FINANCE,
    "banking": Category.FINANCE,
    "investing": Category.FINANCE,
    "stocks": Category.FINANCE,
    "interest rates": Category.FINANCE,
    "inflation": Category.FINANCE,
    "central bank": Category.FINANCE,
    "federal reserve": Category.FINANCE,

    # Business
    "business": Category.BUSINESS,
    "companies": Category.BUSINESS,
    "corporate news": Category.BUSINESS,
    "startups": Category.BUSINESS,
    "commerce": Category.BUSINESS,
    "industry": Category.BUSINESS,
    "merger": Category.BUSINESS,
    "acquisition": Category.BUSINESS,
    "earnings": Category.BUSINESS,
    "layoffs": Category.BUSINESS,
    "bankruptcy": Category.BUSINESS,

    # Investments
    "investment": Category.INVESTMENTS,
    "investments": Category.INVESTMENTS,
    "venture capital": Category.INVESTMENTS,
    "private equity": Category.INVESTMENTS,
    "capital raise": Category.INVESTMENTS,
    "major investment": Category.INVESTMENTS,
    "funding round": Category.INVESTMENTS,

    # Health & Medical
    "health": Category.HEALTH,
    "medicine": Category.HEALTH,
    "healthcare": Category.HEALTH,
    "medical news": Category.HEALTH,
    "public health": Category.HEALTH,
    "wellness": Category.HEALTH,
    "disease": Category.MEDICAL,
    "medical": Category.MEDICAL,
    "clinical trial": Category.MEDICAL,
    "hospital": Category.MEDICAL,
    "vaccine": Category.MEDICAL,
    "drug": Category.MEDICAL,
    "fda": Category.MEDICAL,
    "who": Category.MEDICAL,
    "cancer": Category.MEDICAL,
    "health research": Category.HEALTH,

    # Science
    "science": Category.SCIENCE,
    "scientific research": Category.SCIENCE,
    "space": Category.SCIENCE,
    "astronomy": Category.SCIENCE,
    "physics": Category.SCIENCE,
    "biology": Category.SCIENCE,
    "quantum": Category.SCIENCE,
    "genetics": Category.SCIENCE,
    "research": Category.SCIENCE,
    "breakthrough": Category.SCIENCE,

    # Climate / Environment
    "climate": Category.CLIMATE_ENVIRONMENT,
    "environment": Category.CLIMATE_ENVIRONMENT,
    "climate change": Category.CLIMATE_ENVIRONMENT,
    "global warming": Category.CLIMATE_ENVIRONMENT,
    "clean energy": Category.CLIMATE_ENVIRONMENT,
    "extreme weather": Category.CLIMATE_ENVIRONMENT,
    "emissions": Category.CLIMATE_ENVIRONMENT,
    "renewable energy": Category.CLIMATE_ENVIRONMENT,
    "carbon": Category.CLIMATE_ENVIRONMENT,

    # Sports
    "sports": Category.SPORTS,
    "soccer": Category.SPORTS,
    "football": Category.SPORTS,
    "nba": Category.SPORTS,
    "nfl": Category.SPORTS,
    "tennis": Category.SPORTS,
    "cricket": Category.SPORTS,
    "olympics": Category.SPORTS,
    "f1": Category.SPORTS,
    "formula 1": Category.SPORTS,
    "transfer": Category.SPORTS,
    "injury update": Category.SPORTS,
    "championship": Category.SPORTS,
    "tournament": Category.SPORTS,
}


# Category-specific discovery queries (Section 9 of amendments.md).
# Keep the family-specific query sets explicit so discovery stays editorially
# focused rather than broad and generic.
CATEGORY_DISCOVERY_QUERIES: dict[Category, list[str]] = {
    Category.GLOBAL_POLITICS: [
        "global politics latest",
        "international diplomacy latest",
        "major government decisions today",
        "international relations latest",
        "US foreign policy latest",
        "Europe politics latest",
        "China politics latest",
        "Russia politics latest",
        "Middle East diplomacy latest",
        "UN diplomacy latest",
        "G7 G20 diplomacy latest",
        "US Iran talks",
        "Trump Iran negotiations",
        "Russia Ukraine diplomacy",
        "China Taiwan tensions",
        "NATO latest",
        "UN Security Council latest",
    ],
    Category.WAR_CONFLICT: [
        "war latest",
        "armed conflict latest",
        "military conflict latest",
        "Ukraine war latest",
        "Russia Ukraine latest",
        "Israel Gaza latest",
        "Israel Iran latest",
        "Iran war latest",
        "Middle East conflict latest",
        "Sudan conflict latest",
        "Yemen conflict latest",
        "Syria conflict latest",
        "military escalation latest",
        "ceasefire latest",
        "peace talks conflict latest",
    ],
    Category.ARTIFICIAL_INTELLIGENCE: [
        "AI latest",
        "OpenAI latest",
        "Anthropic latest",
        "Google AI latest",
        "Microsoft AI latest",
        "Meta AI latest",
        "Nvidia AI latest",
        "AI company announcement",
        "AI model release",
        "AI product launch",
        "AI research breakthrough",
        "AI research latest",
        "machine learning breakthrough",
        "large language model research",
        "AI safety research",
        "AI agents research",
        "AI robotics research",
        "AI healthcare latest",
        "AI science latest",
        "AI finance latest",
        "AI cybersecurity latest",
        "AI education latest",
        "AI coding latest",
        "AI agents latest",
        "AI regulation latest",
        "AI policy latest",
        "AI legislation latest",
        "AI governance latest",
        "AI copyright latest",
        "AI safety regulation latest",
    ],
    Category.TECHNOLOGY: [
        "semiconductor latest",
        "chip industry latest",
        "CPU GPU latest",
        "quantum computing latest",
        "cloud computing latest",
        "data center latest",
        "Apple latest",
        "Samsung latest",
        "Google technology latest",
        "Microsoft technology latest",
        "smartphone technology latest",
        "consumer electronics latest",
        "cybersecurity breach latest",
        "major cyber attack latest",
        "security vulnerability latest",
        "ransomware attack latest",
        "data center expansion",
        "cloud infrastructure latest",
        "internet infrastructure latest",
        "telecom technology latest",
    ],
    Category.SCIENCE: [
        "major science breakthrough",
        "scientific discovery latest",
        "physics research latest",
        "astronomy discovery latest",
        "space science latest",
        "biology research latest",
        "genetics research latest",
        "quantum science latest",
        "climate science latest",
    ],
    Category.HEALTH: [
        "health latest",
        "public health latest",
        "WHO health latest",
        "health research latest",
    ],
    Category.MEDICAL: [
        "medical breakthrough latest",
        "clinical trial latest",
        "cancer research latest",
        "infectious disease latest",
        "vaccine research latest",
        "drug trial latest",
        "medical technology latest",
        "FDA approval latest",
    ],
    Category.FINANCE: [
        "global markets latest",
        "stock market latest",
        "Federal Reserve latest",
        "ECB latest",
        "interest rates latest",
        "inflation latest",
        "bond markets latest",
        "currency markets latest",
        "oil prices latest",
        "gold prices latest",
        "banking sector latest",
        "financial markets latest",
    ],
    Category.BUSINESS: [
        "global business latest",
        "major corporate announcement",
        "merger acquisition latest",
        "CEO resignation major company",
        "corporate earnings latest",
        "company bankruptcy latest",
        "major company expansion",
        "major layoffs latest",
        "industry investment latest",
    ],
    Category.INVESTMENTS: [
        "major investment announcement",
        "venture capital latest",
        "private equity latest",
        "major tech investment",
        "infrastructure investment latest",
        "sovereign wealth investment latest",
        "AI investment latest",
        "semiconductor investment latest",
        "energy investment latest",
    ],
    Category.CLIMATE_ENVIRONMENT: [
        "climate policy latest",
        "climate change latest",
        "global warming latest",
        "extreme weather latest",
        "climate science latest",
        "environmental policy latest",
        "renewable energy latest",
        "clean energy investment latest",
        "carbon emissions latest",
        "climate summit latest",
    ],
    Category.SPORTS: [
        "sports latest",
        "football latest",
        "soccer latest",
        "NBA latest",
        "NFL latest",
        "FIFA latest",
        "Champions League latest",
        "Olympics latest",
        "Formula 1 latest",
        "cricket latest",
        "tennis latest",
    ],
    Category.WORLD_EVENTS: [
        "world events latest",
        "international news latest",
        "global news latest",
        "breaking international developments latest",
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
    upper_clean = val.strip().upper().replace(" ", "_").replace("-", "_")
    if upper_clean in REJECTED_CATEGORIES or cleaned in {k.lower().replace("_", " ") for k in REJECTED_CATEGORIES}:
        return None

    # Check exact enum value.
    try:
        return Category(upper_clean)
    except ValueError:
        pass

    # Check mapping.
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


def infer_categories_from_text(text: str) -> list[str]:
    """Heuristic text-based category classification for newsroom discovery."""
    if not text:
        return []
    lower = text.lower()
    terms = re.findall(r"[a-z0-9]+", lower)
    if not terms:
        return []

    matches: set[str] = set()

    # Content-based signal detection; avoid returning AI for every technology story.
    if any(word in lower for word in ["ai ", "artificial intelligence", "llm", "generative ai", "machine learning", "chatgpt", "model release", "ai model", "ai research", "ai regulation", "ai safety"]):
        matches.add(Category.ARTIFICIAL_INTELLIGENCE.value)
    if any(word in lower for word in ["semiconductor", "chip", "cpu", "gpu", "cloud", "data center", "cybersecurity", "telecom", "software", "smartphone", "consumer electronics", "ransomware", "security vulnerability"]):
        matches.add(Category.TECHNOLOGY.value)
    if any(word in lower for word in ["war", "conflict", "ceasefire", "missile", "troop", "attack", "evacuation", "sanctions", "diplomacy", "state department", "nato", "security council"]):
        matches.add(Category.WAR_CONFLICT.value)
    if any(word in lower for word in ["election", "government", "parliament", "policy", "foreign minister", "diplomacy", "sanctions", "united nations", "nato", "g7", "g20"]):
        matches.add(Category.GLOBAL_POLITICS.value)
    if any(word in lower for word in ["interest rate", "inflation", "federal reserve", "ecb", "bond", "currency", "stock market", "oil prices", "gold prices", "banking", "markets"]):
        matches.add(Category.FINANCE.value)
    if any(word in lower for word in ["merger", "acquisition", "earnings", "layoff", "bankruptcy", "ceo", "corporate", "company", "startup", "industry"]):
        matches.add(Category.BUSINESS.value)
    if any(word in lower for word in ["investment", "venture capital", "private equity", "funding", "capital raise", "infrastructure investment", "ai investment"]):
        matches.add(Category.INVESTMENTS.value)
    if any(word in lower for word in ["clinical trial", "patient", "fda", "who", "vaccine", "cancer", "disease", "hospital", "medical", "drug"]):
        matches.add(Category.MEDICAL.value)
    if any(word in lower for word in ["health", "public health", "healthcare"]):
        matches.add(Category.HEALTH.value)
    if any(word in lower for word in ["science", "research", "discovery", "quantum", "telescope", "biology", "genetics", "astronomy", "physics", "breakthrough"]):
        matches.add(Category.SCIENCE.value)
    if any(word in lower for word in ["climate", "carbon", "emissions", "global warming", "renewable energy", "extreme weather", "flood", "wildfire", "heatwave", "environment"]):
        matches.add(Category.CLIMATE_ENVIRONMENT.value)
    if any(word in lower for word in ["arsenal", "liverpool", "soccer", "football", "nba", "nfl", "olympics", "cricket", "tennis", "transfer", "goal", "injury", "match", "tournament", "championship"]):
        matches.add(Category.SPORTS.value)

    # Add world events if the item is general/current news but not deep in a narrow family.
    if "latest" in lower or "breaking" in lower or "global" in lower:
        if not matches:
            matches.add(Category.WORLD_EVENTS.value)

    return sorted(matches)


def is_rejected_category(val: str) -> bool:
    """Return True if category string corresponds to an unwanted category."""
    if not val:
        return False
    cleaned = val.strip().upper().replace(" ", "_").replace("-", "_")
    return cleaned in REJECTED_CATEGORIES or cleaned.lower().replace("_", " ") in {
        k.lower().replace("_", " ") for k in REJECTED_CATEGORIES
    }