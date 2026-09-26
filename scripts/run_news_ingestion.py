"""Production ingestion orchestrator.

Calls every existing source adapter, normalizes results, dedupes by
canonical URL, and persists to the stories table via semantic tools.

Idempotent: rerunning does not create duplicate stories. Failures in one
source do not stop the others.
"""
from __future__ import annotations
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from core.tools.database import stories as db  # noqa: E402


def _canonical_id(url: str) -> str:
    h = hashlib.sha256(url.strip().lower().encode("utf-8")).hexdigest()[:16]
    return f"story_{h}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_item(item: dict[str, Any], source_name: str) -> dict[str, Any] | None:
    """Turn one raw adapter item into a story row. Returns None if unusable."""
    url = item.get("canonical_url") or item.get("url") or item.get("link") or ""
    title = item.get("title") or ""
    if not url or not title:
        return None
    story_id = _canonical_id(url)
    return {
        "story_id": story_id,
        "title": title,
        "summary": item.get("description") or item.get("summary") or "",
        "topic": item.get("topic") or "general",
        "source_ids": [source_name],
        "url": url,
        "first_seen_at": _now_iso(),
        "latest_seen_at": _now_iso(),
        "is_published": False,
    }


def _item_to_dict(item: Any) -> dict[str, Any]:
    """Convert a NewsItem dataclass (or dict) into a plain dict."""
    if isinstance(item, dict):
        return dict(item)
    # Dataclass path.
    if hasattr(item, "__dataclass_fields__"):
        from dataclasses import asdict
        return asdict(item)
    # Fallback: __dict__.
    if hasattr(item, "__dict__"):
        return dict(item.__dict__)
    # Last resort.
    return {"value": str(item)}


def _iter_items(raw: Any) -> list[dict[str, Any]]:
    """Extract list-of-dicts from any shape: SourceResult, dict, or list."""
    if raw is None:
        return []
    # SourceResult dataclass — has .items
    if hasattr(raw, "items"):
        items = getattr(raw, "items") or []
        return [_item_to_dict(x) for x in items]
    # Plain list.
    if isinstance(raw, list):
        return [_item_to_dict(x) for x in raw]
    # Dict with a nested list under a common key.
    if isinstance(raw, dict):
        for key in ("items", "results", "articles", "data", "news"):
            v = raw.get(key)
            if isinstance(v, list):
                return [_item_to_dict(x) for x in v]
    return []


def _call_source(name: str, fn: Callable[[], Any]) -> list[dict[str, Any]]:
    try:
        raw = fn()
        items = _iter_items(raw)
        print(f"  [ingest] {name:16} {len(items)} item(s)")
        return items
    except Exception as exc:  # noqa: BLE001
        print(f"  [ingest] {name:16} FAILED: {type(exc).__name__}: {exc}")
        return []


QUERIES = [
    "breaking news",
    "world news today",
    "technology news",
    "business news",
]


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
    """GDELT is aggressively rate-limited. If it fails, return empty.

    We try once. If we get a rate limit, we wait and try once more. If that
    fails too, we accept it — the other three sources already provide
    plenty of stories. GDELT's value is trend velocity, not raw volume.
    """
    import time
    from sources.gdelt import GDELTClient

    # Polite initial wait in case a recent call hit their limiter.
    time.sleep(2.0)

    for attempt in (1, 2):
        client = GDELTClient()
        try:
            items = _iter_items(client.search(QUERIES[0]))
            if items:
                return items
        except Exception as exc:  # noqa: BLE001
            print(f"  [gdelt] attempt {attempt} failed: {type(exc).__name__}")
            if attempt == 1:
                print(f"  [gdelt] waiting 30s before retry...")
                time.sleep(30)
        finally:
            try: client.close()
            except Exception: pass
    print(f"  [gdelt] giving up — other sources still provide coverage")
    return []


SOURCES: list[tuple[str, Callable[[], list[dict[str, Any]]]]] = [
    ("tavily", _tavily_items),
    ("ddgs", _ddgs_items),
    ("google_news", _google_news_items),
    ("gdelt", _gdelt_items),
]


def main() -> None:
    print("=" * 70)
    print("NewsRoom — Ingestion Orchestrator")
    print("=" * 70)
    print(f"  db backend: {db.backend_status()}")
    print()

    by_source: dict[str, int] = {}
    by_story: dict[str, dict] = {}

    import time as _time
    for i, (name, fn) in enumerate(SOURCES):
        if i > 0:
            _time.sleep(1.0)  # politeness between sources
        items = _call_source(name, fn)
        kept = 0
        for item in items:
            story = _normalize_item(item, name)
            if story is None:
                continue
            sid = story["story_id"]
            existing = by_story.get(sid)
            if existing:
                # Merge source attribution.
                if name not in existing["source_ids"]:
                    existing["source_ids"].append(name)
                continue
            by_story[sid] = story
            kept += 1
        by_source[name] = kept

    print()
    print("  Summary:")
    for name, count in by_source.items():
        print(f"    {name:16} {count} new stories")
    print(f"    {'total unique':16} {len(by_story)}")
    print()

    if not by_story:
        print("  No stories ingested.")
        return

    persisted = 0
    for story in by_story.values():
        try:
            db.save_story(story)
            persisted += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  [ingest] persist failed for {story['story_id']}: {exc}")

    print(f"  Persisted {persisted}/{len(by_story)} stories to {db.backend_status()}")


if __name__ == "__main__":
    main()