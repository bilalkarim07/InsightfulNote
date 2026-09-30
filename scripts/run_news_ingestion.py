"""Production ingestion orchestrator.

Writes to:
  sources        -- one row per provider (Tavily, DDGS, Google News, GDELT)
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
    CATEGORY_DISCOVERY_QUERIES, Category, classify_article,
    infer_categories_from_text, is_newsworthy_text, normalize_category,
    is_publication_current, primary_category_for_text,
)

# Single authoritative source for discovery queries. GDELT coverage is explicit
# and configurable; do not silently slice the taxonomy query set.
QUERIES: list[str] = []
for category in (
    Category.GLOBAL_POLITICS,
    Category.WAR_CONFLICT,
    Category.ARTIFICIAL_INTELLIGENCE,
    Category.TECHNOLOGY,
    Category.SCIENCE,
    Category.HEALTH,
    Category.MEDICAL,
    Category.FINANCE,
    Category.BUSINESS,
    Category.INVESTMENTS,
    Category.CLIMATE_ENVIRONMENT,
    Category.SPORTS,
    Category.WORLD_EVENTS,
):
    QUERIES.extend(CATEGORY_DISCOVERY_QUERIES.get(category, []))

# Optional guard for GDELT rate limiting. Default is "all category queries" to
# preserve the original production model. Override with env var if a stricter cap
# is needed in CI or a low-capacity environment.
_GDELT_MAX_QUERY_LIMIT = int(os.environ.get("NEWSROOM_GDELT_MAX_QUERIES", "0"))


PROVIDERS = {
    "tavily":      {"source_type": "search_api", "domain": "tavily.com"},
    "ddgs":        {"source_type": "search_api", "domain": "duckduckgo.com"},
    "google_news": {"source_type": "rss",        "domain": "news.google.com"},
    "gdelt":       {"source_type": "api",        "domain": "gdeltproject.org"},
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
    from sources.tavily import TavilyClient
    out: list[dict[str, Any]] = []
    client = TavilyClient()
    try:
        for q in QUERIES:
            out.extend(_tag_discovery(_iter_items(client.search(q)), q))
    finally:
        try: client.close()
        except Exception: pass
    return out


def _ddgs_items() -> list[dict[str, Any]]:
    from sources.ddgs import DDGSClient
    out: list[dict[str, Any]] = []
    client = DDGSClient()
    try:
        for q in QUERIES:
            out.extend(_tag_discovery(_iter_items(client.news_search(q)), q))
    finally:
        try: client.close()
        except Exception: pass
    return out


def _google_news_items() -> list[dict[str, Any]]:
    from sources.google_news import GoogleNewsClient
    out: list[dict[str, Any]] = []
    client = GoogleNewsClient()
    try:
        for q in QUERIES:
            out.extend(_tag_discovery(_iter_items(client.search(q)), q))
    finally:
        try: client.close()
        except Exception: pass
    return out


def _gdelt_items() -> list[dict[str, Any]]:
    from sources.gdelt import GDELTClient
    out: list[dict[str, Any]] = []
    client = GDELTClient()
    queries = QUERIES
    if _GDELT_MAX_QUERY_LIMIT > 0:
        queries = queries[:_GDELT_MAX_QUERY_LIMIT]
    try:
        for idx, q in enumerate(queries):
            if idx > 0:
                time.sleep(2.0)
            out.extend(_tag_discovery(_iter_items(client.search(q)), q))
    finally:
        try: client.close()
        except Exception: pass
    return out


SOURCES: list[tuple[str, Callable[[], list[dict[str, Any]]]]] = [
    ("tavily", _tavily_items),
    ("ddgs", _ddgs_items),
    ("google_news", _google_news_items),
    ("gdelt", _gdelt_items),
]


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
    norm_cats = quality["categories"]
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
    if not any(str(item.get(field) or "").strip() for field in ("description", "snippet", "content")):
        return "INSUFFICIENT_METADATA"
    article_text = " ".join(str(item.get(field) or "") for field in ("title", "description", "snippet", "content"))
    if not infer_categories_from_text(article_text):
        return "OUT_OF_SCOPE"
    if not is_newsworthy_text(
        title,
        " ".join(str(item.get(field) or "") for field in ("description", "snippet")),
    ):
        return "NOT_NEWSWORTHY"
    item_metadata = item.get("metadata")
    if not isinstance(item_metadata, dict):
        item_metadata = {}
    published = _parse_publication_datetime(
        item.get("published_at")
        or item_metadata.get("published_date")
        or item_metadata.get("tavily_published_date")
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
            enriched["metadata"] = metadata
        except Exception as exc:
            print(f"  [ingest] article extraction failed for {article_url}: {type(exc).__name__}: {exc}")
    return enriched


def _save_news_items(
    items_by_provider: dict[str, list[dict[str, Any]]],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    rejection_counts: dict[str, int] = {}
    max_extracts = max(0, int(os.environ.get("NEWSROOM_MAX_ARTICLE_EXTRACTIONS", "50")))
    extracts = 0
    provider_order = sorted(
        items_by_provider,
        key=lambda provider: (provider != "google_news", provider),
    )
    for provider in provider_order:
        items = items_by_provider[provider]
        meta = PROVIDERS[provider]
        try:
            source_uuid = db.get_or_create_source(
                name=provider,
                source_type=meta["source_type"],
                domain=meta["domain"],
            )
        except Exception as exc:
            print(f"  [ingest] source ensure failed for {provider}: {exc}")
            result[provider] = []
            continue

        ids: list[str] = []
        for raw in items:
            if not _is_valid_article(raw):
                reason = _reject_reason(raw, provider) or "INSUFFICIENT_METADATA"
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
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
                print(
                    "  [ingest] rejected candidate: "
                    + reason
                    + " | "
                    + str(enriched.get("title") or "")[:120]
                )
                continue
            try:
                nid = db.upsert_news_item(payload)
                ids.append(nid)
            except Exception as exc:
                print(f"  [ingest] upsert_news_item failed: {exc}")
        result[provider] = ids
    if rejection_counts:
        print("  [ingest] rejection totals: " + str(rejection_counts))
    return result


def _group_into_stories(news_item_ids: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for nid in news_item_ids:
        item = db.get_news_item(nid)
        if not item:
            continue
        sig = _title_signature(item.get("title", ""))
        key = _signature_hash(sig)
        groups.setdefault(key, []).append(nid)
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
        norm_cats = _strict_normalize_categories(all_cats)
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
            story_id = db.create_story(
                title=title,
                summary=summary,
                metadata={
                    "cluster_signature": sig_hash,
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
                },
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
        print("  [fetch] " + name + "...")
        try:
            by_provider[name] = fn()
            print("    -> " + str(len(by_provider[name])) + " raw item(s)")
        except Exception as exc:
            print("    -> FAILED: " + type(exc).__name__ + ": " + str(exc))
            by_provider[name] = []

    print()
    print("  [persist] writing news_items...")
    provider_ids = _save_news_items(by_provider)
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
