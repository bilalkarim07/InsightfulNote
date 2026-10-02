"""Production ingestion orchestrator.

Writes to:
  sources        -- one row per configured RSS feed or search provider
  news_items     -- one row per article (idempotent by id)
  stories        -- clustered from news_items by title signature
  story_sources  -- links stories to their news_items

Idempotent: rerunning does not duplicate news_items. Stories may be
recreated (dedup of stories is a later concern).

Fail-soft: one source failing does not stop the others.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from core.tools.database import stories as db  # noqa: E402


from schemas.taxonomy import (
    PRODUCTION_CATEGORY_ALLOWLIST, classify_article,
    infer_categories_from_text, is_newsworthy_text, normalize_category,
    is_publication_current, primary_category_for_text,
)
from extraction.canonicalization.url import canonicalize_url
from sources.rss.registry import load_rss_registry

# Direct RSS configuration stays separate from orchestration and is validated
# against the fixed production taxonomy before it can enter the pipeline.
RSS_FEEDS: list[dict[str, Any]] = [
    feed.__dict__ for feed in load_rss_registry()
]

FALLBACK_DISCOVERY_QUERIES = [
    "major government decision or international agreement",
    "major armed conflict or ceasefire development",
    "significant artificial intelligence or cybersecurity announcement",
    "major technology or semiconductor development",
    "important scientific or medical research finding",
    "major financial market or central bank development",
    "significant corporate announcement or bankruptcy",
    "major climate or environmental development",
    "major international event or diplomatic development",
]
GDELT_DISCOVERY_QUERIES = FALLBACK_DISCOVERY_QUERIES[:4]
_GDELT_MAX_QUERY_LIMIT = max(
    1, int(os.environ.get("NEWSROOM_GDELT_MAX_QUERIES", "4"))
)
_CLUSTER_WINDOW_HOURS = min(
    168,
    max(1, int(os.environ.get("NEWSROOM_CLUSTER_WINDOW_HOURS", "36"))),
)

INGESTION_METRICS: dict[str, dict[str, int]] = {}
TAXONOMY_ACCEPTED: dict[str, int] = {}
TAXONOMY_REJECTED: dict[str, int] = {}


def _metric(provider: str, name: str, amount: int = 1) -> None:
    metrics = INGESTION_METRICS.setdefault(provider, {})
    metrics[name] = metrics.get(name, 0) + amount


PROVIDERS = {
    "tavily":      {"source_type": "search_api", "domain": "tavily.com"},
    "ddgs":        {"source_type": "search_api", "domain": "duckduckgo.com"},
    "google_news": {"source_type": "rss",        "domain": "news.google.com"},
    "gdelt":       {"source_type": "api",        "domain": "gdeltproject.org"},
}
for _feed in RSS_FEEDS:
    PROVIDERS[_feed["id"]] = {
        "source_type": "rss",
        "domain": _feed["publisher_domain"],
        "base_url": _feed["url"],
    }


def _tag_discovery(items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Attach discovery provenance; it is never used as article evidence."""
    for item in items:
        item["discovery_query"] = query
    return items


def _strict_normalize_categories(values: list[Any]) -> list[str]:
    normalized = {
        category.value
        for value in values
        if (category := normalize_category(str(value), allow_partial=False)) is not None
    }
    return sorted(normalized)


def _parse_publication_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(raw)
            except (TypeError, ValueError, OverflowError):
                return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _item_to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    if hasattr(item, "__dataclass_fields__"):
        from dataclasses import asdict
        return asdict(item)
    if hasattr(item, "__dict__"):
        return dict(item.__dict__)
    return {"value": str(item)}


