"""Evening reporting runner.

Runs during the 19:00-23:00 local window. Tries a bounded ranked list of
unpublished candidates (default five, configurable up to ten with
NEWSROOM_MAX_CANDIDATE_ATTEMPTS). Candidate-quality rejections advance to the
next candidate; system, quota, and publication-recovery failures stop the run.
The target is one confirmed post by default and can be configured with
NEWSROOM_MIN_POSTS_PER_RUN, subject to the candidate and publication quotas.
"""
from __future__ import annotations
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def select_candidates(limit: int = 5) -> list[dict]:
    """Rank eligible reporting candidates by category diversity and source count."""
    candidates = db.find_reporting_candidates(max_age_minutes=1440, limit=30)
    if not candidates:
        return []

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
        return []

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

    return eligible[:limit]


def select_candidate() -> dict | None:
    """Compatibility helper for existing one-candidate selection checks."""
    candidates = select_candidates(limit=1)
    return candidates[0] if candidates else None


def candidate_attempt_limit() -> int:
    raw_limit = os.environ.get("NEWSROOM_MAX_CANDIDATE_ATTEMPTS", "5")
    try:
        configured_limit = int(raw_limit)
    except ValueError as exc:
        raise ValueError(
            "NEWSROOM_MAX_CANDIDATE_ATTEMPTS must be an integer"
        ) from exc
    if configured_limit < 1:
        raise ValueError("NEWSROOM_MAX_CANDIDATE_ATTEMPTS must be at least 1")
    return min(configured_limit, 10)


def minimum_posts_per_run() -> int:
    raw_target = os.environ.get("NEWSROOM_MIN_POSTS_PER_RUN", "1")
    try:
        target = int(raw_target)
    except ValueError as exc:
        raise ValueError("NEWSROOM_MIN_POSTS_PER_RUN must be an integer") from exc
    if target < 1:
        raise ValueError("NEWSROOM_MIN_POSTS_PER_RUN must be at least 1")
    return target


def _attempt_candidates(
    candidates: list[dict],
    provider: str,
    model_id: str,
    live: bool,
    *,
    max_attempts: int,
    target_posts: int = 1,
    team_runner: Callable[..., int] | None = None,
    memory_builder: Callable[..., dict] | None = None,
) -> int:
    runner = team_runner or run_team
    build_memory = memory_builder or db.build_editorial_memory
    if not candidates:
        print("  NO_PUBLISHABLE_STORY")
        print("  Candidates attempted: 0")
        print("  Posts published: 0")
        return 0

    attempted = 0
    successful_posts = 0
    for index, candidate in enumerate(candidates[:max_attempts], start=1):
        story_id = candidate.get("id") or candidate.get("story_id") or ""
        title = candidate.get("title") or ""
        if not story_id or not title.strip():
            attempted += 1
            print(
                f"  Candidate {index}/{min(len(candidates), max_attempts)} "
                "rejected: MALFORMED_CANDIDATE (missing story ID or title)"
            )
            continue

        attempted += 1
        sources = candidate.get("source_ids") or []
        print(f"\n[candidate {index}/{min(len(candidates), max_attempts)}]")
        print(f"  Title: {title[:100]}")
        print(f"  Story ID: {story_id}")
        print(f"  Sources: {sources}")

        try:
            memory = build_memory(story_id=story_id, query_title=title)
        except Exception as exc:
            print(
                "  ERROR: editorial memory/database failure; stopping candidate "
                f"fallback: {type(exc).__name__}"
            )
            return 2

        result: dict[str, Any] = {}
        try:
            rc = runner(
                provider,
                model_id,
                story_id=story_id,
                mode="reporting",
                topic=title,
                dry_run=not live,
                editorial_memory=memory,
                result_out=result,
            )
        except Exception as exc:
            print(
                f"  [run] SYSTEM_ERROR: newsroom execution raised "
                f"{type(exc).__name__}; stopping fallback."
            )
            return 2
        outcome = result.get("outcome")
        if outcome == "CANDIDATE_REJECTED":
            reason = result.get("candidate_rejection_reason") or "UNSPECIFIED"
            print(f"  -> REJECTED")
            print(f"  Reason: {reason}")
            continue
        if outcome == "PUBLISHED":
            external_id = result.get("external_post_id") or ""
            if not external_id:
                print("  [run] RECOVERY_REQUIRED: confirmed status lacks a post ID.")
                print("  [run] Automatic retry disabled to prevent duplicate publication.")
                return 1
            successful_posts += 1
            print("  [publisher] PUBLISHED")
            print("  External ID: " + str(external_id))
            print(
                f"  Posts published: {successful_posts}/{target_posts}"
            )
            if successful_posts >= target_posts:
                print("\n  RUN COMPLETE")
                print(f"  Posts published: {successful_posts}")
                print(f"  Candidates attempted: {attempted}")
                return 0
            continue
        if outcome == "DRY_RUN":
            print("  [publisher] SKIPPED_DRY_RUN; no Threads post was made.")
            print("  [run] Dry-run completed; minimum live-post target was not applied.")
            return rc
        if outcome == "RECOVERY_REQUIRED":
            print("  [publisher] RECOVERY_REQUIRED")
            print("  Threads outcome could not be confirmed.")
            print("  [run] Automatic retry disabled to prevent duplicate publication.")
            if result.get("publication_error"):
                print("  [publisher] " + str(result["publication_error"]))
            return rc if rc else 1
        if outcome == "DEFERRED_QUOTA":
            print("  [quota] DEFERRED_QUOTA; stopping candidate processing.")
            print(
                f"  Posts published: {successful_posts}/{target_posts}; "
                f"candidates attempted: {attempted}"
            )
            return rc if rc else 1

        print(
            f"  [run] SYSTEM_ERROR ({outcome or 'UNKNOWN'}); "
            "stopping without trying another candidate."
        )
        return rc if rc else 1

    if successful_posts:
        print("\n  RUN INCOMPLETE: target not reached")
        print(f"  Candidates attempted: {attempted}")
        print(f"  Posts published: {successful_posts}/{target_posts}")
        print(f"  Target posts: {target_posts}; run target not reached.")
        return 1
    print("\n  NO_PUBLISHABLE_STORY")
    print(f"  Candidates attempted: {attempted}")
    print(f"  Posts published: 0")
    return 0


