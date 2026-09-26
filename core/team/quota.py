"""Daily publishing quota + spacing gate.

Production source of truth: Supabase `publications` table.
Local dev fallback: `data/quota.json` (only used if backend is LOCAL).

Config (env-overridable):
  NEWSROOM_MAX_PER_DAY        default 10
  NEWSROOM_MIN_HOURS_BETWEEN  default 1
  NEWSROOM_ACTIVE_START       default 8    (local hour)
  NEWSROOM_ACTIVE_END         default 23   (local hour, exclusive)
  NEWSROOM_TZ_OFFSET          default 5    (hours from UTC)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

QUOTA_PATH = Path(__file__).resolve().parents[2] / "data" / "quota.json"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default


def _local_now() -> datetime:
    offset = _env_int("NEWSROOM_TZ_OFFSET", 5)
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=offset)))


def _local_date() -> str:
    return _local_now().strftime("%Y-%m-%d")


def _local_store_read() -> dict[str, Any]:
    if not QUOTA_PATH.exists():
        return {}
    try:
        return json.loads(QUOTA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _local_store_write(state: dict[str, Any]) -> None:
    QUOTA_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUOTA_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _is_supabase() -> bool:
    try:
        from core.tools.database.client import is_production
        return is_production()
    except Exception:
        return False


def can_publish() -> tuple[bool, str, dict[str, Any]]:
    """Return (allowed, reason, state).

    Supabase path:
      - daily count from publications where status='published' AND published_at >= today
      - last_published_at from publications order by published_at DESC limit 1
    Local path:
      - reads data/quota.json

    Fail-closed: if the Supabase query fails, returns (False, reason, state).
    """
    max_per_day = _env_int("NEWSROOM_MAX_PER_DAY", 10)
    min_hours = _env_int("NEWSROOM_MIN_HOURS_BETWEEN", 1)
    active_start = _env_int("NEWSROOM_ACTIVE_START", 8)
    active_end = _env_int("NEWSROOM_ACTIVE_END", 23)

    state: dict[str, Any] = {
        "date": _local_date(),
        "max_per_day": max_per_day,
        "source": "local",
    }

    # ── Active hours check (applies to both paths) ──
    hour = _local_now().hour
    if not (active_start <= hour < active_end):
        state["published"] = 0
        state["last_published_at"] = None
        return (
            False,
            f"outside active hours ({active_start}-{active_end}, now {hour})",
            state,
        )

    # ── Published-today count + last-published timestamp ──
    published_today = 0
    last_published = None

    if _is_supabase():
        try:
            from core.tools.database import stories as _db
            published_today = _db.count_published_today()
            last_published = _db.last_published_at()
            state["source"] = "supabase"
        except Exception as exc:
            state["error"] = f"{type(exc).__name__}: {exc}"
            return (
                False,
                f"quota unavailable (fail-closed): {state['error']}",
                state,
            )
    else:
        data = _local_store_read()
        if data.get("date") == _local_date():
            published_today = int(data.get("published", 0))
        last_published = data.get("last_published_at")

    state["published"] = published_today
    state["last_published_at"] = last_published

    # ── Daily cap ──
    if published_today >= max_per_day:
        return False, f"daily cap reached ({published_today}/{max_per_day})", state

    # ── Spacing ──
    if last_published:
        try:
            last = datetime.fromisoformat(str(last_published).replace("Z", "+00:00"))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            elapsed = datetime.now(timezone.utc) - last
            if elapsed < timedelta(hours=min_hours):
                remaining = timedelta(hours=min_hours) - elapsed
                mins = int(remaining.total_seconds() // 60)
                return False, f"spacing not met ({mins}m remaining)", state
        except Exception:
            pass

    return True, "ok", state


def record_publication() -> None:
    """Local-only bookkeeping. In production, Supabase publications is the record."""
    if _is_supabase():
        return
    state = _local_store_read()
    today = _local_date()
    if state.get("date") != today:
        state = {"date": today, "published": 0, "last_published_at": None}
    state["published"] = int(state.get("published", 0)) + 1
    state["last_published_at"] = datetime.now(timezone.utc).isoformat()
    _local_store_write(state)


def record_deferral() -> None:
    if _is_supabase():
        return
    state = _local_store_read()
    today = _local_date()
    if state.get("date") != today:
        state = {"date": today, "published": 0, "last_published_at": None, "deferred": 0}
    state["deferred"] = int(state.get("deferred", 0)) + 1
    _local_store_write(state)


def status() -> dict[str, Any]:
    allowed, reason, state = can_publish()
    state["allowed"] = allowed
    state["reason"] = reason
    return state