def _iter_items(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if hasattr(raw, "items"):
        items = getattr(raw, "items") or []
        return [_item_to_dict(x) for x in items]
    if isinstance(raw, list):
        return [_item_to_dict(x) for x in raw]
    if isinstance(raw, dict):
        for key in ("items", "results", "articles", "data"):
            v = raw.get(key)
            if isinstance(v, list):
                return [_item_to_dict(x) for x in v]
    return []


_SKIP_URL_RE = re.compile(
    r"(apps\.apple\.com|play\.google\.com|microsoft\.com/store|"
    r"chrome\.google\.com/webstore|download)",
    re.IGNORECASE,
)

_PORTAL_PATH_BLOCKLIST = re.compile(
    r"(^/$|^/news/?$|^/breaking-news/?$|^/world/?$|^/us/?$|^/politics/?$|"
    r"^/business/?$|^/technology/?$|^/tech/?$|^/entertainment/?$|"
    r"^/sports/?$|^/health/?$|^/science/?$|^/latest/?$|^/top-stories/?$|"
    r"^/home/?$|^/index\.html?$)",
    re.IGNORECASE,
)

_PORTAL_TITLE_BLOCKLIST = re.compile(
    r"^(Breaking News, Latest News|Latest News, Breaking News|"
    r"Breaking News & Top Stories|Top World News|"
    r"[A-Z][a-zA-Z]+ (News|Breaking News)( [-,:|]|$))",
    re.IGNORECASE,
)


def _is_portal_url(url: str) -> bool:
    """Return True if the URL looks like a publisher homepage/portal."""
    try:
        from urllib.parse import urlparse
        p = urlparse(url)
        path = p.path or "/"
        # A portal is a domain root or a well-known section landing page.
        if _PORTAL_PATH_BLOCKLIST.match(path):
            return True
        # Paths with no segments beyond the domain are portals.
        segments = [s for s in path.split("/") if s]
        if len(segments) == 0:
            return True
        return False
    except Exception:
        return False


def _is_valid_article(item: dict[str, Any]) -> bool:
    url = (item.get("url") or item.get("canonical_url") or "").strip()
    title = (item.get("title") or "").strip()
    if not url or not title:
        return False
    if len(title) < 15:
        return False
    if _SKIP_URL_RE.search(url):
        return False
    if _is_portal_url(url):
        return False
    if _PORTAL_TITLE_BLOCKLIST.match(title):
        return False
    return True


_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at",
    "for", "with", "by", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "as", "from", "will",
    "has", "have", "had", "not", "no", "breaking", "live", "updates",
    "just", "news", "today", "latest", "new", "says", "said", "update",
    "watch", "video", "photos", "photo",
}


def _normalize_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _title_signature(title: str) -> str:
    """Stable key used to group news_items into stories."""
    norm = _normalize_title(title)
    tokens = [w for w in norm.split() if w not in _STOPWORDS and len(w) > 2]
    tokens = sorted(tokens)[:8]
    if not tokens:
        tokens = norm.split()[:4]
    return " ".join(tokens)


def _signature_hash(sig: str) -> str:
    return hashlib.sha256(sig.encode()).hexdigest()[:16]


def _tavily_items() -> list[dict[str, Any]]:
    if os.environ.get("NEWSROOM_ENABLE_TAVILY", "").strip().lower() not in {
        "1", "true", "yes",
    }:
        return []
    from sources.tavily import TavilyClient
    out: list[dict[str, Any]] = []
    client = TavilyClient()
    try:
        for q in FALLBACK_DISCOVERY_QUERIES:
            _metric("tavily", "requests")
            items = _iter_items(client.search(q))
            _metric("tavily", "items_fetched", len(items))
            out.extend(_tag_discovery(items, q))
    finally:
        try: client.close()
        except Exception: pass
    return out


def _ddgs_items() -> list[dict[str, Any]]:
    from sources.ddgs import DDGSClient
    out: list[dict[str, Any]] = []
    client = DDGSClient()
    try:
        for q in FALLBACK_DISCOVERY_QUERIES:
            _metric("ddgs", "queries")
            try:
                items = _iter_items(client.news_search(q))
            except Exception as exc:
                _metric("ddgs", "failures")
                print(f"  [ingest] DDGS query failed: {type(exc).__name__}")
                continue
            _metric("ddgs", "items_fetched", len(items))
            out.extend(_tag_discovery(items, q))
    finally:
        try: client.close()
        except Exception: pass
    return out


def _google_news_items() -> list[dict[str, Any]]:
    from sources.google_news import GoogleNewsClient
    out: list[dict[str, Any]] = []
    client = GoogleNewsClient()
    try:
        for q in FALLBACK_DISCOVERY_QUERIES:
            _metric("google_news", "queries")
            try:
                items = _iter_items(client.search(q))
            except Exception as exc:
                _metric("google_news", "failures")
                print(f"  [ingest] Google News query failed: {type(exc).__name__}")
                continue
            _metric("google_news", "items_fetched", len(items))
            out.extend(_tag_discovery(items, q))
    finally:
        try: client.close()
        except Exception: pass
    return out


def _gdelt_items() -> list[dict[str, Any]]:
    from sources.gdelt import GDELTClient
    from core.exceptions import SourceRateLimitError

    out: list[dict[str, Any]] = []
    client = GDELTClient()
    queries = GDELT_DISCOVERY_QUERIES[:_GDELT_MAX_QUERY_LIMIT]
    try:
        for idx, q in enumerate(queries):
            if idx > 0:
                time.sleep(max(2.0, float(os.environ.get(
                    "NEWSROOM_GDELT_MIN_DELAY_SECONDS", "2"
                ))))
            _metric("gdelt", "queries")
            try:
                items = _iter_items(client.search(q))
            except SourceRateLimitError:
                _metric("gdelt", "rate_limits")
                _metric("gdelt", "failures")
                print("  [ingest] GDELT rate limited; continuing with next source")
                continue
            except Exception as exc:
                _metric("gdelt", "failures")
                print(f"  [ingest] GDELT query failed: {type(exc).__name__}")
                continue
            _metric("gdelt", "items_fetched", len(items))
            out.extend(_tag_discovery(items, q))
    finally:
        try: client.close()
        except Exception: pass
    return out


