"""Executable checks for reporting active-hours and quota safeguards."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.team import quota  # noqa: E402
from core.team.graph import node_quota_gate  # noqa: E402


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  PASS: {message}")


def main() -> int:
    original_env = {
        name: os.environ.get(name)
        for name in (
            "NEWSROOM_BYPASS_ACTIVE_HOURS",
            "NEWSROOM_ACTIVE_START",
            "NEWSROOM_ACTIVE_END",
            "NEWSROOM_MAX_PER_DAY",
            "NEWSROOM_MIN_HOURS_BETWEEN",
        )
    }
    original_local_now = quota._local_now
    original_is_supabase = quota._is_supabase
    original_local_store_read = quota._local_store_read
    original_can_publish = quota.can_publish
    original_record_deferral = quota.record_deferral
    from core.tools.database import stories as db
    original_count_published = db.count_published_today
    original_last_published = db.last_published_at

    try:
        quota._is_supabase = lambda: False
        quota._local_store_read = lambda: {}
        os.environ["NEWSROOM_ACTIVE_START"] = "20"
        os.environ["NEWSROOM_ACTIVE_END"] = "24"
        os.environ["NEWSROOM_MAX_PER_DAY"] = "5"
        os.environ["NEWSROOM_MIN_HOURS_BETWEEN"] = "1"

        quota._local_now = lambda: datetime(2026, 9, 29, 20, tzinfo=timezone.utc)
        os.environ.pop("NEWSROOM_BYPASS_ACTIVE_HOURS", None)
        allowed, reason, state = quota.can_publish()
        _assert(allowed, "active-hours reporting is allowed")

        quota._local_now = lambda: datetime(2026, 9, 29, 7, tzinfo=timezone.utc)
        os.environ["NEWSROOM_BYPASS_ACTIVE_HOURS"] = "true"
        allowed, reason, _ = quota.can_publish()
        _assert(
            not allowed and "outside active hours" in reason,
            "out-of-hours reporting remains blocked even if the removed bypass variable is set",
        )
        gate_result = node_quota_gate({
            "outcome": "RUNNING",
            "dry_run": True,
            "mode": "reporting",
            "messages": [],
        })
        _assert(
            gate_result.get("outcome") == "DEFERRED_QUOTA",
            "dry-run quota gate reports the out-of-hours deferral",
        )

        quota._local_now = lambda: datetime(2026, 9, 29, 20, tzinfo=timezone.utc)
        quota._local_store_read = lambda: {
            "date": quota._local_date(),
            "published": 5,
            "last_published_at": None,
        }
        allowed, reason, _ = quota.can_publish()
        _assert(
            not allowed and "daily cap reached" in reason,
            "daily cap remains enforced",
        )

        quota._local_store_read = lambda: {
            "date": quota._local_date(),
            "published": 1,
            "last_published_at": (
                datetime.now(timezone.utc) - timedelta(minutes=20)
            ).isoformat(),
        }
        allowed, reason, state = quota.can_publish()
        _assert(
            not allowed and "spacing not met" in reason,
            "removed bypass variable cannot bypass minimum spacing",
        )

        allowed, reason, state = quota.can_publish()
        _assert(
            not allowed and "spacing not met" in reason,
            "scheduled reporting still enforces minimum spacing",
        )
        quota.can_publish = lambda **_: (
            False,
            "spacing not met (37m remaining)",
            {"source": "supabase"},
        )
        quota.record_deferral = lambda: None
        deferred = node_quota_gate({
            "outcome": "RUNNING",
            "dry_run": False,
            "mode": "reporting",
            "messages": [],
        })
        _assert(
            deferred.get("outcome") == "DEFERRED_QUOTA",
            "live quota gate exposes spacing as a safe terminal deferral",
        )
        quota.can_publish = original_can_publish
        quota.record_deferral = original_record_deferral

        quota._is_supabase = lambda: True
        db.count_published_today = lambda: 1
        db.last_published_at = lambda: (
            datetime.now(timezone.utc) - timedelta(minutes=20)
        ).isoformat()
        allowed, reason, state = quota.can_publish(publication_type="normal")
        _assert(
            not allowed and "spacing not met" in reason,
            "Supabase reporting quota enforces minimum spacing",
        )
        db.count_published_today = lambda: 5
        allowed, reason, _ = quota.can_publish(publication_type="normal")
        _assert(
            not allowed and "daily cap reached" in reason,
            "Supabase daily cap remains enforced",
        )

        db.count_published_today = lambda: 1
        allowed, reason, state = quota.can_publish(publication_type="breaking")
        _assert(
            allowed
            and "active_hours_bypassed" not in state
            and "spacing_bypassed" not in state,
            "breaking-news quota remains independent of reporting restrictions",
        )

        print("Active-hours quota checks — ALL PASS")
        return 0
    finally:
        quota._local_now = original_local_now
        quota._is_supabase = original_is_supabase
        quota._local_store_read = original_local_store_read
        quota.can_publish = original_can_publish
        quota.record_deferral = original_record_deferral
        db.count_published_today = original_count_published
        db.last_published_at = original_last_published
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":
    sys.exit(main())
