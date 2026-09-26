"""Append-only run log for observability (spec §75).

Every stage execution writes one JSONL row. This gives us the audit trail:
  run_id, agent, provider, model, latency_ms, status, error, metadata

Local JSONL file at data/pipeline_log.jsonl.
Swap for Supabase later by replacing the _write() function.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

LOG_PATH = Path("data/pipeline_log.jsonl")


def _ensure_dir() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _write(row: dict[str, Any]) -> None:
    """Append a log row. Never raises — a broken log must not crash a run."""
    try:
        _ensure_dir()
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except Exception:  # noqa: BLE001
        pass


@contextmanager
def stage(
    *,
    run_id: str,
    agent: str,
    provider: str = "",
    model_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Context manager that records a stage execution.

    Usage:
        with stage(run_id=run_id, agent="research") as s:
            s["metadata"]["evidence_chars"] = 1200
            ... do work ...
            s["status"] = "PASS"
    """
    row: dict[str, Any] = {
        "run_id": run_id,
        "agent": agent,
        "provider": provider,
        "model_id": model_id,
        "status": "RUNNING",
        "error": None,
        "metadata": metadata or {},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    t0 = time.monotonic()
    try:
        yield row
        if row["status"] == "RUNNING":
            row["status"] = "PASS"
    except Exception as exc:  # noqa: BLE001
        row["status"] = "FAILED"
        row["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        row["latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
        row["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write(row)


def read_log(limit: int | None = None) -> list[dict[str, Any]]:
    if not LOG_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if limit is not None:
        rows = rows[-limit:]
    return rows


def summarize() -> dict[str, Any]:
    rows = read_log()
    by_agent: dict[str, dict[str, int]] = {}
    for r in rows:
        agent = r.get("agent", "unknown")
        status = r.get("status", "unknown")
        by_agent.setdefault(agent, {}).setdefault(status, 0)
        by_agent[agent][status] += 1
    return {
        "total_rows": len(rows),
        "by_agent": by_agent,
    }
