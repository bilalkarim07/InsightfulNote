import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from scripts._bootstrap import *
from core.tools.database.client import get_client

c = get_client()
for t in ["sources", "news_items", "stories", "story_sources", "claims", "evidence", "publications"]:
    try:
        if t == "story_sources":
            r = c.table(t).select("story_id", count="exact").limit(0).execute()
        else:
            r = c.table(t).select("id", count="exact").limit(0).execute()
        print(f"  {t:16} {r.count or 0} rows")
    except Exception as exc:
        print(f"  {t:16} ERROR: {exc}")