def _canonical_article_url(url: Any) -> str:
    if not isinstance(url, str) or not url.strip():
        return ""
    try:
        return canonicalize_url(url.strip())
    except Exception:
        return url.strip().casefold()


def _rss_items(feed: dict[str, Any]) -> list[dict[str, Any]]:
    from sources.rss import RSSClient

    with RSSClient(timeout=20.0) as client:
        result = client.fetch(feed["url"])
    items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for normalized in result.items:
        item = normalized.model_dump(mode="json")
        key = _canonical_article_url(item.get("canonical_url") or item.get("url"))
        if not key or key in seen_urls:
            _metric(feed["id"], "duplicates")
            continue
        seen_urls.add(key)
        publisher_name = item.get("source_name") or ""
        if "://" in publisher_name:
            publisher_name = ""
        item["publisher_name"] = publisher_name or feed["name"]
        item["source_name"] = publisher_name or feed["name"]
        item["publisher_domain"] = feed["publisher_domain"]
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["publisher_name"] = metadata.get("publisher_name") or feed["name"]
        metadata["publisher_domain"] = feed["publisher_domain"]
        metadata["registry_category"] = feed["category"]
        metadata["feed_priority"] = feed["priority"]
        item["metadata"] = metadata
        items.append(item)
    _metric(feed["id"], "items_fetched", len(result.items))
    return items


SOURCES: list[tuple[str, Callable[[], list[dict[str, Any]]]]] = [
    (feed["id"], lambda feed=feed: _rss_items(feed))
    for feed in RSS_FEEDS
]
SOURCES.extend([
    ("google_news", _google_news_items),
    ("ddgs", _ddgs_items),
    ("gdelt", _gdelt_items),
])
if os.environ.get("NEWSROOM_ENABLE_TAVILY", "").strip().lower() in {
    "1", "true", "yes",
}:
    SOURCES.append(("tavily", _tavily_items))


