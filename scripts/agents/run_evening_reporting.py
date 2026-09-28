"""Evening reporting runner.

Runs during the 19:00-23:00 local window. Selects at most ONE story per
scheduled invocation from the candidates gathered during the day,
excluding any already published. Publishes at most one post per run.

Behaviour:
  0 posts = valid (no qualified story or diversity exhausted)
  1 post  = valid
  2+      = not allowed
"""
from __future__ import annotations
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


def _topic_of(r: dict) -> str:
    t = (r.get("topic") or "").strip().lower()
    if t and t != "news" and t != "general":
        return t
    words = (r.get("title") or "").split()
    return " ".join(words[:2]).lower()


def _most_recent_publication_topic() -> str:
    """Return topic of the most recently PUBLISHED story, or empty string."""
    try:
        client = db.get_client()
        pubs = client.select("publications") if not db.is_production() else []
        published_ids = [p.get("story_id") for p in pubs if p.get("status") == "PUBLISHED"]
        if not published_ids:
            return ""
        latest = None
        for sid in published_ids:
            s = db.get_story(sid)
            if not s:
                continue
            fs = s.get("first_seen_at") or ""
            if latest is None or fs > latest.get("first_seen_at", ""):
                latest = s
        return _topic_of(latest) if latest else ""
    except Exception:
        return ""


from schemas.taxonomy import is_rejected_category


def select_candidate() -> dict | None:
    """Select at most one story, favoring category diversity and avoiding repetition."""
    candidates = db.find_reporting_candidates(max_age_minutes=1440, limit=30)
    if not candidates:
        return None

    # Filter out rejected categories
    eligible = []
    for c in candidates:
        cats = c.get("categories") or c.get("metadata", {}).get("categories") or []
        if any(is_rejected_category(cat) for cat in cats):
            continue
        title = c.get("title", "")
        if any(is_rejected_category(word) for word in title.split()):
            continue
        eligible.append(c)

    if not eligible:
        return None

    # Favor category diversity based on recent category distribution
    dist = db.get_recent_category_distribution(hours=24)
    if dist:
        # Sort candidates so categories with lower recent count come first (diversity bonus)
        def diversity_score(c: dict) -> tuple[int, int]:
            cats = c.get("categories") or c.get("metadata", {}).get("categories") or []
            max_count = max([dist.get(str(cat).upper(), 0) for cat in cats], default=0)
            cnt = c.get("_source_count", 0)
            source_cnt = cnt if isinstance(cnt, int) else (len(cnt) if isinstance(cnt, (list, tuple)) else 1)
            return (max_count, -source_cnt)
        eligible.sort(key=diversity_score)

    return eligible[0]


def main() -> int:
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print("Usage: python scripts/agents/run_evening_reporting.py")
        return 0
    provider = os.environ.get("NEWSROOM_PROVIDER", "").strip()
    model_id = os.environ.get("NEWSROOM_MODEL", "").strip()
    if not provider or not model_id:
        provider, model_id = _route_model(AgentTask.RESEARCH)
    live = _is_live()
    try:
        if not db.is_production():
            print("  ERROR: reporting workflow requires the real Supabase backend.")
            return 2
    except Exception as exc:
        print("  ERROR: Supabase is unavailable: " + str(exc))
        return 2

    print("=" * 70)
    print(f"Evening Reporting Runner — live={live}")
    print("=" * 70)
    print(f"  provider={provider}  model={model_id}")
    print(f"  backend={db.backend_status()}")
    print()

    candidate = select_candidate()
    if candidate is None:
        print("  No qualified candidate for evening reporting.")
        print("  Exiting with no publication (valid outcome).")
        return 0

    story_id = candidate.get("id", "") or candidate.get("story_id", "")
    title = candidate.get("title", "")
    sources = candidate.get("source_ids") or []
    print(f"  Selected: {story_id}")
    print(f"    title:    {title[:80]}")
    print(f"    sources:  {sources}")
    print(f"    topic:    {_topic_of(candidate)}")
    print("    seen_at:  " + str(candidate.get("first_seen_at")))
    print()

    # Build editorial memory from database
    memory = db.build_editorial_memory(story_id=story_id, query_title=title)

    rc = run_team(
        provider, model_id,
        story_id=story_id,
        mode="reporting",
        topic=title,
        dry_run=not live,
        editorial_memory=memory,
    )

    return rc


if __name__ == "__main__":
    sys.exit(main())