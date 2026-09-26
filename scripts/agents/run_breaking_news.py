"""Breaking news runner.

Runs hourly. Loads fresh candidates from the story DB, selects one, and
runs the LangGraph team in breaking mode. Publishes at most one post.

Behaviour:
  0 posts = valid (no qualified story)
  1 post  = valid
  2+     = not allowed (hard-capped by this runner)
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from core.team.graph import run_team  # noqa: E402
from core.tools.database import stories as db  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_live() -> bool:
    return os.environ.get("NEWSROOM_LIVE", "").strip().lower() in ("1", "true", "yes")


def select_candidate() -> dict | None:
    """Return the top-ranked unpublished candidate, or None."""
    candidates = db.find_unpublished_candidates(
        max_age_minutes=360,   # stories first seen in the last 6h
        min_source_count=1,    # at least one source (DB already has sources)
        limit=5,
    )
    if not candidates:
        return None
    # Prefer titles containing breaking/fresh cues when otherwise tied.
    def score(r: dict) -> tuple[int, str]:
        title = (r.get("title") or "").lower()
        breaking_bonus = 0
        for cue in ("breaking", "live updates", "just in", "developing"):
            if cue in title:
                breaking_bonus -= 1
        return (breaking_bonus, r.get("first_seen_at") or "")
    candidates.sort(key=score)
    return candidates[0]


def main() -> int:
    provider = os.environ.get("NEWSROOM_PROVIDER", "ollama")
    model_id = os.environ.get("NEWSROOM_MODEL", "gpt-oss:120b")
    live = _is_live()

    print("=" * 70)
    print(f"Breaking News Runner — live={live}")
    print("=" * 70)
    print(f"  provider={provider}  model={model_id}")
    print(f"  backend={db.backend_status()}")
    print()

    candidate = select_candidate()
    if candidate is None:
        print("  No qualified unpublished candidate in the freshness window.")
        print("  Exiting with no publication (valid outcome).")
        return 0

    story_id = candidate.get("id", "") or candidate.get("story_id", "")
    title = candidate.get("title", "")
    sources = candidate.get("source_ids") or []
    print(f"  Selected: {story_id}")
    print(f"    title:    {title[:80]}")
    print(f"    sources:  {sources}")
    print(f"    seen_at:  {candidate.get('first_seen_at')}")
    print()

    # Run the team graph in breaking mode. The topic is the real story title.
    rc = run_team(
        provider, model_id,
        story_id=story_id,
        mode="breaking",
        topic=title,
        dry_run=not live,
    )

    return rc


if __name__ == "__main__":
    sys.exit(main())