def main() -> int:
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print("Usage: python scripts/agents/run_evening_reporting.py")
        return 0
    provider = os.environ.get("NEWSROOM_PROVIDER", "").strip()
    model_id = os.environ.get("NEWSROOM_MODEL", "").strip()
    if not provider or not model_id:
        try:
            provider, model_id = _route_model(AgentTask.RESEARCH)
        except Exception as exc:
            print(
                "  [run] SYSTEM_ERROR: no verified research model available ("
                + type(exc).__name__
                + ")."
            )
            return 2
    live = _is_live()
    try:
        if not db.is_production():
            print("  ERROR: reporting workflow requires the real Supabase backend.")
            return 2
    except Exception as exc:
        print("  ERROR: Supabase is unavailable: " + str(exc))
        return 2

    try:
        max_attempts = candidate_attempt_limit()
        target_posts = minimum_posts_per_run()
    except ValueError as exc:
        print("  ERROR: " + str(exc))
        return 2
    if target_posts > max_attempts:
        print(
            "  ERROR: NEWSROOM_MIN_POSTS_PER_RUN cannot exceed "
            "NEWSROOM_MAX_CANDIDATE_ATTEMPTS."
        )
        return 2

    try:
        candidates = select_candidates(limit=max_attempts)
    except Exception as exc:
        print(
            "  [run] SYSTEM_ERROR: candidate query failed ("
            + type(exc).__name__
            + ")."
        )
        return 2
    print("=" * 70)
    print("NewsRoom Reporting Run")
    print("=" * 70)
    print(f"  live={live}  provider={provider}  model={model_id}")
    print(f"  backend={db.backend_status()}")
    print(f"  Target posts: {target_posts}")
    print(f"  Maximum candidate attempts: {max_attempts}")
    print()
    return _attempt_candidates(
        candidates,
        provider,
        model_id,
        live,
        max_attempts=max_attempts,
        target_posts=target_posts,
    )


if __name__ == "__main__":
    sys.exit(main())