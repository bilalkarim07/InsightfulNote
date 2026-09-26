"""Inspect publication + story status in Supabase."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from scripts._bootstrap import *  # noqa: F401,F403,E402
from core.tools.database.client import get_client


def safe(v, n=8):
    if v is None:
        return "<none>"
    return str(v)[:n]


def main():
    c = get_client()

    r = c.table("publications").select("*").order("created_at", desc=True).limit(10).execute()
    rows = r.data or []
    print(f"publications: {len(rows)} row(s) shown")
    for row in rows:
        status = str(row.get("status"))
        ext = str(row.get("external_post_id"))
        sid = safe(row.get("story_id"))
        print(f"  status={status!r:24} external_id={ext!r:24} story_id={sid}")
    print()

    r = c.table("stories").select("id,status").order("updated_at", desc=True).limit(10).execute()
    rows = r.data or []
    print(f"stories: {len(rows)} row(s) shown")
    for row in rows:
        print(f"  story={safe(row.get('id'))}  status={str(row.get('status'))!r}")

    print()
    for t in ["publications", "stories", "news_items", "story_sources"]:
        try:
            r = c.table(t).select("id", count="exact").limit(0).execute()
            print(f"  {t:16} {r.count or 0} rows")
        except Exception:
            try:
                r = c.table(t).select("story_id", count="exact").limit(0).execute()
                print(f"  {t:16} {r.count or 0} rows")
            except Exception:
                print(f"  {t:16} ?")


if __name__ == "__main__":
    main()