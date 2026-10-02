"""Evening reporting runner.

Runs hourly during the 20:00-23:00 New York window. Tries a bounded ranked list of
unpublished candidates (default five, configurable up to ten with
NEWSROOM_MAX_CANDIDATE_ATTEMPTS). Candidate-quality rejections advance to the
next candidate; quota deferral stops successfully; system and
publication-recovery failures stop with an error.
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


from schemas.taxonomy import (
    classify_article, is_rejected_category, normalize_category,
    is_publication_current, primary_category_for_text,
    PRODUCTION_CATEGORY_ALLOWLIST,
)


def select_candidates(limit: int = 5) -> list[dict]:
    """Rank eligible reporting candidates by category diversity and source count."""
    candidates = db.find_reporting_candidates(max_age_minutes=1440, limit=30)
    if not candidates:
        return []

    # Require a real story, at least one linked source, and controlled categories.
    eligible = []
    for c in candidates:
        story_id = c.get("id") or c.get("story_id")
        title = c.get("title")
        metadata = c.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        max_age_days = int(os.environ.get("NEWSROOM_MAX_ARTICLE_AGE_DAYS", "30"))
        if not is_publication_current(
            metadata.get("published_at"),
            max_age_days=max_age_days,
        ):
            continue
        if metadata.get("topic_fit") is False or metadata.get("newsworthiness") is False:
            continue
        if metadata.get("topic_fit") is not True or metadata.get("newsworthiness") is not True:
            assessed = classify_article(
                title=title,
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
        if not isinstance(cats, (list, tuple, set)):
            cats = []
        normalized_categories = {
            category.value
            for raw_category in cats
            if isinstance(raw_category, str)
            and (
                category := normalize_category(
                    raw_category,
                    allow_partial=False,
                )
            ) is not None
            and category.value in PRODUCTION_CATEGORY_ALLOWLIST
        }
        source_count = c.get("_source_count")
        if type(source_count) is int:
            has_sources = source_count > 0
        else:
            sources = c.get("source_ids") or c.get("sources") or []
            has_sources = isinstance(sources, (list, tuple, set)) and bool(sources)
        if (
            not isinstance(story_id, str)
            or not story_id.strip()
            or not isinstance(title, str)
            or not title.strip()
            or not normalized_categories
            or not has_sources
        ):
            continue
        if any(is_rejected_category(word) for word in title.split()):
            continue
        c["categories"] = sorted(normalized_categories)
        primary = metadata.get("primary_category")
        if isinstance(primary, str):
            normalized_primary = normalize_category(primary, allow_partial=False)
            if normalized_primary and normalized_primary.value in normalized_categories:
                c["primary_category"] = normalized_primary.value
        if c.get("primary_category") not in normalized_categories:
            c["primary_category"] = (
                primary_category_for_text(
                    title,
                    str(c.get("summary") or ""),
                )
                or sorted(normalized_categories)[0]
            )
        c["_quality_metadata"] = {
            "topic_fit": metadata.get("topic_fit"),
            "newsworthiness": metadata.get("newsworthiness"),
            "publishers": metadata.get("publishers") or [],
        }
        eligible.append(c)

    if not eligible:
        return []

    # Favor category diversity based on recent category distribution
    dist = db.get_recent_category_distribution(hours=24)
    if dist:
        # Sort candidates so categories with lower recent count come first (diversity bonus)
        def diversity_score(c: dict) -> tuple[int, int, int, int]:
            cats = c.get("categories") or []
            max_count = max([dist.get(str(cat).upper(), 0) for cat in cats], default=0)
            cnt = c.get("_source_count", 0)
            source_cnt = cnt if isinstance(cnt, int) else (len(cnt) if isinstance(cnt, (list, tuple)) else 1)
            quality = c.get("_quality_metadata") or {}
            # Quality eligibility always outranks topic diversity. The signal
            # is metadata generated by deterministic ingestion gates, not an
            # LLM score or a publication quota.
            quality_complete = int(quality.get("topic_fit") is True) + int(
                quality.get("newsworthiness") is True
            )
            publisher_domains = quality.get("publishers") or []
            publisher_count = len({
                str(domain).strip().lower().removeprefix("www.")
                for domain in publisher_domains if str(domain).strip()
            }) if isinstance(publisher_domains, (list, tuple, set)) else 0
            return (-quality_complete, -publisher_count, max_count, -source_cnt)
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
        source_count = candidate.get("_source_count")
        if not isinstance(source_count, int):
            source_count = len(sources)
        print(f"\n[candidate {index}/{min(len(candidates), max_attempts)}]")
        print(f"  Title: {title[:100]}")
        print(f"  Story ID: {story_id}")
        print(f"  Sources: {source_count} linked")
        categories = candidate.get("categories") or []
        metadata = candidate.get("metadata") or {}
        published_at = (
            metadata.get("published_at")
            if isinstance(metadata, dict)
            else None
        )
        first_seen_at = candidate.get("first_seen_at") or candidate.get("last_seen_at")
        freshness = "unknown"
        if isinstance(published_at or first_seen_at, str):
            try:
                timestamp = datetime.fromisoformat(
                    str(published_at or first_seen_at).replace("Z", "+00:00")
                )
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                age_minutes = (
                    datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)
                ).total_seconds() / 60
                freshness = f"{max(0, age_minutes):.0f} minutes"
            except ValueError:
                pass
        print(f"  Category: {', '.join(map(str, categories)) or 'unknown'}")
        print(f"  Freshness: {freshness}")

        try:
            memory = build_memory(story_id=story_id, query_title=title)
        except Exception as exc:
            print(
                "  [run] SYSTEM_ERROR: editorial memory/database failure; "
                f"stopping candidate fallback: {type(exc).__name__}"
            )
            return 1

        result: dict[str, Any] = {}
        try:
            rc = runner(
                provider,
                model_id,
                story_id=story_id,
                mode="reporting",
                topic=title,
                dry_run=False,
                editorial_memory=memory,
                result_out=result,
            )
        except Exception as exc:
            print(
                f"  [run] SYSTEM_ERROR: newsroom execution raised "
                f"{type(exc).__name__}; stopping fallback."
            )
            return 1
        outcome = result.get("outcome")
        if outcome == "CANDIDATE_REJECTED":
            reason = result.get("candidate_rejection_reason") or "UNSPECIFIED"
            print(f"  -> REJECTED")
            print(f"  Reason: {reason}")
            continue
        if outcome == "PUBLISHED":
            external_id = result.get("external_post_id") or ""
            publication_status = str(
                result.get("publication_status") or ""
            ).strip().lower()
            if not external_id or publication_status != "published":
                print(
                    "  [run] RECOVERY_REQUIRED: publication lacks a confirmed "
                    "Threads ID or persisted published status."
                )
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
        if outcome == "RECOVERY_REQUIRED":
            print("  [publisher] RECOVERY_REQUIRED")
            print("  Threads outcome could not be confirmed.")
            print("  [run] Automatic retry disabled to prevent duplicate publication.")
            if result.get("publication_error"):
                print("  [publisher] " + str(result["publication_error"]))
            return 1
        if outcome == "DEFERRED_QUOTA":
            print("  [quota] DEFERRED_QUOTA; stopping candidate processing.")
            print(
                f"  Posts published: {successful_posts}/{target_posts}; "
                f"candidates attempted: {attempted}"
            )
            return 0

        print(
            f"  [run] SYSTEM_ERROR ({outcome or 'UNKNOWN'}); "
            "stopping without trying another candidate."
        )
        return 1

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
            return 1
    try:
        if not db.is_production():
            print("  ERROR: reporting workflow requires the real Supabase backend.")
            return 1
    except Exception as exc:
        print("  ERROR: Supabase is unavailable: " + str(exc))
        return 1

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
        return 1
    print("=" * 70)
    print("NewsRoom Reporting Run")
    print("=" * 70)
    print(f"  publishing=automatic  provider={provider}  model={model_id}")
    print(f"  backend={db.backend_status()}")
    print(f"  Target posts: {target_posts}")
    print(f"  Maximum candidate attempts: {max_attempts}")
    print()
    return _attempt_candidates(
        candidates,
        provider,
        model_id,
        max_attempts=max_attempts,
        target_posts=target_posts,
    )


if __name__ == "__main__":
    sys.exit(main())