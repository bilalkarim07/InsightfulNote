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
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from core.tools.database import stories as db  # noqa: E402


QUERIES = [
    "breaking news",
    "world news today",
    "technology news",
    "business news",
]


PROVIDERS = {
    "tavily":      {"source_type": "search_api", "domain": "tavily.com"},
    "ddgs":        {"source_type": "search_api", "domain": "duckduckgo.com"},
    "google_news": {"source_type": "rss",        "domain": "news.google.com"},
    "gdelt":       {"source_type": "api",        "domain": "gdeltproject.org"},
}


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
        for q in QUERIES[:2]:
            out.extend(_iter_items(client.search(q)))
    finally:
        try: client.close()
        except Exception: pass
    return out


def _ddgs_items() -> list[dict[str, Any]]:
    from sources.ddgs import DDGSClient
    out: list[dict[str, Any]] = []
    client = DDGSClient()
    try:
        for q in QUERIES[:2]:
            out.extend(_iter_items(client.news_search(q)))
    finally:
        try: client.close()
        except Exception: pass
    return out


def _google_news_items() -> list[dict[str, Any]]:
    from sources.google_news import GoogleNewsClient
    out: list[dict[str, Any]] = []
    client = GoogleNewsClient()
    try:
        for q in QUERIES[:2]:
            out.extend(_iter_items(client.search(q)))
    finally:
        try: client.close()
        except Exception: pass
    return out


def _gdelt_items() -> list[dict[str, Any]]:
    from sources.gdelt import GDELTClient
    out: list[dict[str, Any]] = []
    client = GDELTClient()
    try:
        out.extend(_iter_items(client.search(QUERIES[0])))
        time.sleep(5.5)
        out.extend(_iter_items(client.search(QUERIES[1])))
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
    url = (item.get("url") or item.get("canonical_url") or "").strip()
    if not url:
        return None
    canonical = (item.get("canonical_url") or url).strip()
    return {
        "url": url,
        "canonical_url": canonical,
        "title": (item.get("title") or "").strip(),
        "description": item.get("description") or "",
        "snippet": item.get("snippet") or "",
        "source_id": source_uuid,
        "source_name": item.get("source_name") or provider,
        "source_domain": item.get("source_domain") or "",
        "author": item.get("author") or None,
        "published_at": item.get("published_at") or None,
        "content": item.get("content") or None,
        "language": item.get("language") or "en",
        "country": item.get("country") or None,
        "categories": item.get("categories") or [],
        "metadata": {
            "provider": provider,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def _save_news_items(
    items_by_provider: dict[str, list[dict[str, Any]]],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for provider, items in items_by_provider.items():
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
                continue
            payload = _build_news_item(raw, provider, source_uuid)
            if payload is None:
                continue
            try:
                nid = db.upsert_news_item(payload)
                ids.append(nid)
            except Exception as exc:
                print(f"  [ingest] upsert_news_item failed: {exc}")
        result[provider] = ids
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

        try:
            story_id = db.create_story(
                title=title,
                summary=summary,
                metadata={
                    "cluster_signature": sig_hash,
                    "item_count": len(item_ids),
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


def main() -> None:
    print("=" * 70)
    print("NewsRoom -- Ingestion Orchestrator")
    print("=" * 70)
    print("  backend: " + db.backend_status())
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


if __name__ == "__main__":
    main()
