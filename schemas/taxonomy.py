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
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Literal, Optional, TypedDict


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


PRODUCTION_CATEGORY_ALLOWLIST = frozenset(
    category.value for category in Category if category is not Category.SPORTS
)


class ArticleQuality(TypedDict):
    categories: list[str]
    primary_category: Optional[str]
    topic_fit: bool
    newsworthiness: bool
    article_quality: Literal["article", "snippet"]


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
        "major diplomatic agreement announced",
        "government announces new policy",
        "international summit decision",
        "UN Security Council decision",
        "major sanctions announced",
        "foreign policy announcement",
        "major election result",
        "major government decision",
        "major legislation approved",
        "international institution decision",
    ],
    Category.WAR_CONFLICT: [
        "military operation announced",
        "ceasefire agreement announced",
        "peace talks conflict",
        "military escalation",
        "armed conflict developments",
        "major battlefield development",
        "military offensive announced",
        "conflict diplomacy agreement",
    ],
    Category.ARTIFICIAL_INTELLIGENCE: [
        "AI model launch",
        "AI model release",
        "AI company announces",
        "AI research breakthrough",
        "AI agents announcement",
        "AI safety research",
        "AI regulation decision",
        "AI legislation approved",
        "AI copyright ruling",
        "AI chip announcement",
        "AI data center investment",
    ],
    Category.TECHNOLOGY: [
        "semiconductor company announces",
        "new chip announced",
        "major cybersecurity breach",
        "major software release",
        "data center investment",
        "cloud infrastructure expansion",
        "major technology acquisition",
        "major technology company announcement",
        "telecom infrastructure expansion",
        "hardware launch announcement",
    ],
    Category.SCIENCE: [
        "scientific discovery announced",
        "major research finding",
        "space discovery reported",
        "astronomy discovery",
        "physics research finding",
        "genetics research finding",
        "quantum research breakthrough",
    ],
    Category.HEALTH: [
        "public health decision announced",
        "health system expansion announced",
        "public health emergency declared",
        "health policy change",
    ],
    Category.MEDICAL: [
        "drug approval announced",
        "clinical trial results reported",
        "vaccine development announced",
        "medical breakthrough reported",
        "cancer research finding",
        "major disease outbreak confirmed",
        "medical device approval announced",
        "hospital system development announced",
    ],
    Category.FINANCE: [
        "central bank decision",
        "interest rate decision",
        "inflation report released",
        "stock market major move",
        "bond market development",
        "currency market development",
        "banking sector announcement",
        "oil market major development",
    ],
    Category.BUSINESS: [
        "major merger announced",
        "major acquisition announced",
        "company earnings reported",
        "company bankruptcy filed",
        "major layoffs announced",
        "CEO resignation major company",
        "major company expansion announced",
        "corporate restructuring announced",
    ],
    Category.INVESTMENTS: [
        "major investment announced",
        "major funding round announced",
        "venture capital investment announced",
        "private equity deal announced",
        "AI investment announced",
        "semiconductor investment announced",
        "energy investment announced",
        "infrastructure investment announced",
        "sovereign investment announced",
    ],
    Category.CLIMATE_ENVIRONMENT: [
        "climate agreement announced",
        "climate policy decision",
        "emissions report released",
        "renewable energy investment announced",
        "major environmental event",
        "climate research finding",
        "environmental regulation approved",
    ],
    Category.SPORTS: [
        "major tournament result",
        "championship result",
        "major player transfer announced",
        "major sports announcement",
        "Olympics result",
        "Formula 1 result",
        "major football result",
        "major cricket result",
        "major tennis result",
    ],
    Category.WORLD_EVENTS: [
        "major international event announced",
        "international organization decision",
        "cross-border agreement announced",
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
    """Classify article text against explicit controlled-topic signals."""
    if not text:
        return []
    lower = re.sub(r"\s+", " ", text.lower())
    patterns: dict[Category, tuple[str, ...]] = {
        Category.WAR_CONFLICT: (
            r"\bwar\b", r"\barmed conflict\b", r"\bceasefire\b", r"\bpeace talks\b",
            r"\bmilitary (?:operation|offensive|escalation|strike|forces?)\b",
            r"\bbattlefield\b", r"\binvasion\b", r"\bairstrike\b", r"\bmissile strike\b",
            r"\bfront line\b", r"\bhostilities\b", r"\bconflict zone\b",
        ),
        Category.ARTIFICIAL_INTELLIGENCE: (
            r"\bartificial intelligence\b", r"\bgenerative ai\b", r"\bmachine learning\b",
            r"\bai\b", r"\bllm\b", r"\blarge language model\b", r"\bai agents?\b",
            r"\bopenai\b", r"\banthropic\b", r"\bchatgpt\b", r"\bai safety\b",
            r"\bai regulation\b", r"\bai model\b",
        ),
        Category.TECHNOLOGY: (
            r"\bsemiconductor", r"\b(?:new )?chip\b", r"\bcloud infrastructure\b",
            r"\bcybersecurity\b", r"\bsoftware\b", r"\bhardware\b", r"\btelecom",
            r"\bdata cent(?:er|re)\b", r"\bconsumer technolog", r"\bransomware\b",
            r"\bsmartphone\b", r"\btechnology company\b", r"\btech company\b",
            r"\b(?:apple|google|microsoft|meta|nvidia|samsung|intel|qualcomm)\b.{0,60}\b(?:announc\w*|launch\w*|releas\w*|chip|cloud|data center|device|software|acquir\w*)",
        ),
        Category.GLOBAL_POLITICS: (
            r"\belection\b", r"\bgovernment\b", r"\bparliament\b", r"\blegislation\b",
            r"\bdiplomac", r"\bdiplomatic\b", r"\binternational relations\b",
            r"\bforeign policy\b", r"\bsanctions\b", r"\bminister\b",
            r"\bpresident\b", r"\bcongress\b", r"\bwhite house\b", r"\bregulation\b",
            r"\bsecurity council\b", r"\bunited nations\b", r"\bnato\b",
        ),
        Category.FINANCE: (
            r"\binterest rates?\b", r"\bcentral bank\b", r"\bfederal reserve\b",
            r"\binflation\b", r"\bfinancial markets?\b", r"\bstock market\b",
            r"\bbond markets?\b", r"\bcurrenc(?:y|ies)\b", r"\bcommodit(?:y|ies)\b",
            r"\bbanking sector\b", r"\bmarket (?:rally|selloff|surge|plunge)\b",
            r"\boil (?:prices?|market)\b", r"\bgold prices?\b",
            r"\beconomic indicator\b", r"\bgdp\b",
        ),
        Category.INVESTMENTS: (
            r"\bmajor investment\b", r"\bventure capital\b", r"\bprivate equity\b",
            r"\bfunding round\b", r"\bcapital raise\b", r"\bsovereign (?:wealth )?fund\b",
            r"\binfrastructure investment\b", r"\b(?:energy|semiconductor|ai) investment\b",
            r"\binvestment of\b",
        ),
        Category.BUSINESS: (
            r"\bmerger\b", r"\bacquisition\b", r"\bearnings\b", r"\bbankruptcy\b",
            r"\blayoffs?\b", r"\bcorporate restructuring\b", r"\bceo\b",
            r"\bcompany (?:announced|expands?|acquired|filed)\b", r"\bbusiness deal\b",
        ),
        Category.MEDICAL: (
            r"\bclinical trial\b", r"\bvaccine\b", r"\bdrug approval\b",
            r"\bfda approval\b", r"\bdisease outbreak\b", r"\bcancer research\b",
            r"\bmedical (?:discovery|device|breakthrough|research)\b",
            r"\bhospital system\b", r"\bhospital (?:opens?|expands?|closes?|announces?)\b",
            r"\bpatient results\b",
        ),
        Category.HEALTH: (
            r"\bpublic health\b", r"\bhealth system\b", r"\bhealthcare policy\b",
            r"\bhealth ministry\b", r"\bhealth emergency\b",
        ),
        Category.SCIENCE: (
            r"\bscientific (?:discovery|finding|research)\b", r"\bresearch finding\b",
            r"\bspace (?:discovery|mission|telescope)\b", r"\bastronomy\b",
            r"\bphysics\b", r"\bgenetics?\b", r"\bquantum (?:research|discovery|science)\b",
            r"\bbiolog(?:y|ical)\b", r"\bscientists? (?:discover|find|report)\b",
        ),
        Category.CLIMATE_ENVIRONMENT: (
            r"\bclimate (?:agreement|policy|research|change|summit)\b",
            r"\bemissions report\b", r"\brenewable energy\b", r"\bcarbon emissions\b",
            r"\benvironmental (?:event|regulation|policy)\b", r"\bwildfire\b",
            r"\bextreme (?:heat|weather|flooding)\b",
        ),
        Category.SPORTS: (
            r"\bchampions league\b", r"\b(?:nba|nfl|fifa)\b", r"\bolympics?\b",
            r"\bformula 1\b", r"\bf1\b", r"\bcricket\b", r"\btennis\b",
            r"\bfootball\b", r"\bsoccer\b", r"\bchampionship\b",
            r"\btournament\b", r"\bmatch result\b", r"\btransfer\b",
        ),
        Category.WORLD_EVENTS: (
            r"\binternational summit\b", r"\binternational organization\b",
            r"\binternational event\b",
            r"\bcross-border agreement\b", r"\bglobal treaty\b",
        ),
    }
    return sorted(
        category.value
        for category, signals in patterns.items()
        if any(re.search(signal, lower) for signal in signals)
    )


def primary_category_for_text(title: str, body: str = "") -> Optional[str]:
    """Choose a primary category from article wording, never from its query."""
    priorities = (
        Category.WAR_CONFLICT, Category.ARTIFICIAL_INTELLIGENCE,
        Category.FINANCE, Category.INVESTMENTS, Category.BUSINESS,
        Category.MEDICAL, Category.HEALTH, Category.TECHNOLOGY,
        Category.SCIENCE, Category.CLIMATE_ENVIRONMENT,
        Category.SPORTS, Category.GLOBAL_POLITICS, Category.WORLD_EVENTS,
    )
    title_categories = set(infer_categories_from_text(title))
    body_categories = set(infer_categories_from_text(body))
    candidates = title_categories or body_categories
    return next((category.value for category in priorities if category.value in candidates), None)


def is_newsworthy_text(title: str, body: str = "") -> bool:
    """Require a concrete development and reject common evergreen/soft-news forms."""
    title_lower = title.lower()
    text = (title + " " + body).lower()
    excluded = (
        r"\b(opinion|editorial|op-ed|interview|explainer|what you need to know|"
        r"what to know|guide|listicle|horoscope|recipe|celebrity|lifestyle|"
        r"podcast|gaming|wikipedia|list of|most \w+|all.time|records? and stats|"
        r"standings|history of|year in review|tournaments?\s*:\s*results?|"
        r"best .{0,30} to buy|"
        r"products? to buy|review roundup)\b"
    )
    if re.search(excluded, title_lower):
        return False
    development = (
        r"\b(announc\w*|approv\w*|launch\w*|releas\w*|decid\w*|"
        r"discover\w*|find\w*|(?:reports? (?:finds?|says|shows|results?|released|issued)|report released)|ruled|ruling|"
        r"acquir\w*|merg\w*|filed|bankrupt\w*|layoff\w*|earnings|"
        r"expan\w*|invest\w*|rais\w*|fund\w*|sign\w*|"
        r"ceasefire|escalat\w*|outbreak|breach\w*|"
        r"cyberattack|outage|result|market move|market rally|market surge|"
        r"market plunge|market fall|market gain|rose|rises|fell|falls|"
        r"surged|plunged|climbed|dropped|hit record|reached record|killed|"
        r"defeats?|sets? record|votes? to|passes?|"
        r"win\w*.{0,80}\b(?:final|championship|tournament|title|cup|medal|"
        r"record|first time)\b)\b"
    )
    return bool(re.search(development, text))


def classify_article(
    *,
    title: str,
    description: str = "",
    snippet: str = "",
    content: str = "",
    source_name: str = "",
) -> ArticleQuality:
    """Return deterministic quality metadata from article fields, never its query.

    ``source_name`` is accepted for a stable ingestion interface but deliberately
    excluded from topic evidence so publisher names cannot assign categories.
    """
    del source_name
    article_text = " ".join(
        value.strip()
        for value in (title, description, snippet, content)
        if value and value.strip()
    )
    categories = sorted({
        normalized.value
        for category in infer_categories_from_text(article_text)
        if (normalized := normalize_category(category, allow_partial=False)) is not None
    })
    primary = primary_category_for_text(
        title,
        " ".join((description, snippet, content)),
    )
    if primary not in categories:
        primary = categories[0] if categories else None
    return {
        "categories": categories,
        "primary_category": primary,
        "topic_fit": bool(categories),
        "newsworthiness": is_newsworthy_text(
            title,
            " ".join((description, snippet)),
        ),
        "article_quality": "article" if len(content.strip()) >= 500 else "snippet",
    }


def is_publication_current(
    value: object,
    *,
    max_age_days: int = 30,
    now: datetime | None = None,
) -> bool:
    """Require a valid, recent publication timestamp rather than ingestion time."""
    if isinstance(value, datetime):
        published = value
    elif isinstance(value, str) and value.strip():
        try:
            published = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return False
    else:
        return False
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    published = published.astimezone(timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(timezone.utc)
    return (
        published <= reference + timedelta(days=1)
        and reference - published <= timedelta(days=max_age_days)
    )


def is_rejected_category(val: str) -> bool:
    """Return True if category string corresponds to an unwanted category."""
    if not val:
        return False
    cleaned = val.strip().upper().replace(" ", "_").replace("-", "_")
    return cleaned in REJECTED_CATEGORIES or cleaned.lower().replace("_", " ") in {
        k.lower().replace("_", " ") for k in REJECTED_CATEGORIES
    }