def _build_news_item(
    item: dict[str, Any], provider: str, source_uuid: str,
) -> dict[str, Any] | None:
    url = (item.get("article_url") or item.get("url") or item.get("canonical_url") or "").strip()
    if not url:
        return None
    canonical = (item.get("canonical_url") or url).strip()
    canonical_host = (urlparse(canonical).hostname or "").lower()
    if not canonical_host or canonical_host == "news.google.com" or canonical_host.endswith(".google.com"):
        canonical = url
    title = (item.get("title") or "").strip()
    description = str(item.get("description") or "")
    snippet = str(item.get("snippet") or "")
    content = str(item.get("content") or "")
    raw_metadata = item.get("metadata")
    item_metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    quality = classify_article(
        title=title,
        description=description,
        snippet=snippet,
        content=content,
        source_name=str(item.get("source_name") or ""),
    )
    norm_cats = [
        category for category in quality["categories"]
        if category in PRODUCTION_CATEGORY_ALLOWLIST
    ]
    if not norm_cats:
        return None
    primary = quality["primary_category"]

    hostname = (urlparse(url).hostname or "").lower().removeprefix("www.")
    publisher_name = (
        item.get("publisher_name")
        or item_metadata.get("publisher_name")
        or item.get("source_name")
        or hostname
    )
    publisher_name = str(publisher_name).strip()
    name_url = publisher_name if "://" in publisher_name else "//" + publisher_name
    candidate_host = (urlparse(name_url).hostname or "").lower()
    if candidate_host.endswith("google.com") or (
        provider == "google_news" and publisher_name.lower() in ("google news", "google news rss")
    ):
        publisher_name = hostname
    publisher_domain = str(
        item.get("publisher_domain")
        or item_metadata.get("publisher_domain")
        or item.get("source_domain")
        or hostname
    ).lower().removeprefix("www.")
    if publisher_domain.endswith("google.com"):
        publisher_domain = hostname
    topic_fit = bool(quality["topic_fit"])
    newsworthy = bool(quality["newsworthiness"])
    if not topic_fit or not newsworthy:
        return None

    return {
        "url": url,
        "canonical_url": canonical,
        "title": title,
        "description": description,
        "snippet": snippet,
        "source_id": source_uuid,
        "source_name": publisher_name,
        "source_domain": publisher_domain,
        "author": item.get("author") or None,
        "published_at": item.get("published_at") or None,
        "content": content or None,
        "language": item.get("language") or "en",
        "country": item.get("country") or None,
        "categories": norm_cats,
        "metadata": {
            "provider": provider,
            "discovery_provider": provider,
            "article_url": url,
            "publisher_name": publisher_name,
            "publisher_domain": publisher_domain,
            "discovery_query": item.get("discovery_query") or "",
            "primary_category": primary,
            "topic_fit": topic_fit,
            "newsworthiness": newsworthy,
            "registry_category": item_metadata.get("registry_category"),
            "feed_priority": item_metadata.get("feed_priority"),
            "article_quality": quality["article_quality"],
            "rejection_reason": None,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def _reject_reason(item: dict[str, Any], provider: str) -> str | None:
    url = (item.get("article_url") or item.get("url") or item.get("canonical_url") or "").strip()
    title = (item.get("title") or "").strip()
    if not url or not title:
        return "INSUFFICIENT_METADATA"
    parsed_url = urlparse(url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.hostname:
        return "INSUFFICIENT_METADATA"
    if _SKIP_URL_RE.search(url) or _is_portal_url(url) or _PORTAL_TITLE_BLOCKLIST.match(title):
        return "PORTAL_PAGE"
    if len(title) < 15:
        return "INSUFFICIENT_METADATA"
    title_lower = title.lower()
    if re.search(r"\b(opinion|editorial|op-ed|interview|explainer|what to know|guide)\b", title_lower):
        return "OPINION_CONTENT"
    if re.search(r"\b(sponsored|promotional|promo code|buy now|shopping deals)\b", title_lower):
        return "PROMOTIONAL_CONTENT"
    host = (parsed_url.hostname or "").lower()
    if provider == "google_news" and (
        host == "news.google.com" or host.endswith(".google.com")
    ):
        return "UNRESOLVED_PUBLISHER"
    body = " ".join(
        str(item.get(field) or "").strip()
        for field in ("description", "snippet", "content")
    ).strip()
    if len(body) < 40:
        return "INSUFFICIENT_METADATA"
    article_text = " ".join(str(item.get(field) or "") for field in ("title", "description", "snippet", "content"))
    inferred_categories = infer_categories_from_text(article_text)
    if not any(
        str(getattr(category, "value", category)) in PRODUCTION_CATEGORY_ALLOWLIST
        for category in inferred_categories
    ):
        return "OUT_OF_SCOPE"
    if not is_newsworthy_text(
        title,
        " ".join(str(item.get(field) or "") for field in ("description", "snippet")),
    ):
        return "NOT_NEWSWORTHY"
    item_metadata = item.get("metadata")
    if not isinstance(item_metadata, dict):
        item_metadata = {}
    extraction_metadata = item_metadata.get("article_extraction")
    if not isinstance(extraction_metadata, dict):
        extraction_metadata = {}
    published = _parse_publication_datetime(
        item.get("published_at")
        or item_metadata.get("published_date")
        or item_metadata.get("tavily_published_date")
        or extraction_metadata.get("published_at")
    )
    if published is None:
        return "INSUFFICIENT_METADATA"
    if published > datetime.now(timezone.utc) + timedelta(days=1):
        return "INSUFFICIENT_METADATA"
    max_age_days = int(os.environ.get("NEWSROOM_MAX_ARTICLE_AGE_DAYS", "30"))
    if not is_publication_current(published, max_age_days=max_age_days):
        return "STALE_ARTICLE"
    return None


def _enrich_article(
    item: dict[str, Any], provider: str, *, extract_content: bool = True,
) -> dict[str, Any]:
    """Resolve discovery wrappers and opportunistically extract the publisher article."""
    enriched = dict(item)
    item_metadata = enriched.get("metadata")
    if not isinstance(item_metadata, dict):
        item_metadata = {}
    published_at = _parse_publication_datetime(
        enriched.get("published_at")
        or item_metadata.get("published_date")
        or item_metadata.get("tavily_published_date")
    )
    if published_at is not None:
        enriched["published_at"] = published_at.isoformat()
    url = (enriched.get("url") or enriched.get("canonical_url") or "").strip()
    if not url:
        return enriched

    from extraction.fetchers.resolvers import is_google_news_redirect, resolve_google_news_url

    try:
        article_url = resolve_google_news_url(url) if is_google_news_redirect(url) else url
        if provider == "google_news" and not is_google_news_redirect(article_url):
            _metric("google_news", "items_resolved")
    except Exception as exc:
        print(f"  [ingest] publisher resolution failed: {type(exc).__name__}: {exc}")
        article_url = url
    enriched["article_url"] = article_url
    canonical_url = (enriched.get("canonical_url") or "").strip()
    canonical_host = (urlparse(canonical_url).hostname or "").lower()
    if (
        not canonical_host
        or canonical_host == "news.google.com"
        or canonical_host.endswith(".google.com")
    ):
        enriched["canonical_url"] = article_url
        enriched["url"] = article_url
    if is_google_news_redirect(article_url):
        return enriched

    article_text = " ".join(str(enriched.get(field) or "") for field in ("description", "snippet", "content"))
    should_extract = extract_content and (
        provider == "google_news"
        or len(str(enriched.get("content") or "")) < 500
        or len(article_text.strip()) < 500
    )
    if should_extract:
        try:
            from extraction.normalizers.article import extract_article
            extracted = extract_article(article_url)
            extracted_data = extracted.model_dump(mode="json")
            for key in ("title", "canonical_url", "content", "author", "published_at", "language"):
                if extracted_data.get(key):
                    if key == "canonical_url" or not enriched.get(key):
                        enriched[key] = extracted_data[key]
            final_url = extracted_data.get("url") or article_url
            enriched["article_url"] = final_url
            enriched["url"] = final_url
            enriched["canonical_url"] = extracted_data.get("canonical_url") or final_url
            parsed = urlparse(final_url)
            enriched["publisher_domain"] = (parsed.hostname or "").lower().removeprefix("www.")
            metadata = enriched.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            metadata["article_extraction"] = extracted_data.get("metadata", {})
            if not enriched.get("published_at") and extracted_data.get("published_at"):
                enriched["published_at"] = extracted_data["published_at"]
            enriched["metadata"] = metadata
            method = (extracted_data.get("metadata") or {}).get("extraction_method")
            if method == "trafilatura":
                _metric("extraction", "trafilatura_successes")
            elif method == "newspaper4k":
                _metric("extraction", "newspaper4k_fallbacks")
            else:
                _metric("extraction", "parser_fallbacks")
            if (extracted_data.get("metadata") or {}).get("fallback_errors"):
                _metric("extraction", "fallback_errors")
        except Exception as exc:
            _metric("extraction", "failures")
            print(f"  [ingest] article extraction failed for {article_url}: {type(exc).__name__}: {exc}")
    return enriched


def _save_news_items(
    items_by_provider: dict[str, list[dict[str, Any]]],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    rejection_counts: dict[str, int] = {}
    max_extracts = max(0, int(os.environ.get("NEWSROOM_MAX_ARTICLE_EXTRACTIONS", "50")))
    extracts = 0
    rss_provider_ids = {feed["id"] for feed in RSS_FEEDS}
    seen_rss_urls: set[str] = set()
    feed_by_id = {feed["id"]: feed for feed in RSS_FEEDS}
    provider_order = sorted(
        items_by_provider,
        key=lambda provider: (
            provider not in rss_provider_ids,
            provider != "google_news",
            provider,
        ),
    )
    for provider in provider_order:
        items = items_by_provider[provider]
        meta = PROVIDERS[provider]
        feed = feed_by_id.get(provider)
        try:
            source_uuid = db.get_or_create_source(
                name=feed["name"] if feed else provider,
                source_type=meta["source_type"],
                domain=meta["domain"],
                base_url=meta.get("base_url"),
                metadata={
                    "registry_category": feed["category"],
                    "priority": feed["priority"],
                    "active": feed["active"],
                } if feed else None,
            )
        except Exception as exc:
            print(f"  [ingest] source ensure failed for {provider}: {exc}")
            result[provider] = []
            continue

        ids: list[str] = []
        rejected_before_save = 0
        upsert_failures = 0
        for raw in items:
            if not _is_valid_article(raw):
                reason = _reject_reason(raw, provider) or "INSUFFICIENT_METADATA"
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
                rejected_before_save += 1
                print(
                    "  [ingest] rejected candidate: "
                    + reason
                    + " | "
                    + str(raw.get("title") or "")[:120]
                )
                continue
            extract_content = extracts < max_extracts
            if extract_content:
                extracts += 1
            enriched = _enrich_article(
                raw,
                provider,
                extract_content=extract_content,
            )
            reason = _reject_reason(enriched, provider)
            if reason or not _is_valid_article(enriched):
                reason = reason or "INSUFFICIENT_METADATA"
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
                rejected_before_save += 1
                if reason == "OUT_OF_SCOPE":
                    article_text = " ".join(
                        str(enriched.get(field) or "")
                        for field in ("title", "description", "snippet", "content")
                    )
                    inferred = infer_categories_from_text(article_text)
                    rejected_categories = {
                        category.value for category in inferred
                    } or {"UNCATEGORIZED"}
                    for category in rejected_categories:
                        TAXONOMY_REJECTED[category] = (
                            TAXONOMY_REJECTED.get(category, 0) + 1
                        )
                print(
                    "  [ingest] rejected candidate: "
                    + reason
                    + " | "
                    + str(enriched.get("title") or "")[:120]
                )
                continue
            payload = _build_news_item(enriched, provider, source_uuid)
            if payload is None:
                reason = _reject_reason(enriched, provider) or "NO_VALID_CATEGORY"
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
                rejected_before_save += 1
                print(
                    "  [ingest] rejected candidate: "
                    + reason
                    + " | "
                    + str(enriched.get("title") or "")[:120]
                )
                continue
            rss_key = (
                _canonical_article_url(payload.get("canonical_url") or payload.get("url"))
                if provider in rss_provider_ids
                else ""
            )
            if rss_key and rss_key in seen_rss_urls:
                _metric(provider, "duplicates")
                continue
            try:
                nid = db.upsert_news_item(payload)
                ids.append(nid)
                _metric(provider, "accepted")
                for category in payload.get("categories") or []:
                    TAXONOMY_ACCEPTED[category] = (
                        TAXONOMY_ACCEPTED.get(category, 0) + 1
                    )
                if rss_key:
                    seen_rss_urls.add(rss_key)
            except Exception as exc:
                upsert_failures += 1
                print(f"  [ingest] upsert_news_item failed: {exc}")
        result[provider] = ids
        print(
            f"  [ingest] provider={provider} raw={len(items)} "
            f"persisted={len(ids)} rejected={rejected_before_save} "
            f"write_failures={upsert_failures}"
        )
    if rejection_counts:
        print("  [ingest] rejection totals: " + str(rejection_counts))
    return result


def _print_observability() -> None:
    rss_metrics = [
        INGESTION_METRICS.get(feed["id"], {})
        for feed in RSS_FEEDS
    ]
    rss_fetched = sum(metric.get("items_fetched", 0) for metric in rss_metrics)
    rss_accepted = sum(metric.get("accepted", 0) for metric in rss_metrics)
    rss_checked = sum(metric.get("feeds_checked", 0) for metric in rss_metrics)
    rss_duplicates = sum(metric.get("duplicates", 0) for metric in rss_metrics)
    print("  [observability] RSS:")
    print(
        f"    feeds checked={rss_checked}/{len(RSS_FEEDS)} "
        f"items fetched={rss_fetched} accepted={rss_accepted} "
        f"rejected={max(0, rss_fetched - rss_accepted - rss_duplicates)} "
        f"duplicates={rss_duplicates}"
    )
    for provider, label in (("google_news", "Google News"), ("ddgs", "DDGS")):
        metrics = INGESTION_METRICS.get(provider, {})
        resolved = metrics.get("items_resolved", 0)
        print(
            f"  [observability] {label}: queries={metrics.get('queries', 0)} "
            f"items fetched={metrics.get('items_fetched', 0)} "
            f"items resolved={resolved} "
            f"items accepted={metrics.get('accepted', 0)} "
            f"failures={metrics.get('failures', 0)}"
        )
    gdelt = INGESTION_METRICS.get("gdelt", {})
    print(
        f"  [observability] GDELT: queries={gdelt.get('queries', 0)} "
        f"items fetched={gdelt.get('items_fetched', 0)} "
        f"rate limits={gdelt.get('rate_limits', 0)} "
        f"failures={gdelt.get('failures', 0)}"
    )
    extraction = INGESTION_METRICS.get("extraction", {})
    print(
        "  [observability] Extraction: "
        f"Trafilatura successes={extraction.get('trafilatura_successes', 0)} "
        f"Newspaper4k fallbacks={extraction.get('newspaper4k_fallbacks', 0)} "
        f"parser fallbacks={extraction.get('parser_fallbacks', 0)} "
        f"failures={extraction.get('failures', 0)} "
        f"fallback errors={extraction.get('fallback_errors', 0)}"
    )
    print(
        "  [observability] Taxonomy: accepted by category="
        + str(dict(sorted(TAXONOMY_ACCEPTED.items())))
    )
    print(
        "  [observability] Taxonomy: rejected by category="
        + str(dict(sorted(TAXONOMY_REJECTED.items())))
    )
    tavily_requests = INGESTION_METRICS.get("tavily", {}).get("requests", 0)
    print(f"  [observability] Tavily requests: {tavily_requests}")


def _group_into_stories(news_item_ids: list[str]) -> dict[str, list[str]]:
    candidates = [
        item for nid in news_item_ids
        if (item := db.get_news_item(nid)) is not None
    ]
    candidates.sort(
        key=lambda item: (
            _parse_publication_datetime(item.get("published_at"))
            or datetime.min.replace(tzinfo=timezone.utc),
            str(item.get("title") or "").casefold(),
            str(item.get("id") or ""),
        )
    )
    clusters: list[list[dict[str, Any]]] = []
    cluster_dates: list[datetime | None] = []
    title_tokens: list[set[str]] = []
    title_signatures: list[str] = []
    title_entities: list[set[str]] = []
    cluster_publishers: list[set[str]] = []
    non_entity_title_words = {
        "a", "an", "the", "after", "amid", "breaking", "major", "new",
        "official", "report", "reports", "says", "update", "what",
    }

    def categories_of(item: dict[str, Any]) -> set[str]:
        values = item.get("categories") or []
        if isinstance(values, str):
            values = [values]
        return {
            str(value) for value in values
            if str(value) in PRODUCTION_CATEGORY_ALLOWLIST
        }

    def entities_of(title: str) -> set[str]:
        return {
            match.group().casefold()
            for match in re.finditer(r"\b[A-Z][A-Za-z0-9&'-]{2,}\b", title)
            if match.group().casefold() not in non_entity_title_words
            and match.group().casefold() not in _STOPWORDS
        }

    def publisher_of(item: dict[str, Any]) -> str:
        metadata = item.get("metadata") or {}
        publisher = (
            item.get("publisher_domain")
            or item.get("source_domain")
            or (metadata.get("publisher_domain") if isinstance(metadata, dict) else None)
        )
        return str(publisher or "").casefold().removeprefix("www.")

    for item in candidates:
        title = str(item.get("title") or "")
        signature = _title_signature(title)
        tokens = set(signature.split())
        entities = entities_of(title)
        item_date = _parse_publication_datetime(item.get("published_at"))
        item_categories = categories_of(item)
        item_publisher = publisher_of(item)
        matching_cluster: int | None = None
        for index, cluster in enumerate(clusters):
            cluster_date = cluster_dates[index]
            if item_date is None or cluster_date is None:
                continue
            if abs((item_date - cluster_date).total_seconds()) > _CLUSTER_WINDOW_HOURS * 60 * 60:
                continue
            if not item_categories.intersection(
                set().union(*(categories_of(member) for member in cluster))
            ):
                continue
            overlap = len(tokens.intersection(title_tokens[index]))
            union = len(tokens.union(title_tokens[index]))
            different_publisher = (
                bool(item_publisher)
                and bool(cluster_publishers[index])
                and item_publisher not in cluster_publishers[index]
            )
            if signature == title_signatures[index] or (
                overlap >= 2
                and (
                    (
                        different_publisher
                        and bool(entities.intersection(title_entities[index]))
                    )
                    or (union > 0 and overlap / union >= 0.60 and overlap >= 3)
                )
            ):
                matching_cluster = index
                break
        if matching_cluster is None:
            clusters.append([item])
            cluster_dates.append(item_date)
            title_tokens.append(tokens)
            title_signatures.append(signature)
            title_entities.append(entities)
            cluster_publishers.append({item_publisher} if item_publisher else set())
        else:
            clusters[matching_cluster].append(item)
            title_tokens[matching_cluster].update(tokens)
            title_entities[matching_cluster].update(entities)
            if item_publisher:
                cluster_publishers[matching_cluster].add(item_publisher)

    groups: dict[str, list[str]] = {}
    for cluster in clusters:
        representative = cluster[0]
        title = str(representative.get("title") or "")
        published = _parse_publication_datetime(representative.get("published_at"))
        date_key = published.strftime("%Y%m%d") if published else "unknown"
        category_key = "|".join(sorted(categories_of(representative)))
        key = _signature_hash(
            f"{_title_signature(title)}|{date_key}|{category_key}"
        )
        groups[key] = [str(item["id"]) for item in cluster if item.get("id")]
    return groups


def _persist_stories(groups: dict[str, list[str]]) -> tuple[int, int, int]:
    stories_created = 0
    links_created = 0
    clusters_skipped = 0

    for sig_hash, item_ids in groups.items():
        if not item_ids:
            clusters_skipped += 1
            continue
        rep = db.get_news_item(item_ids[0])
        if not rep:
            clusters_skipped += 1
            continue
        title = (rep.get("title") or "").strip() or "(untitled)"
        summary = (rep.get("description") or rep.get("snippet") or "")[:280]

        # Aggregate categories across items in cluster
        all_cats: list[str] = []
        for nid in item_ids:
            ni = db.get_news_item(nid)
            if ni and ni.get("categories"):
                all_cats.extend(ni["categories"])
        norm_cats = [
            category for category in _strict_normalize_categories(all_cats)
            if category in PRODUCTION_CATEGORY_ALLOWLIST
        ]
        representative_metadata = rep.get("metadata") or {}
        primary_category = (
            representative_metadata.get("primary_category")
            or primary_category_for_text(title, summary)
        )
        if primary_category not in norm_cats:
            primary_category = norm_cats[0] if norm_cats else None
        linked_items = [db.get_news_item(nid) for nid in item_ids]
        linked_metadata = [
            ni.get("metadata") or {} for ni in linked_items if ni
        ]
        publication_dates = [
            parsed
            for item in linked_items
            if item
            if (parsed := _parse_publication_datetime(item.get("published_at"))) is not None
        ]
        story_published_at = (
            max(publication_dates).isoformat() if publication_dates else None
        )

        try:
            legacy_signature = _signature_hash(_title_signature(title))
            metadata = {
                "cluster_signature": sig_hash,
                "legacy_cluster_signature": legacy_signature,
                "item_count": len(item_ids),
                "categories": norm_cats,
                "primary_category": primary_category,
                "topic_fit": bool(norm_cats),
                "newsworthiness": bool(representative_metadata.get("newsworthiness")),
                "published_at": story_published_at,
                "publisher_name": representative_metadata.get("publisher_name") or "",
                "publisher_domain": representative_metadata.get("publisher_domain") or "",
                "discovery_provider": (
                    representative_metadata.get("discovery_provider")
                    or representative_metadata.get("provider")
                    or ""
                ),
                "discovery_query": representative_metadata.get("discovery_query") or "",
                "article_quality": (
                    "article"
                    if any(meta.get("article_quality") == "article" for meta in linked_metadata)
                    else "snippet"
                ),
                "publishers": sorted({
                    str(meta.get("publisher_domain") or "")
                    for meta in linked_metadata if meta.get("publisher_domain")
                }),
                "discovery_providers": sorted({
                    str(meta.get("discovery_provider") or meta.get("provider") or "")
                    for meta in linked_metadata
                    if meta.get("discovery_provider") or meta.get("provider")
                }),
                "discovery_queries": list(dict.fromkeys(
                    str(meta.get("discovery_query") or "")
                    for meta in linked_metadata if meta.get("discovery_query")
                )),
                "ingest_run": datetime.now(timezone.utc).isoformat(),
            }
            existing = db.find_story_by_cluster_signature(
                sig_hash,
                legacy_signature=legacy_signature,
            )
            if existing:
                story_id = existing["id"]
                merged_metadata = {
                    **(existing.get("metadata") or {}),
                    **metadata,
                }
                db.update_story_content(
                    story_id,
                    title=title,
                    summary=summary,
                    metadata=merged_metadata,
                )
            else:
                story_id = db.create_story(
                    title=title,
                    summary=summary,
                    metadata=metadata,
                )
                stories_created += 1
        except Exception as exc:
            print(f"  [ingest] create_story failed: {exc}")
            clusters_skipped += 1
            continue

        for nid in item_ids:
            try:
                db.link_story_source(story_id, nid)
                links_created += 1
            except Exception as exc:
                print(f"  [ingest] link_story_source failed: {exc}")

    return stories_created, links_created, clusters_skipped


def main() -> int:
    print("=" * 70)
    print("NewsRoom -- Ingestion Orchestrator")
    print("=" * 70)
    try:
        if not db.is_production():
            print("  ERROR: production ingestion requires the real Supabase backend.")
            return 2
        print("  backend: " + db.backend_status())
    except Exception as exc:
        print("  ERROR: Supabase is unavailable: " + type(exc).__name__ + ": " + str(exc))
        return 2
    print()

    by_provider: dict[str, list[dict[str, Any]]] = {}
    for i, (name, fn) in enumerate(SOURCES):
        if i > 0:
            time.sleep(1.0)
        if name in {feed["id"] for feed in RSS_FEEDS}:
            _metric(name, "feeds_checked")
        print("  [fetch] " + name + "...")
        try:
            by_provider[name] = fn()
            print("    -> " + str(len(by_provider[name])) + " raw item(s)")
        except Exception as exc:
            _metric(name, "failures")
            print("    -> FAILED: " + type(exc).__name__ + ": " + str(exc))
            by_provider[name] = []

    print()
    print("  [persist] writing news_items...")
    provider_ids = _save_news_items(by_provider)
    _print_observability()
    for provider, ids in provider_ids.items():
        print("    " + provider.ljust(14) + str(len(ids)) + " item(s) persisted")

    all_ids: list[str] = []
    for ids in provider_ids.values():
        all_ids.extend(ids)
    all_ids = list(dict.fromkeys(all_ids))
    print("    unique news_items: " + str(len(all_ids)))
    print()

    print("  [cluster] grouping into stories...")
    groups = _group_into_stories(all_ids)
    print("    " + str(len(groups)) + " cluster(s)")
    for sig, ids in list(groups.items())[:5]:
        print("      " + sig + "  " + str(len(ids)) + " item(s)")
    print()

    print("  [persist] writing stories + story_sources...")
    sc, lc, sk = _persist_stories(groups)
    print("    stories created:  " + str(sc))
    print("    links created:    " + str(lc))
    print("    clusters skipped: " + str(sk))
    print()

    print("  backend: " + db.backend_status())
    if not all_ids or not groups:
        print("  ERROR: ingestion produced no persisted source-backed story candidates.")
        return 1
    if not any(by_provider.values()):
        print("  ERROR: every configured external source returned no items.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
