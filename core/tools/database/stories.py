"""Semantic database tools - matches actual Supabase schema.

Chain:
  sources <- news_items <- story_sources -> stories
  claims -> evidence
  publications

Every function is a controlled operation. No raw SQL. No client exposure.
"""
from __future__ import annotations

import hashlib
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from core.tools.database.client import (
    DatabaseUnavailableError, get_client, is_production, mode,
    raise_unavailable,
)
from core.tools.database import schema as S


def backend_status() -> str:
    return "SUPABASE" if is_production() else f"LOCAL ({mode()})"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_missing(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "does not exist" in msg or "not found" in msg or "404" in msg


def _jsonify(value):
    """Recursively convert non-JSON-safe values to JSON-safe ones."""
    from datetime import date, datetime
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonify(v) for v in value]
    # Fallback: stringify anything else.
    return str(value)


def _sanitize_row(row: dict) -> dict:
    """Return a JSON-safe copy of a row."""
    return {k: _jsonify(v) for k, v in row.items()}


def _new_uuid() -> str:
    return str(_uuid.uuid4())


# ============================================================
# sources
# ============================================================

def get_or_create_source(
    *,
    name: str,
    source_type: str,
    domain: Optional[str] = None,
    base_url: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> str:
    """Return the UUID of a source, creating it if missing."""
    client = get_client()
    if not is_production():
        rows = client.select(S.SOURCES, name=name)
        if rows:
            return rows[0]["id"]
        new = {
            "id": _new_uuid(),
            "name": name,
            "source_type": source_type,
            "domain": domain,
            "base_url": base_url,
            "metadata": metadata or {},
            "is_active": True,
        }
        client.insert(S.SOURCES, new)
        return new["id"]

    try:
        r = client.table(S.SOURCES).select("id").eq("name", name).limit(1).execute()
        if r.data:
            return r.data[0]["id"]
        payload = {
            "name": name,
            "source_type": source_type,
            "domain": domain,
            "base_url": base_url,
            "metadata": metadata or {},
        }
        r2 = client.table(S.SOURCES).insert(payload).execute()
        if not r2.data:
            raise RuntimeError("insert returned no data")
        return r2.data[0]["id"]
    except DatabaseUnavailableError:
        raise
    except Exception as exc:
        raise_unavailable("get_or_create_source", exc)


# ============================================================
# news_items
# ============================================================

def upsert_news_item(item: dict[str, Any]) -> str:
    """Insert or update a news_item. Returns its id (TEXT)."""
    client = get_client()

    url = item.get("url") or item.get("canonical_url") or ""
    if not url:
        raise ValueError("news_item.url is required")

    if not item.get("id"):
        item["id"] = "ni_" + hashlib.sha256(url.encode()).hexdigest()[:24]

    item.setdefault("categories", [])
    item.setdefault("metadata", {})
    if not item.get("discovered_at"):
        item["discovered_at"] = _now()

    item = _sanitize_row(item)

    if not is_production():
        client.upsert(S.NEWS_ITEMS, item, key="id")
        return item["id"]

    try:
        client.table(S.NEWS_ITEMS).upsert(item, on_conflict="id").execute()
        return item["id"]
    except Exception as exc:
        raise_unavailable("upsert_news_item", exc)


def get_news_item(news_item_id: str) -> Optional[dict[str, Any]]:
    client = get_client()
    if not is_production():
        rows = client.select(S.NEWS_ITEMS, id=news_item_id)
        return rows[0] if rows else None
    try:
        r = client.table(S.NEWS_ITEMS).select("*").eq("id", news_item_id).limit(1).execute()
        return r.data[0] if r.data else None
    except Exception as exc:
        if _is_missing(exc):
            return None
        raise_unavailable("get_news_item", exc)


def find_news_items_by_story(story_id: str) -> list[dict[str, Any]]:
    """Join story_sources -> news_items."""
    client = get_client()
    if not is_production():
        links = client.select(S.STORY_SOURCES, story_id=story_id)
        ids = {l.get("news_item_id") for l in links}
        return [r for r in client.select(S.NEWS_ITEMS) if r.get("id") in ids]
    try:
        r = (
            client.table(S.STORY_SOURCES)
            .select("news_item_id, news_items(*)")
            .eq("story_id", story_id)
            .execute()
        )
        out = []
        for row in r.data or []:
            ni = row.get("news_items")
            if ni:
                out.append(ni)
        return out
    except Exception as exc:
        raise_unavailable("find_news_items_by_story", exc)


# ============================================================
# stories
# ============================================================

def create_story(
    *,
    title: str,
    summary: Optional[str] = None,
    status: str = S.STORY_STATUS_CANDIDATE,
    metadata: Optional[dict] = None,
) -> str:
    client = get_client()
    if not is_production():
        new = {
            "id": _new_uuid(),
            "title": title,
            "summary": summary,
            "status": status,
            "metadata": metadata or {},
            "first_seen_at": _now(),
            "last_seen_at": _now(),
        }
        client.insert(S.STORIES, new)
        return new["id"]
    try:
        payload = _sanitize_row({
            "title": title,
            "summary": summary,
            "status": status,
            "metadata": metadata or {},
        })
        r = client.table(S.STORIES).insert(payload).execute()
        if not r.data:
            raise RuntimeError("insert returned no data")
        return r.data[0]["id"]
    except Exception as exc:
        raise_unavailable("create_story", exc)


def get_story(story_id: str) -> Optional[dict[str, Any]]:
    client = get_client()
    if not is_production():
        rows = client.select(S.STORIES, id=story_id)
        return rows[0] if rows else None
    try:
        r = client.table(S.STORIES).select("*").eq("id", story_id).limit(1).execute()
        return r.data[0] if r.data else None
    except Exception as exc:
        if _is_missing(exc):
            return None
        raise_unavailable("get_story", exc)


def update_story_status(story_id: str, status: str) -> None:
    client = get_client()
    if not is_production():
        rows = client.select(S.STORIES, id=story_id)
        if rows:
            rows[0]["status"] = status
            rows[0]["updated_at"] = _now()
            client._flush()
        return
    try:
        client.table(S.STORIES).update({"status": status}).eq("id", story_id).execute()
    except Exception as exc:
        raise_unavailable("update_story_status", exc)


def link_story_source(
    story_id: str,
    news_item_id: str,
    relationship: str = S.RELATIONSHIP_REPORTED_BY,
) -> None:
    client = get_client()
    row = {
        "story_id": story_id,
        "news_item_id": news_item_id,
        "relationship": relationship,
    }
    if not is_production():
        existing = client.select(
            S.STORY_SOURCES, story_id=story_id, news_item_id=news_item_id,
        )
        if not existing:
            client.insert(S.STORY_SOURCES, row)
        return
    try:
        client.table(S.STORY_SOURCES).upsert(
            row, on_conflict="story_id,news_item_id",
        ).execute()
    except Exception as exc:
        raise_unavailable("link_story_source", exc)


def get_story_sources(story_id: str) -> list[dict[str, Any]]:
    """Return news_items backing a story, enriched with source metadata."""
    client = get_client()
    items = find_news_items_by_story(story_id)
    if not is_production():
        return items
    out = []
    for item in items:
        enriched = dict(item)
        sid = item.get("source_id")
        if sid:
            try:
                r = client.table(S.SOURCES).select("*").eq("id", sid).limit(1).execute()
                if r.data:
                    enriched["source"] = r.data[0]
                else:
                    enriched["source"] = None
            except Exception as exc:
                raise_unavailable("get_story_sources.source_metadata", exc)
        out.append(enriched)
    return out


# ============================================================
# story candidate queries
# ============================================================

def _story_source_count(client, story_id: str) -> int:
    if not is_production():
        return len(client.select(S.STORY_SOURCES, story_id=story_id))
    try:
        r = (
            client.table(S.STORY_SOURCES)
            .select("news_item_id")
            .eq("story_id", story_id)
            .execute()
        )
        return len(r.data or [])
    except Exception as exc:
        raise_unavailable("_story_source_count", exc)


def _is_eligible_story(story: dict) -> bool:
    status = story.get("status")
    return status in (S.STORY_STATUS_CANDIDATE, S.STORY_STATUS_RESEARCHING)


def find_unpublished_candidates(
    *,
    max_age_minutes: int = 360,
    min_source_count: int = 1,
    limit: int = 20,
) -> list[dict[str, Any]]:
    client = get_client()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)

    if not is_production():
        rows = client.select(S.STORIES)
    else:
        try:
            r = (
                client.table(S.STORIES)
                .select("*")
                .order("last_seen_at", desc=True)
                .limit(100)
                .execute()
            )
            rows = r.data or []
        except Exception as exc:
            raise_unavailable("find_unpublished_candidates", exc)
            return []

    out: list[dict[str, Any]] = []
    for s in rows:
        sid = s.get("id", "")
        if not sid:
            continue
        if not _is_eligible_story(s):
            continue
        ls = s.get("last_seen_at") or s.get("first_seen_at") or ""
        try:
            ts = datetime.fromisoformat(str(ls).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue
        except Exception:
            pass
        try:
            if find_duplicate_publication(sid):
                continue
        except DatabaseUnavailableError:
            raise
        n = _story_source_count(client, sid)
        if n < min_source_count:
            continue
        s["_source_count"] = n
        out.append(s)

    out.sort(key=lambda s: (-s.get("_source_count", 0), s.get("last_seen_at") or ""))
    return out[:limit]


def find_reporting_candidates(
    *,
    max_age_minutes: int = 1440,
    limit: int = 30,
) -> list[dict[str, Any]]:
    client = get_client()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)

    if not is_production():
        rows = client.select(S.STORIES)
    else:
        try:
            r = (
                client.table(S.STORIES)
                .select("*")
                .order("first_seen_at", desc=True)
                .limit(200)
                .execute()
            )
            rows = r.data or []
        except Exception as exc:
            raise_unavailable("find_reporting_candidates", exc)
            return []

    out: list[dict[str, Any]] = []
    for s in rows:
        sid = s.get("id", "")
        if not sid:
            continue
        if not _is_eligible_story(s):
            continue
        fs = s.get("first_seen_at") or ""
        try:
            ts = datetime.fromisoformat(str(fs).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue
        except Exception:
            pass
        try:
            if find_duplicate_publication(sid):
                continue
        except DatabaseUnavailableError:
            raise
        n = _story_source_count(client, sid)
        s["_source_count"] = n
        out.append(s)

    out.sort(key=lambda s: (-s.get("_source_count", 0), s.get("first_seen_at") or ""))
    return out[:limit]


# ============================================================
# claims
# ============================================================

def save_claim(
    *,
    story_id: str,
    claim_text: str,
    claim_type: Optional[str] = None,
    news_item_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> str:
    client = get_client()
    payload = {
        "story_id": story_id,
        "news_item_id": news_item_id,
        "claim_text": claim_text,
        "claim_type": claim_type,
        "status": S.CLAIM_STATUS_UNVERIFIED,
        "metadata": metadata or {},
    }
    payload = _sanitize_row(payload)
    if not is_production():
        new = {**payload, "id": _new_uuid()}
        client.insert(S.CLAIMS, new)
        return new["id"]
    try:
        r = client.table(S.CLAIMS).insert(payload).execute()
        if not r.data:
            raise RuntimeError("insert returned no data")
        return r.data[0]["id"]
    except Exception as exc:
        raise_unavailable("save_claim", exc)


def get_story_claims(story_id: str) -> list[dict[str, Any]]:
    client = get_client()
    if not is_production():
        return client.select(S.CLAIMS, story_id=story_id)
    try:
        r = client.table(S.CLAIMS).select("*").eq("story_id", story_id).execute()
        return r.data or []
    except Exception as exc:
        raise_unavailable("get_story_claims", exc)


def update_claim_status(
    claim_id: str,
    status: str,
    confidence: Optional[float] = None,
) -> None:
    client = get_client()
    update: dict[str, Any] = {"status": status}
    if confidence is not None:
        update["confidence"] = confidence
    if not is_production():
        rows = client.select(S.CLAIMS, id=claim_id)
        if rows:
            rows[0].update(update)
            client._flush()
        return
    try:
        client.table(S.CLAIMS).update(update).eq("id", claim_id).execute()
    except Exception as exc:
        raise_unavailable("update_claim_status", exc)


# ============================================================
# evidence
# ============================================================

def save_evidence(
    *,
    claim_id: str,
    evidence_type: str,
    excerpt: Optional[str] = None,
    url: Optional[str] = None,
    news_item_id: Optional[str] = None,
    source_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> str:
    client = get_client()
    payload = {
        "claim_id": claim_id,
        "news_item_id": news_item_id,
        "source_id": source_id,
        "evidence_type": evidence_type,
        "excerpt": excerpt,
        "url": url,
        "metadata": metadata or {},
    }
    payload = _sanitize_row(payload)
    if not is_production():
        new = {**payload, "id": _new_uuid()}
        client.insert(S.EVIDENCE, new)
        return new["id"]
    try:
        r = client.table(S.EVIDENCE).insert(payload).execute()
        if not r.data:
            raise RuntimeError("insert returned no data")
        return r.data[0]["id"]
    except Exception as exc:
        raise_unavailable("save_evidence", exc)


def get_story_evidence(story_id: str) -> list[dict[str, Any]]:
    claims = get_story_claims(story_id)
    if not claims:
        return []
    claim_ids = [c["id"] for c in claims]
    client = get_client()
    if not is_production():
        return [r for r in client.select(S.EVIDENCE) if r.get("claim_id") in claim_ids]
    try:
        r = (
            client.table(S.EVIDENCE)
            .select("*")
            .in_("claim_id", claim_ids)
            .execute()
        )
        return r.data or []
    except Exception as exc:
        raise_unavailable("get_story_evidence", exc)


# ============================================================
# publications
# ============================================================

def save_publication_result(
    story_id: str,
    payload: dict[str, Any],
) -> str:
    client = get_client()
    row = dict(payload)
    row.setdefault("story_id", story_id)
    row.setdefault("platform", S.PLATFORM_THREADS)
    row.setdefault("status", S.PUBLICATION_STATUS_DRAFT)
    row.setdefault("metadata", {})

    row.pop("publication_id", None)
    if "run_id" in payload:
        row["metadata"] = {
            **row.get("metadata", {}),
            "run_id": payload["run_id"],
        }
    row.pop("run_id", None)
    row.pop("error", None)  # not a real column; goes to metadata
    row = _sanitize_row(row)

    if not is_production():
        new = {**row, "id": _new_uuid()}
        client.insert(S.PUBLICATIONS, new)
        return new["id"]
    try:
        r = client.table(S.PUBLICATIONS).insert(row).execute()
        if not r.data:
            raise RuntimeError("insert returned no data")
        return r.data[0]["id"]
    except Exception as exc:
        raise_unavailable("save_publication_result", exc)


def update_publication_result(
    publication_id: str,
    payload: dict[str, Any],
) -> None:
    """Update a previously reserved publication record."""
    client = get_client()
    row = dict(payload)
    row.pop("id", None)
    row.pop("run_id", None)
    row.pop("error", None)
    row = _sanitize_row(row)

    if not is_production():
        rows = client.select(S.PUBLICATIONS, id=publication_id)
        if not rows:
            raise ValueError(f"Publication record not found: {publication_id}")
        rows[0].update(row)
        client._flush()
        return
    try:
        result = (
            client.table(S.PUBLICATIONS)
            .update(row)
            .eq("id", publication_id)
            .select("id")
            .execute()
        )
        if not result.data:
            raise RuntimeError("publication update returned no data")
    except Exception as exc:
        raise_unavailable("update_publication_result", exc)


def find_duplicate_publication(
    story_id: str,
    platform: str = S.PLATFORM_THREADS,
) -> Optional[dict[str, Any]]:
    client = get_client()
    live_statuses = (
        S.PUBLICATION_STATUS_PUBLISHED,
        S.PUBLICATION_STATUS_APPROVED,
        S.PUBLICATION_STATUS_PUBLISHING,
        "PUBLISHED",
        "APPROVED",
        "PUBLISHING",
    )
    if not is_production():
        rows = client.select(S.PUBLICATIONS, story_id=story_id, platform=platform)
        return next(
            (r for status in live_statuses for r in rows if r.get("status") == status),
            None,
        )
    try:
        r = (
            client.table(S.PUBLICATIONS)
            .select("*")
            .eq("story_id", story_id)
            .eq("platform", platform)
            .in_("status", list(live_statuses))
            .limit(10)
            .execute()
        )
        rows = r.data or []
        return next(
            (row for status in live_statuses for row in rows if row.get("status") == status),
            None,
        )
    except Exception as exc:
        raise_unavailable("find_duplicate_publication", exc)


def count_published_today(platform: str = S.PLATFORM_THREADS) -> int:
    client = get_client()
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if not is_production():
        count = 0
        for r in client.select(S.PUBLICATIONS, platform=platform):
            if r.get("status") != S.PUBLICATION_STATUS_PUBLISHED:
                continue
            pa = r.get("published_at") or ""
            try:
                ts = datetime.fromisoformat(str(pa).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= start:
                    count += 1
            except Exception:
                pass
        return count
    try:
        r = (
            client.table(S.PUBLICATIONS)
            .select("id", count="exact")
            .eq("platform", platform)
            .eq("status", S.PUBLICATION_STATUS_PUBLISHED)
            .gte("published_at", start.isoformat())
            .execute()
        )
        return r.count or 0
    except Exception as exc:
        raise_unavailable("count_published_today", exc)


def last_published_at(platform: str = S.PLATFORM_THREADS) -> Optional[str]:
    client = get_client()
    if not is_production():
        pubs = [
            r for r in client.select(S.PUBLICATIONS, platform=platform)
            if r.get("status") == S.PUBLICATION_STATUS_PUBLISHED
        ]
        pubs.sort(key=lambda r: r.get("published_at") or "", reverse=True)
        return pubs[0].get("published_at") if pubs else None
    try:
        r = (
            client.table(S.PUBLICATIONS)
            .select("published_at")
            .eq("platform", platform)
            .eq("status", S.PUBLICATION_STATUS_PUBLISHED)
            .order("published_at", desc=True)
            .limit(1)
            .execute()
        )
        return r.data[0]["published_at"] if r.data else None
    except Exception as exc:
        raise_unavailable("last_published_at", exc)


# ============================================================
# Compatibility shims for the graph
# ============================================================

def save_story(story: dict) -> str:
    client = get_client()
    sid = story.get("id")
    if not sid:
        return create_story(
            title=story.get("title", ""),
            summary=story.get("summary"),
        )
    story = _sanitize_row(story)
    if not is_production():
        client.upsert(S.STORIES, story, key="id")
        return sid
    try:
        client.table(S.STORIES).upsert(story, on_conflict="id").execute()
        return sid
    except Exception as exc:
        raise_unavailable("save_story", exc)


def save_source(source: dict) -> str:
    return get_or_create_source(
        name=source.get("name", ""),
        source_type=source.get("source_type", "unknown"),
        domain=source.get("domain"),
        base_url=source.get("base_url"),
        metadata=source.get("metadata"),
    )


def save_research_result(run_id: str, payload: dict) -> str:
    story_id = payload.get("story_id")
    if not story_id:
        raise ValueError("save_research_result requires story_id")
    claim_map: dict[str, str] = {}
    for claim in payload.get("claims", []):
        cid = save_claim(
            story_id=story_id,
            claim_text=claim.get("text", ""),
            claim_type=claim.get("claim_type"),
            metadata={"run_id": run_id},
        )
        claim_map[claim.get("claim_id")] = cid
    for ev in payload.get("evidence", []):
        claim_ref = ev.get("claim_id")
        claim_uuid = claim_map.get(claim_ref) if claim_ref else None
        if not claim_uuid:
            continue
        save_evidence(
            claim_id=claim_uuid,
            evidence_type=ev.get("evidence_type", "secondary_reporting"),
            excerpt=ev.get("quote") or ev.get("excerpt"),
            url=ev.get("url"),
            metadata={"run_id": run_id},
        )
    return f"research/{run_id}"


def save_verification_result(run_id: str, payload: dict) -> str:
    for v in payload.get("verifications", []):
        cid = v.get("claim_id")
        if not cid:
            continue
        update_claim_status(
            claim_id=cid,
            status=v.get("status", "uncertain"),
            confidence=v.get("confidence"),
        )
    return f"verification/{run_id}"


def save_editorial_decision(run_id: str, payload: dict) -> str:
    story_id = payload.get("story_id")
    if not story_id:
        raise ValueError("save_editorial_decision requires story_id")
    client = get_client()
    if not is_production():
        rows = client.select(S.STORIES, id=story_id)
        if rows:
            rows[0].setdefault("metadata", {})["editorial"] = payload
            rows[0]["status"] = S.STORY_STATUS_EDITORIAL
            client._flush()
        return f"editorial/{run_id}"
    try:
        client.table(S.STORIES).update({
            "status": S.STORY_STATUS_EDITORIAL,
            "metadata": {"editorial": payload, "run_id": run_id},
        }).eq("id", story_id).execute()
        return f"editorial/{run_id}"
    except Exception as exc:
        raise_unavailable("save_editorial_decision", exc)
# ============================================================
# Compatibility aliases (older callers)
# ============================================================

def find_recent_stories(limit: int = 20, topic: str | None = None) -> list[dict]:
    """Alias for find_unpublished_candidates with relaxed defaults."""
    return find_unpublished_candidates(
        max_age_minutes=1440,
        min_source_count=0,
        limit=limit,
    )


# ============================================================
# Editorial Memory Functions (ammendments.md Sections 15-25)
# ============================================================

def get_recent_publications(
    platform: str = S.PLATFORM_THREADS,
    limit: int = 10,
    hours: int = 48,
) -> list[dict[str, Any]]:
    """Retrieve recent publications from Supabase with story metadata."""
    client = get_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    if not is_production():
        pubs = client.select(S.PUBLICATIONS, platform=platform)
        pubs = [p for p in pubs if p.get("status") in (S.PUBLICATION_STATUS_PUBLISHED, "PUBLISHED", "published")]
        pubs.sort(key=lambda p: p.get("published_at") or "", reverse=True)
        results = pubs[:limit]
    else:
        try:
            r = (
                client.table(S.PUBLICATIONS)
                .select("*")
                .eq("platform", platform)
                .in_("status", [S.PUBLICATION_STATUS_PUBLISHED, "PUBLISHED", "published"])
                .order("published_at", desc=True)
                .limit(limit)
                .execute()
            )
            results = r.data or []
        except DatabaseUnavailableError:
            raise
        except Exception as exc:
            raise_unavailable("get_recent_publications", exc)
            results = []

    # Enrich with story details
    enriched = []
    for pub in results:
        p = dict(pub)
        # Standardize status to lowercase
        if p.get("status") == "PUBLISHED":
            p["status"] = S.PUBLICATION_STATUS_PUBLISHED
        sid = p.get("story_id")
        if sid:
            story = get_story(sid)
            if story:
                p["title"] = story.get("title")
                p["categories"] = story.get("categories") or story.get("metadata", {}).get("categories") or []
        enriched.append(p)
    return enriched


def get_recent_stories(
    hours: int = 24,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Retrieve stories created/updated in the last N hours."""
    client = get_client()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    if not is_production():
        rows = client.select(S.STORIES)
    else:
        try:
            r = (
                client.table(S.STORIES)
                .select("*")
                .order("last_seen_at", desc=True)
                .limit(limit * 2)
                .execute()
            )
            rows = r.data or []
        except DatabaseUnavailableError:
            raise
        except Exception as exc:
            raise_unavailable("get_recent_stories", exc)
            return []

    out = []
    for s in rows:
        ls = s.get("last_seen_at") or s.get("first_seen_at") or ""
        try:
            ts = datetime.fromisoformat(str(ls).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue
        except Exception:
            pass
        out.append(s)
        if len(out) >= limit:
            break
    return out


def get_recent_category_distribution(
    hours: int = 24,
) -> dict[str, int]:
    """Calculate category counts for stories/publications in the last N hours."""
    pubs = get_recent_publications(limit=30, hours=hours)
    dist: dict[str, int] = {}
    for pub in pubs:
        cats = pub.get("categories") or []
        if isinstance(cats, str):
            cats = [cats]
        for c in cats:
            c_str = str(c).upper().strip()
            dist[c_str] = dist.get(c_str, 0) + 1
    return dist


def _compute_text_similarity(text1: str, text2: str) -> float:
    """Compute word overlap Jaccard similarity between two titles/texts."""
    if not text1 or not text2:
        return 0.0
    words1 = set(w.lower().strip(".,;:!?\"'()[]{}—–-") for w in text1.split() if len(w) > 2)
    words2 = set(w.lower().strip(".,;:!?\"'()[]{}—–-") for w in text2.split() if len(w) > 2)
    if not words1 or not words2:
        return 0.0
    intersection = words1 & words2
    union = words1 | words2
    return len(intersection) / len(union)


def find_similar_recent_stories(
    query_title: str,
    story_id: Optional[str] = None,
    hours: int = 48,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Find recent stories that are similar to the query title to detect repetition/material updates."""
    recent_pubs = get_recent_publications(limit=30, hours=hours)
    recent_stories = get_recent_stories(hours=hours, limit=30)

    candidates = []
    seen_ids = set()

    for p in recent_pubs:
        sid = p.get("story_id")
        if sid == story_id or sid in seen_ids:
            continue
        seen_ids.add(sid)
        title = p.get("title") or ""
        score = _compute_text_similarity(query_title, title)
        if score >= 0.10:
            rel = "RELATED"
            if score > 0.70:
                rel = "DUPLICATE"
            elif score >= 0.35:
                rel = "REPETITIVE"
            elif score >= 0.20:
                rel = "MATERIAL_UPDATE"
            candidates.append({
                "id": sid,
                "title": title,
                "categories": p.get("categories") or [],
                "relationship": rel,
                "score": score,
                "published_at": p.get("published_at"),
            })

    for s in recent_stories:
        sid = s.get("id")
        if sid == story_id or sid in seen_ids:
            continue
        seen_ids.add(sid)
        title = s.get("title") or ""
        score = _compute_text_similarity(query_title, title)
        if score >= 0.10:
            rel = "RELATED"
            if score > 0.70:
                rel = "DUPLICATE"
            elif score >= 0.35:
                rel = "REPETITIVE"
            elif score >= 0.20:
                rel = "MATERIAL_UPDATE"
            candidates.append({
                "id": sid,
                "title": title,
                "categories": s.get("categories") or s.get("metadata", {}).get("categories") or [],
                "relationship": rel,
                "score": score,
                "published_at": s.get("first_seen_at"),
            })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:limit]


def build_editorial_memory(
    story_id: Optional[str] = None,
    query_title: Optional[str] = None,
    hours: int = 48,
) -> dict[str, Any]:
    """Construct an EditorialMemory dictionary object from database state."""
    from schemas.editorial_memory import EditorialMemory, RecentPublication, RecentStory, SimilarStory

    pubs_raw = get_recent_publications(limit=10, hours=hours)
    pubs = [
        RecentPublication(
            id=p.get("id", ""),
            story_id=p.get("story_id", ""),
            platform=p.get("platform", "threads"),
            content=p.get("content", ""),
            published_at=p.get("published_at"),
            status=p.get("status", "published"),
            external_post_id=p.get("external_post_id"),
            title=p.get("title"),
            categories=p.get("categories") or [],
        )
        for p in pubs_raw
    ]

    stories_raw = get_recent_stories(hours=hours, limit=15)
    stories = [
        RecentStory(
            id=s.get("id", ""),
            title=s.get("title", ""),
            summary=s.get("summary"),
            categories=s.get("categories") or s.get("metadata", {}).get("categories") or [],
            first_seen_at=s.get("first_seen_at"),
            status=s.get("status"),
        )
        for s in stories_raw
    ]

    similar = []
    warnings = []
    if query_title:
        sim_raw = find_similar_recent_stories(query_title, story_id=story_id, hours=hours, limit=5)
        for sr in sim_raw:
            similar.append(
                SimilarStory(
                    id=sr["id"],
                    title=sr["title"],
                    categories=sr.get("categories") or [],
                    relationship=sr["relationship"],
                    score=sr["score"],
                    published_at=sr.get("published_at"),
                )
            )
            if sr["relationship"] in ("DUPLICATE", "REPETITIVE"):
                warnings.append(
                    f"Warning: Story is highly similar ({sr['relationship']}) to recently published/covered story: {sr['title']}"
                )

    cat_dist = get_recent_category_distribution(hours=24)

    memory_obj = EditorialMemory(
        recent_publications=pubs,
        recent_stories=stories,
        similar_stories=similar,
        category_distribution=cat_dist,
        repetition_warnings=warnings,
    )
    return memory_obj.model_dump(mode="json")
