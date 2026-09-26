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

from core.team.graph import run_team  # noqa: E402
from core.tools.database import stories as db  # noqa: E402


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


def select_candidate() -> dict | None:
    """Select at most one story, favoring topic diversity."""
    candidates = db.find_reporting_candidates(max_age_minutes=1440, limit=30)
    if not candidates:
        return None
    recent_topic = _most_recent_publication_topic()
    if recent_topic:
        diverse = [c for c in candidates if _topic_of(c) != recent_topic]
        if diverse:
            return diverse[0]
    return candidates[0]


def main() -> int:
    provider = os.environ.get("NEWSROOM_PROVIDER", "ollama")
    model_id = os.environ.get("NEWSROOM_MODEL", "gpt-oss:120b")
    live = _is_live()

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

    rc = run_team(
        provider, model_id,
        story_id=story_id,
        mode="reporting",
        topic=title,
        dry_run=not live,
    )

    return rc


if __name__ == "__main__":
    sys.exit(main())