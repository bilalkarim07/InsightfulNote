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

    try:
        quota._is_supabase = lambda: False
        quota._local_store_read = lambda: {}
        os.environ["NEWSROOM_ACTIVE_START"] = "8"
        os.environ["NEWSROOM_ACTIVE_END"] = "24"
        os.environ["NEWSROOM_MAX_PER_DAY"] = "5"
        os.environ["NEWSROOM_MIN_HOURS_BETWEEN"] = "1"

        quota._local_now = lambda: datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
        os.environ.pop("NEWSROOM_BYPASS_ACTIVE_HOURS", None)
        allowed, reason, _ = quota.can_publish()
        _assert(allowed, "active-hours reporting is allowed")

        quota._local_now = lambda: datetime(2026, 9, 29, 1, tzinfo=timezone.utc)
        allowed, reason, _ = quota.can_publish()
        _assert(
            not allowed and "outside active hours" in reason,
            "out-of-hours reporting is blocked by default",
        )

        os.environ["NEWSROOM_BYPASS_ACTIVE_HOURS"] = "true"
        allowed, reason, state = quota.can_publish()
        _assert(
            allowed and state.get("active_hours_bypassed") is True,
            "manual active-hours bypass permits testing and reports telemetry",
        )
        gate_result = node_quota_gate({
            "outcome": "RUNNING",
            "dry_run": True,
            "mode": "reporting",
            "messages": [],
        })
        _assert(
            "active-hours bypass enabled" in gate_result["messages"][0]["content"],
            "dry-run quota telemetry reports the manual bypass setting",
        )

        quota._local_store_read = lambda: {
            "date": quota._local_date(),
            "published": 5,
            "last_published_at": None,
        }
        allowed, reason, _ = quota.can_publish()
        _assert(
            not allowed and "daily cap reached" in reason,
            "active-hours bypass does not override the daily cap",
        )

        quota._local_store_read = lambda: {
            "date": quota._local_date(),
            "published": 1,
            "last_published_at": (
                datetime.now(timezone.utc) - timedelta(minutes=20)
            ).isoformat(),
        }
        allowed, reason, _ = quota.can_publish()
        _assert(
            not allowed and "spacing not met" in reason,
            "active-hours bypass does not override minimum spacing",
        )

        allowed, reason, state = quota.can_publish(publication_type="breaking")
        _assert(
            allowed and "active_hours_bypassed" not in state,
            "breaking-news quota behavior remains independent of the bypass",
        )

        print("Active-hours quota checks — ALL PASS")
        return 0
    finally:
        quota._local_now = original_local_now
        quota._is_supabase = original_is_supabase
        quota._local_store_read = original_local_store_read
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":
    sys.exit(main())
