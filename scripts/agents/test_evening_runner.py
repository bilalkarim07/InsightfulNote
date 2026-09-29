"""Test evening reporting selection (deterministic)."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from core.tools.database import stories as db  # noqa: E402
from core.team.graph import _validation_retry_target  # noqa: E402
from core.team.state import MAX_WRITER_ATTEMPTS  # noqa: E402
from core.tools import publishing as threads_publishing  # noqa: E402
from sources.threads.exceptions import (  # noqa: E402
    ThreadsAuthenticationError,
    ThreadsPublishingError,
)
from scripts.agents.run_evening_reporting import (  # noqa: E402
    _attempt_candidates,
    select_candidates,
)


def _candidate(index: int) -> dict:
    return {
        "id": f"story-{index}",
        "title": f"Candidate {index}",
        "source_ids": [f"source-{index}"],
    }


def _test_candidate_fallback() -> None:
    def memory_builder(**_) -> dict:
        return {}

    candidates = [_candidate(index) for index in range(1, 4)]

    calls: list[str] = []

    def reject_then_pass(*_args, result_out, **kwargs) -> int:
        del _args
        calls.append(kwargs["story_id"])
        if len(calls) == 1:
            result_out.update({
                "outcome": "CANDIDATE_REJECTED",
                "candidate_rejection_reason": "INSUFFICIENT_EVIDENCE",
            })
            return 1
        result_out.update({
            "outcome": "PUBLISHED",
            "external_post_id": "confirmed-post-id",
        })
        return 0

    rc = _attempt_candidates(
        candidates,
        "provider",
        "model",
        False,
        max_attempts=5,
        team_runner=reject_then_pass,
        memory_builder=memory_builder,
    )
    assert rc == 0 and calls == ["story-1", "story-2"]

    calls.clear()

    def always_reject(*_args, result_out, **kwargs) -> int:
        del _args
        calls.append(kwargs["story_id"])
        result_out.update({
            "outcome": "CANDIDATE_REJECTED",
            "candidate_rejection_reason": "QA_FAILED",
        })
        return 1

    rc = _attempt_candidates(
        candidates,
        "provider",
        "model",
        False,
        max_attempts=2,
        team_runner=always_reject,
        memory_builder=memory_builder,
    )
    assert rc == 0 and calls == ["story-1", "story-2"]

    calls.clear()

    def system_failure(*_args, result_out, **kwargs) -> int:
        del _args
        calls.append(kwargs["story_id"])
        result_out["outcome"] = "ESCALATE"
        return 1

    rc = _attempt_candidates(
        candidates,
        "provider",
        "model",
        False,
        max_attempts=5,
        team_runner=system_failure,
        memory_builder=memory_builder,
    )
    assert rc == 1 and calls == ["story-1"]

    calls.clear()

    def uncertain_publication(*_args, result_out, **kwargs) -> int:
        del _args
        calls.append(kwargs["story_id"])
        result_out.update({
            "outcome": "RECOVERY_REQUIRED",
            "publication_error": "Threads response did not contain an ID",
        })
        return 1

    rc = _attempt_candidates(
        candidates,
        "provider",
        "model",
        True,
        max_attempts=5,
        team_runner=uncertain_publication,
        memory_builder=memory_builder,
    )
    assert rc == 1 and calls == ["story-1"]

    calls.clear()

    def deferred_quota(*_args, result_out, **kwargs) -> int:
        del _args
        calls.append(kwargs["story_id"])
        result_out["outcome"] = "DEFERRED_QUOTA"
        return 1

    rc = _attempt_candidates(
        candidates,
        "provider",
        "model",
        True,
        max_attempts=5,
        team_runner=deferred_quota,
        memory_builder=memory_builder,
    )
    assert rc == 0 and calls == ["story-1"]

    calls.clear()

    def actual_exception(*_args, **kwargs) -> int:
        del _args, kwargs
        raise RuntimeError("simulated provider failure")

    rc = _attempt_candidates(
        candidates,
        "provider",
        "model",
        True,
        max_attempts=5,
        team_runner=actual_exception,
        memory_builder=memory_builder,
    )
    assert rc == 1

    calls.clear()
    rc = _attempt_candidates(
        [],
        "provider",
        "model",
        False,
        max_attempts=5,
        team_runner=system_failure,
        memory_builder=memory_builder,
    )
    assert rc == 0 and calls == []
    assert MAX_WRITER_ATTEMPTS == 2
    assert _validation_retry_target(
        {"iteration": {"writer": 1}}, ["empty post text"],
    ) == "writer"
    assert _validation_retry_target(
        {"iteration": {"writer": 2}}, ["empty post text"],
    ) is None
    print("  Candidate fallback checks: PASS")


def _test_candidate_eligibility() -> None:
    from schemas.taxonomy import Category

    original_candidates = db.find_reporting_candidates
    original_distribution = db.get_recent_category_distribution
    valid_categories = [category.value for category in Category]
    candidates = [
        {
            "id": f"valid-{category}",
            "title": f"Valid story about {category.lower()}",
            "categories": [category],
            "_source_count": 1,
        }
        for category in valid_categories
    ]
    candidates.extend([
        {
            "id": "politics-alias",
            "title": "Story about politics",
            "categories": ["politics"],
            "_source_count": 1,
        },
        {
            "id": "metadata-category",
            "title": "Story from metadata category",
            "categories": [],
            "metadata": {"categories": ["FINANCE"]},
            "_source_count": 1,
        },
        {
            "id": "no-category",
            "title": "Story without a category",
            "categories": [],
            "_source_count": 1,
        },
        {
            "id": "invalid-category",
            "title": "Story with art category",
            "categories": ["ART"],
            "_source_count": 1,
        },
        {
            "id": "sports",
            "title": "Sports story",
            "categories": ["SPORTS"],
            "_source_count": 1,
        },
        {
            "id": "celebrity",
            "title": "Celebrity story",
            "categories": ["CELEBRITY"],
            "_source_count": 1,
        },
        {
            "id": "entertainment",
            "title": "Entertainment story",
            "categories": ["ENTERTAINMENT"],
            "_source_count": 1,
        },
        {
            "title": "Story missing ID",
            "categories": ["FINANCE"],
            "_source_count": 1,
        },
        {
            "id": "no-title",
            "title": " ",
            "categories": ["FINANCE"],
            "_source_count": 1,
        },
        {
            "id": "no-sources",
            "title": "Story missing sources",
            "categories": ["FINANCE"],
            "_source_count": 0,
        },
    ])

    try:
        db.find_reporting_candidates = lambda **_: candidates
        db.get_recent_category_distribution = lambda **_: {}
        selected = select_candidates(limit=30)
    finally:
        db.find_reporting_candidates = original_candidates
        db.get_recent_category_distribution = original_distribution

    selected_by_id = {
        candidate.get("id"): candidate for candidate in selected
    }
    assert len(selected) == len(valid_categories) + 2
    assert selected_by_id["politics-alias"]["categories"] == ["GLOBAL_POLITICS"]
    assert selected_by_id["metadata-category"]["categories"] == ["FINANCE"]
    assert all(candidate.get("id") for candidate in selected)
    assert not any(
        candidate.get("id") in {
            "no-category", "invalid-category", "sports", "celebrity",
            "entertainment", "no-title", "no-sources",
        }
        for candidate in selected
    )
    print("  Candidate eligibility checks: PASS")


def _test_threads_result_classification() -> None:
    original_available = threads_publishing._AVAILABLE
    original_factory = threads_publishing.build_threads_api

    class FakeAPI:
        def __init__(self, result: dict | Exception) -> None:
            self.result = result

        def create_post(self, *, text: str) -> dict:
            del text
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

        def close(self) -> None:
            return None

    try:
        threads_publishing._AVAILABLE = True
        threads_publishing.build_threads_api = lambda: FakeAPI({"id": "post-1"})
        published = threads_publishing.publish_threads("safe test text", dry_run=False)
        assert published["status"] == "PUBLISHED"
        assert published["external_id"] == "post-1"

        threads_publishing.build_threads_api = lambda: FakeAPI(
            {"status": "ok", "message": "created"}
        )
        unknown = threads_publishing.publish_threads("safe test text", dry_run=False)
        assert unknown["status"] == "UNKNOWN"
        assert unknown["diagnostic"]["response_keys"] == ["message", "status"]

        threads_publishing.build_threads_api = lambda: FakeAPI(
            ThreadsPublishingError("non-secret simulated publish failure")
        )
        uncertain = threads_publishing.publish_threads("safe test text", dry_run=False)
        assert uncertain["status"] == "UNKNOWN"
        assert "reconciliation required" in uncertain["error"]

        auth_failure = ThreadsPublishingError("non-secret simulated publish failure")
        auth_failure.__cause__ = ThreadsAuthenticationError(
            "non-secret authentication failure",
            status_code=401,
        )
        threads_publishing.build_threads_api = lambda: FakeAPI(auth_failure)
        rejected = threads_publishing.publish_threads("safe test text", dry_run=False)
        assert rejected["status"] == "FAILED"
        assert rejected["diagnostic"]["cause_status_code"] == 401
    finally:
        threads_publishing._AVAILABLE = original_available
        threads_publishing.build_threads_api = original_factory
    print("  Threads result classification checks: PASS")


def main() -> int:
    print("=" * 70)
    print("Evening reporting selection test")
    print("=" * 70)
    print(f"  backend: {db.backend_status()}")
    print()
    _test_candidate_fallback()
    _test_candidate_eligibility()
    _test_threads_result_classification()

    cands = db.find_reporting_candidates(max_age_minutes=1440, limit=10)
    print(f"  candidates in last 24h: {len(cands)}")
    for c in cands[:5]:
        sid = c.get("story_id", "?")
        title = (c.get("title") or "")[:60]
        srcs = len(c.get("source_ids") or [])
        print(f"    {sid}  [{srcs} src]  {title}")
    print()

    if not cands:
        print("  NOTE: no candidates — run scripts/run_news_ingestion.py first.")
        print("  Selection logic: PASS (empty input handled)")
        return 0

    print(f"  Selection logic: PASS ({len(cands)} eligible)")
    return 0


if __name__ == "__main__":
    sys.exit(main())