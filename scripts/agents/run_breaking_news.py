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


from schemas.taxonomy import (
    classify_article, is_rejected_category, normalize_category,
    is_publication_current, primary_category_for_text,
)


def select_candidate() -> dict | None:
    """Return the top-ranked qualified breaking news candidate, or None.

    Evaluates:
      - freshness (<= 180 mins)
      - at least two linked source records as a minimum corroboration signal
      - non-duplicate / novelty
      - eligible category taxonomy
    """
    candidates = db.find_unpublished_candidates(
        max_age_minutes=180,   # strict 3-hour freshness window for breaking events
        min_source_count=2,
        limit=15,
    )
    if not candidates:
        return None

    # Filter out rejected categories and already published duplicates
    eligible = []
    now_utc = datetime.now(timezone.utc)

    for c in candidates:
        metadata = c.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        max_age_days = int(os.environ.get("NEWSROOM_MAX_ARTICLE_AGE_DAYS", "30"))
        if not is_publication_current(
            metadata.get("published_at"),
            max_age_days=max_age_days,
        ):
            continue
        title = str(c.get("title") or "")
        if not title.strip():
            continue
        if metadata.get("topic_fit") is False or metadata.get("newsworthiness") is False:
            continue
        if metadata.get("topic_fit") is not True or metadata.get("newsworthiness") is not True:
            assessed = classify_article(
                title=str(title),
                description=str(c.get("summary") or ""),
            )
            if not assessed["topic_fit"] or not assessed["newsworthiness"]:
                continue
            metadata = {
                **metadata,
                "categories": metadata.get("categories") or assessed["categories"],
                "primary_category": metadata.get("primary_category") or assessed["primary_category"],
                "topic_fit": assessed["topic_fit"],
                "newsworthiness": assessed["newsworthiness"],
            }
        cats = c.get("categories") or metadata.get("categories") or []
        if isinstance(cats, str):
            cats = [cats]
        categories = {
            category.value
            for raw in cats
            if isinstance(raw, str)
            and (category := normalize_category(raw, allow_partial=False)) is not None
        }
        if not categories:
            continue
        if any(is_rejected_category(cat) for cat in cats):
            continue
        if any(is_rejected_category(word) for word in title.split()):
            continue
        c["categories"] = sorted(categories)
        primary = normalize_category(
            str(metadata.get("primary_category") or c.get("primary_category") or ""),
            allow_partial=False,
        )
        c["primary_category"] = (
            primary.value
            if primary and primary.value in categories
            else primary_category_for_text(title, str(c.get("summary") or ""))
            or sorted(categories)[0]
        )
        c["metadata"] = metadata

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

    # Rank using recorded corroboration and freshness; the word "breaking"
    # is not treated as evidence of significance or urgency.
    def breaking_rank(c: dict) -> tuple[int, int, float]:
        source_count = c.get("_source_count", 1)
        if isinstance(source_count, list):
            source_count = len(source_count)
        metadata = c.get("metadata") or {}
        publishers = metadata.get("publishers") or []
        publisher_count = len(set(map(str, publishers)))
        return (-publisher_count, -int(source_count), c.get("_age_mins", 999.0))

    eligible.sort(key=breaking_rank)
    return eligible[0]


def main() -> int:
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print("Usage: python scripts/agents/run_breaking_news.py")
        return 0
    provider = os.environ.get("NEWSROOM_PROVIDER", "").strip()
    model_id = os.environ.get("NEWSROOM_MODEL", "").strip()
    if not provider or not model_id:
        provider, model_id = _route_model(AgentTask.RESEARCH)
    live = _is_live()
    try:
        if not db.is_production():
            print("  ERROR: breaking workflow requires the real Supabase backend.")
            return 2
    except Exception as exc:
        print("  ERROR: Supabase is unavailable: " + str(exc))
        return 2

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