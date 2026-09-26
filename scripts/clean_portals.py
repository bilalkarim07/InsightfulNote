"""Delete portal/homepage news_items and orphan stories."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402
from core.tools.database.client import get_client


PORTAL_TITLE_FRAGMENTS = [
    "Breaking News, Latest News and Videos",
    "Breaking News, Latest Headlines",
    "Breaking News, US News, World News",
    "Top World News",
    "Latest News, Breaking News",
    "Breaking News & Top Stories",
]


def is_portal(item: dict) -> bool:
    url = (item.get("url") or item.get("canonical_url") or "").strip()
    title = (item.get("title") or "").strip()

    # Title check
    for frag in PORTAL_TITLE_FRAGMENTS:
        if frag in title:
            return True

    # URL check: domain root or /news, /breaking-news, etc.
    try:
        from urllib.parse import urlparse
        path = urlparse(url).path or "/"
        if path in ("", "/"):
            return True
        segments = [s for s in path.split("/") if s]
        if len(segments) == 0:
            return True
        if len(segments) == 1 and segments[0].lower() in (
            "news", "breaking-news", "world", "us", "politics",
            "business", "technology", "tech", "entertainment",
            "sports", "health", "science", "latest", "top-stories",
            "home",
        ):
            return True
    except Exception:
        pass

    return False


def main() -> None:
    c = get_client()
    print("=" * 70)
    print("Cleaning portal news_items and orphan stories")
    print("=" * 70)

    # Get all news_items
    r = c.table("news_items").select("id,title,url,canonical_url").execute()
    items = r.data or []
    print(f"  news_items total: {len(items)}")

    junk_ids: list[str] = []
    for it in items:
        if is_portal(it):
            junk_ids.append(it["id"])
    print(f"  portal news_items: {len(junk_ids)}")

    if not junk_ids:
        print("  Nothing to clean.")
        return

    # Find story_sources rows that reference junk items
    ss = c.table("story_sources").select("story_id,news_item_id").execute()
    links = ss.data or []
    affected_story_ids = {l["story_id"] for l in links if l["news_item_id"] in junk_ids}
    print(f"  affected stories: {len(affected_story_ids)}")

    # Delete story_sources for junk
    for sid in affected_story_ids:
        try:
            c.table("story_sources").delete().eq("story_id", sid).execute()
        except Exception as exc:
            print(f"    story_sources del {sid[:8]}: {exc}")

    # Delete news_items (in batches to avoid huge IN clauses)
    BATCH = 50
    for i in range(0, len(junk_ids), BATCH):
        batch = junk_ids[i:i + BATCH]
        try:
            c.table("news_items").delete().in_("id", batch).execute()
        except Exception as exc:
            print(f"    news_items del batch {i}: {exc}")
    print(f"  deleted {len(junk_ids)} news_items")

    # Delete stories that no longer have any links
    ss2 = c.table("story_sources").select("story_id").execute()
    live_story_ids = {l["story_id"] for l in (ss2.data or [])}
    story_r = c.table("stories").select("id").execute()
    all_story_ids = {s["id"] for s in (story_r.data or [])}
    orphan_ids = list(all_story_ids - live_story_ids)
    print(f"  orphan stories: {len(orphan_ids)}")

    for sid in orphan_ids:
        try:
            c.table("stories").delete().eq("id", sid).execute()
        except Exception as exc:
            print(f"    story del {sid[:8]}: {exc}")
    print(f"  deleted {len(orphan_ids)} orphan stories")

    # Final counts
    print()
    for t in ["news_items", "stories", "story_sources"]:
        try:
            r = c.table(t).select("id" if t != "story_sources" else "story_id", count="exact").limit(0).execute()
            print(f"  {t:16} {r.count or 0} rows")
        except Exception:
            print(f"  {t:16} ?")


if __name__ == "__main__":
    main()
