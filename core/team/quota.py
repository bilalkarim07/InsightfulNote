"""Daily publishing quota + active-hours gate.

Config (env-overridable):
  NEWSROOM_MAX_PER_DAY        default 10
  NEWSROOM_MIN_HOURS_BETWEEN  default 1
  NEWSROOM_ACTIVE_START       default 8   (local hour)
  NEWSROOM_ACTIVE_END         default 23  (local hour, exclusive)
  NEWSROOM_TZ_OFFSET          default 5   (hours from UTC — Pakistan)

State persisted to data/quota.json, committed by the workflow.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

QUOTA_PATH = Path(__file__).resolve().parents[2] / "data" / "quota.json"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default


@dataclass
class QuotaState:
    date: str = ""
    published: int = 0
    last_published_at: str | None = None
    deferred_today: int = 0

    @classmethod
    def load(cls) -> "QuotaState":
        if not QUOTA_PATH.exists():
            return cls()
        try:
            data = json.loads(QUOTA_PATH.read_text(encoding="utf-8"))
            return cls(
                date=data.get("date", ""),
                published=int(data.get("published", 0)),
                last_published_at=data.get("last_published_at"),
                deferred_today=int(data.get("deferred_today", 0)),
            )
        except Exception:
            return cls()

    def save(self) -> None:
        QUOTA_PATH.parent.mkdir(parents=True, exist_ok=True)
        QUOTA_PATH.write_text(
            json.dumps({
                "date": self.date,
                "published": self.published,
                "last_published_at": self.last_published_at,
                "deferred_today": self.deferred_today,
            }, indent=2),
            encoding="utf-8",
        )


def _local_now() -> datetime:
    offset = _env_int("NEWSROOM_TZ_OFFSET", 5)
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=offset)))


def _local_date() -> str:
    return _local_now().strftime("%Y-%m-%d")


def _reset_if_new_day(state: QuotaState) -> None:
    today = _local_date()
    if state.date != today:
        state.date = today
        state.published = 0
        state.deferred_today = 0
        # last_published_at is preserved so spacing still applies across midnight.


def can_publish() -> tuple[bool, str, QuotaState]:
    """Return (allowed, reason, state). Reason is short human-readable text."""
    state = QuotaState.load()
    _reset_if_new_day(state)

    max_per_day = _env_int("NEWSROOM_MAX_PER_DAY", 10)
    min_hours_between = _env_int("NEWSROOM_MIN_HOURS_BETWEEN", 1)
    active_start = _env_int("NEWSROOM_ACTIVE_START", 8)
    active_end = _env_int("NEWSROOM_ACTIVE_END", 23)

    # 1. Daily cap
    if state.published >= max_per_day:
        return False, f"daily cap reached ({state.published}/{max_per_day})", state

    # 2. Active hours (local)
    hour = _local_now().hour
    if not (active_start <= hour < active_end):
        return False, f"outside active hours ({active_start}-{active_end}, now {hour})", state

    # 3. Spacing
    if state.last_published_at:
        try:
            last = datetime.fromisoformat(state.last_published_at)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            elapsed = datetime.now(timezone.utc) - last
            if elapsed < timedelta(hours=min_hours_between):
                remaining = timedelta(hours=min_hours_between) - elapsed
                mins = int(remaining.total_seconds() // 60)
                return False, f"spacing not met ({mins}m remaining)", state
        except Exception:
            pass

    return True, "ok", state


def record_publication() -> None:
    state = QuotaState.load()
    _reset_if_new_day(state)
    state.published += 1
    state.last_published_at = datetime.now(timezone.utc).isoformat()
    state.save()


def record_deferral() -> None:
    state = QuotaState.load()
    _reset_if_new_day(state)
    state.deferred_today += 1
    state.save()


def status() -> dict:
    state = QuotaState.load()
    _reset_if_new_day(state)
    max_per_day = _env_int("NEWSROOM_MAX_PER_DAY", 10)
    return {
        "date": state.date,
        "published": state.published,
        "max_per_day": max_per_day,
        "deferred_today": state.deferred_today,
        "last_published_at": state.last_published_at,
    }