"""List stories from the local store."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from core.tools.database.client import get_client


def main() -> None:
    c = get_client()
    rows = c.select("stories")
    print(f"Total story rows: {len(rows)}")
    print()
    for i, r in enumerate(rows):
        title = (r.get("title") or "")[:70]
        sources = ",".join(r.get("source_ids", []))
        print(f"  {i+1:3}. {r.get('story_id','')[:20]}  [{sources:20}]  {title}")


if __name__ == "__main__":
    main()
