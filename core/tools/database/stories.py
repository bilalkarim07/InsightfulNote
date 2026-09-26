"""Semantic database tools for the agent layer.

Agents never see the raw client. These functions are the stable boundary.

Every function:
  - never raises on missing data (returns None or [])
  - never exposes the client
  - works identically against Supabase and the local fallback
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Optional

from core.tools.database.client import get_client, is_production, mode
from core.tools.database import schema as S


def backend_status() -> str:
    return "SUPABASE" if is_production() else f"LOCAL ({mode()})"


# ── Reads ──────────────────────────────────────────────────────

def _local_or_supabase_select(table: str, **filters: Any) -> list[dict]:
    client = get_client()
    if not is_production():
        return client.select(table, **filters)
    try:
        q = client.table(table).select("*")
        for k, v in filters.items():
            q = q.eq(k, v)
        return q.execute().data or []
    except Exception as exc:
        print(f"  [db] select {table} failed: {exc}")
        return []


def get_story(story_id: str) -> Optional[dict[str, Any]]:
    rows = _local_or_supabase_select(S.STORIES, **{S.PK_STORY: story_id})
    return rows[0] if rows else None


def find_recent_stories(limit: int = 20, topic: Optional[str] = None) -> list[dict[str, Any]]:
    client = get_client()
    if not is_production():
        rows = client.select(S.STORIES)
        if topic:
            rows = [r for r in rows if r.get("topic") == topic]
        return rows[-limit:]
    try:
        q = client.table(S.STORIES).select("*").order("first_seen_at", desc=True).limit(limit)
        if topic:
            q = q.eq("topic", topic)
        return q.execute().data or []
    except Exception as exc:
        print(f"  [db] find_recent_stories failed: {exc}")
        return []


def get_story_sources(story_id: str) -> list[dict[str, Any]]:
    return _local_or_supabase_select(S.SOURCES, **{S.PK_STORY: story_id})


def get_story_claims(story_id: str) -> list[dict[str, Any]]:
    return _local_or_supabase_select(S.CLAIMS, **{S.PK_STORY: story_id})


def get_story_evidence(story_id: str) -> list[dict[str, Any]]:
    return _local_or_supabase_select(S.EVIDENCE, **{S.PK_STORY: story_id})


def find_duplicate_publication(
    story_id: str, platform: str = S.PLATFORM_THREADS,
) -> Optional[dict[str, Any]]:
    rows = _local_or_supabase_select(
        S.PUBLICATIONS, **{S.PK_STORY: story_id, "platform": platform},
    )
    for r in rows:
        if r.get("status") == "PUBLISHED":
            return r
    return None


# ── Writes ─────────────────────────────────────────────────────

def _upsert(table: str, row: dict, key: str) -> str:
    client = get_client()
    if not is_production():
        client.upsert(table, row, key=key)
        return str(row.get(key, ""))
    try:
        client.table(table).upsert(row, on_conflict=key).execute()
        return str(row.get(key, ""))
    except Exception as exc:
        print(f"  [db] upsert {table} failed: {exc}")
        raise


def save_story(story: dict[str, Any]) -> str:
    """Persist or update a story. Idempotent by story_id.

    Preserves the original first_seen_at across upserts so recency-based
    selection (breaking news) reflects when the story was truly first seen.
    """
    story_id = story.get(S.PK_STORY, "")
    existing = get_story(story_id) if story_id else None
    now = datetime.now(timezone.utc).isoformat()
    story = {**story}
    if existing and existing.get("first_seen_at"):
        story["first_seen_at"] = existing["first_seen_at"]
    else:
        story.setdefault("first_seen_at", now)
    story["latest_seen_at"] = now
    return _upsert(S.STORIES, story, key=S.PK_STORY)


def save_source(source: dict[str, Any]) -> str:
    return _upsert(S.SOURCES, source, key=S.PK_SOURCE)


def save_research_result(run_id: str, payload: dict[str, Any]) -> str:
    """Persist claims and evidence produced by the Research stage."""
    story_id = payload.get("story_id", "")
    for claim in payload.get("claims", []) or []:
        row = {**claim, "story_id": story_id, "run_id": run_id}
        _upsert(S.CLAIMS, row, key=S.PK_CLAIM)
    for ev in payload.get("evidence", []) or []:
        row = {**ev, "story_id": story_id, "run_id": run_id}
        _upsert(S.EVIDENCE, row, key=S.PK_EVIDENCE)
    return f"research/{run_id}"


def save_verification_result(run_id: str, payload: dict[str, Any]) -> str:
    story_id = payload.get("story_id", "")
    for v in payload.get("verifications", []) or []:
        row = {**v, "story_id": story_id, "run_id": run_id, "kind": "verification"}
        _upsert(S.CLAIMS, row, key="claim_id")
    return f"verification/{run_id}"


def save_editorial_decision(run_id: str, payload: dict[str, Any]) -> str:
    story_id = payload.get("story_id", "")
    row = {**payload, "story_id": story_id, "run_id": run_id, "kind": "editorial"}
    _upsert(S.STORIES, {"story_id": story_id, "editorial": payload,
                        "run_id": run_id}, key=S.PK_STORY)
    return f"editorial/{run_id}"


def save_publication_result(run_id: str, payload: dict[str, Any]) -> str:
    """Persist a publication record. Idempotent by publication_id."""
    row = {**payload, "run_id": run_id}
    row.setdefault("platform", S.PLATFORM_THREADS)
    row.setdefault("published_at", datetime.now(timezone.utc).isoformat())
    return _upsert(S.PUBLICATIONS, row, key=S.PK_PUBLICATION)


def save_pipeline_run(run_id: str, payload: dict[str, Any]) -> str:
    row = {**payload, "run_id": run_id,
           "created_at": datetime.now(timezone.utc).isoformat()}
    return _upsert(S.PIPELINE_RUNS, row, key="run_id")

def find_unpublished_candidates(
    *,
    max_age_minutes: int = 360,
    min_source_count: int = 1,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return recent stories not yet published, ranked by freshness.

    Ordering:
      1. story with most source_ids (independent support)
      2. then most recent first_seen_at
    """
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    rows = _local_or_supabase_select(S.STORIES)
    out: list[dict[str, Any]] = []
    for r in rows:
        # Skip synthetic/dev test stories.
        sid = r.get(S.PK_STORY, "")
        if not sid or sid.startswith("story_test"):
            continue
        srcs = r.get("source_ids") or []
        if "test" in srcs:
            continue
        # Freshness filter
        fs = r.get("first_seen_at") or r.get("latest_seen_at") or ""
        try:
            ts = datetime.fromisoformat(fs.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue
        except Exception:
            pass  # can't parse → include it, let the caller decide
        # Source-count filter
        n_sources = len(r.get("source_ids") or [])
        if n_sources < min_source_count:
            continue
        # Already published?
        if find_duplicate_publication(r.get(S.PK_STORY, "")):
            continue
        out.append(r)
    def rank(r: dict) -> tuple[int, str]:
        n = len(r.get("source_ids") or [])
        fs = r.get("first_seen_at") or ""
        # Sort descending by source count, then descending by first_seen_at.
        return (-n, fs)
    out.sort(key=rank, reverse=False)
    return out[:limit]

def find_reporting_candidates(
    *,
    max_age_minutes: int = 1440,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Return candidates for the evening reporting slot.

    Unlike breaking, this favors diversity across topics. We exclude
    stories already published and rank by source count. Diversity is
    applied by the caller (which picks one candidate).
    """
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    rows = _local_or_supabase_select(S.STORIES)
    out: list[dict[str, Any]] = []
    for r in rows:
        sid = r.get(S.PK_STORY, "")
        if not sid or sid.startswith("story_test"):
            continue
        srcs = r.get("source_ids") or []
        if "test" in srcs:
            continue
        fs = r.get("first_seen_at") or r.get("latest_seen_at") or ""
        try:
            ts = datetime.fromisoformat(fs.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue
        except Exception:
            pass
        if find_duplicate_publication(sid):
            continue
        out.append(r)
    def rank(r: dict) -> tuple[int, str]:
        n = len(r.get("source_ids") or [])
        fs = r.get("first_seen_at") or ""
        return (-n, fs)
    out.sort(key=rank)
    return out[:limit]