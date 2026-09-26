"""Supabase client singleton with a local JSONL fallback for dev.

Production path: SUPABASE_URL + SUPABASE_KEY set → real Supabase.
Fallback path:   env absent → in-memory store backed by data/local_store.json.

Agents NEVER receive the raw client. They only see the semantic tools
in core.tools.database.stories.
"""
from __future__ import annotations
import json
import os
import threading
from pathlib import Path
from typing import Any, Optional

_LOCK = threading.Lock()
_CLIENT: Optional[Any] = None
_MODE: str = "uninitialized"


def _local_store_path() -> Path:
    root = Path(__file__).resolve().parents[3]
    p = root / "data" / "local_store.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class LocalStore:
    """Minimal in-memory replacement for Supabase during development.

    Persists to data/local_store.json so state survives process restarts.
    """
    def __init__(self) -> None:
        self._path = _local_store_path()
        self._data: dict[str, list[dict]] = {}
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}

    def _flush(self) -> None:
        self._path.write_text(json.dumps(self._data, indent=2, default=str), encoding="utf-8")

    def insert(self, table: str, row: dict) -> dict:
        self._data.setdefault(table, []).append(row)
        self._flush()
        return row

    def upsert(self, table: str, row: dict, key: str) -> dict:
        rows = self._data.setdefault(table, [])
        for i, r in enumerate(rows):
            if r.get(key) == row.get(key):
                rows[i] = {**r, **row}
                self._flush()
                return rows[i]
        rows.append(row)
        self._flush()
        return row

    def select(self, table: str, **filters: Any) -> list[dict]:
        rows = self._data.get(table, [])
        if not filters:
            return list(rows)
        out = []
        for r in rows:
            if all(r.get(k) == v for k, v in filters.items()):
                out.append(r)
        return out


_STORE: Optional[LocalStore] = None


def get_client() -> Any:
    """Return the Supabase client, or the LocalStore if creds are absent."""
    global _CLIENT, _MODE, _STORE
    with _LOCK:
        if _MODE == "supabase":
            return _CLIENT
        if _MODE == "local":
            return _STORE
        url = os.environ.get("SUPABASE_URL", "").strip()
        key = os.environ.get("SUPABASE_KEY", "").strip()
        if url and key:
            try:
                from supabase import create_client  # type: ignore
                _CLIENT = create_client(url, key)
                _MODE = "supabase"
                return _CLIENT
            except Exception as exc:
                print(f"  [db] supabase client init failed: {exc} — using local store")
        _STORE = LocalStore()
        _MODE = "local"
        return _STORE


def mode() -> str:
    get_client()
    return _MODE


def is_production() -> bool:
    return mode() == "supabase"