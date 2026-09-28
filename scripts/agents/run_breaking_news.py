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

from core.llm.registry import build_default_registry
from core.llm.persistence import load_capabilities
from core.llm.routing.router import AgentTask, ModelRouter  # noqa: E402
from core.team.graph import run_team  # noqa: E402
from core.tools.database import stories as db  # noqa: E402


def _route_model(task: AgentTask) -> tuple[str, str]:
    registry = build_default_registry()
    load_capabilities(registry)
    router = ModelRouter(registry)
    primary = router.route(task)
    if primary is None:
        raise RuntimeError(f"No verified model available for task {task.value!r}")
    return primary.provider, primary.model_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_live() -> bool:
    return os.environ.get("NEWSROOM_LIVE", "").strip().lower() in ("1", "true", "yes")


from schemas.taxonomy import is_rejected_category


def select_candidate() -> dict | None:
    """Return the top-ranked qualified breaking news candidate, or None.

    Evaluates:
      - freshness (<= 180 mins)
      - source count / corroboration (_source_count >= 1)
      - non-duplicate / novelty
      - eligible category taxonomy
    """
    candidates = db.find_unpublished_candidates(
        max_age_minutes=180,   # strict 3-hour freshness window for breaking events
        min_source_count=1,
        limit=15,
    )
    if not candidates:
        return None

    # Filter out rejected categories and already published duplicates
    eligible = []
    now_utc = datetime.now(timezone.utc)

    for c in candidates:
        cats = c.get("categories") or c.get("metadata", {}).get("categories") or []
        if any(is_rejected_category(cat) for cat in cats):
            continue
        title = c.get("title", "")
        if any(is_rejected_category(word) for word in title.split()):
            continue

        sid = c.get("id", "")
        if sid and db.find_duplicate_publication(sid):
            continue

        # Calculate freshness age in minutes
        first_seen = c.get("first_seen_at") or ""
        age_mins = 999.0
        if first_seen:
            try:
                ts = datetime.fromisoformat(str(first_seen).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_mins = (now_utc - ts).total_seconds() / 60.0
            except Exception:
                pass

        c["_age_mins"] = age_mins
        eligible.append(c)

    if not eligible:
        return None

    # Rank breaking candidates by multi-factor score: (source_count DESC, freshness_age ASC)
    def breaking_rank(c: dict) -> tuple[int, float]:
        source_count = c.get("_source_count", 1)
        if isinstance(source_count, list):
            source_count = len(source_count)
        return (-int(source_count), c.get("_age_mins", 999.0))

    eligible.sort(key=breaking_rank)
    return eligible[0]


def main() -> int:
    provider = os.environ.get("NEWSROOM_PROVIDER", "").strip()
    model_id = os.environ.get("NEWSROOM_MODEL", "").strip()
    if not provider or not model_id:
        provider, model_id = _route_model(AgentTask.RESEARCH)
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

    # Build editorial memory from database
    memory = db.build_editorial_memory(story_id=story_id, query_title=title)

    # Run the team graph in breaking mode. The topic is the real story title.
    rc = run_team(
        provider, model_id,
        story_id=story_id,
        mode="breaking",
        topic=title,
        dry_run=not live,
        editorial_memory=memory,
    )

    return rc


if __name__ == "__main__":
    sys.exit(main())