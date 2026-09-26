"""Supabase client singleton with LocalStore fallback."""
from __future__ import annotations
import json
import os
import threading
from pathlib import Path
from typing import Any, Optional


class DatabaseUnavailableError(RuntimeError):
    """Raised when Supabase is configured but unreachable, or a query fails."""


_LOCK = threading.Lock()
_CLIENT: Optional[Any] = None
_MODE: str = "uninitialized"
_STORE: Optional[Any] = None


def _local_store_path() -> Path:
    root = Path(__file__).resolve().parents[3]
    p = root / "data" / "local_store.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class LocalStore:
    """Development fallback so semantic tools work without Supabase."""
    def __init__(self) -> None:
        self._path = _local_store_path()
        self._data: dict[str, list[dict]] = {}
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}

    def _flush(self) -> None:
        self._path.write_text(
            json.dumps(self._data, indent=2, default=str),
            encoding="utf-8",
        )

    def select(self, table: str, **filters: Any) -> list[dict]:
        rows = self._data.get(table, [])
        if not filters:
            return list(rows)
        return [
            r for r in rows
            if all(r.get(k) == v for k, v in filters.items())
        ]

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

    def delete(self, table: str, **filters: Any) -> int:
        rows = self._data.get(table, [])
        before = len(rows)
        if not filters:
            self._data[table] = []
        else:
            self._data[table] = [
                r for r in rows
                if not all(r.get(k) == v for k, v in filters.items())
            ]
        removed = before - len(self._data[table])
        self._flush()
        return removed


def _resolve_supabase_key() -> str:
    for name in ("SUPABASE_KEY", "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_KEY"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    return ""


def get_client() -> Any:
    global _CLIENT, _MODE, _STORE
    with _LOCK:
        if _MODE == "supabase":
            return _CLIENT
        if _MODE == "local":
            return _STORE

        url = os.environ.get("SUPABASE_URL", "").strip()
        key = _resolve_supabase_key()

        if url and key:
            try:
                from supabase import create_client  # type: ignore
                _CLIENT = create_client(url, key)
                _MODE = "supabase"
                return _CLIENT
            except Exception as exc:
                print(f"  [db] supabase init failed: {exc} - using local store")

        _STORE = LocalStore()
        _MODE = "local"
        return _STORE


def mode() -> str:
    get_client()
    return _MODE


def is_production() -> bool:
    return mode() == "supabase"


def raise_unavailable(op: str, exc: Exception) -> None:
    raise DatabaseUnavailableError(
        f"Database operation {op!r} failed: {type(exc).__name__}: {exc}"
    ) from exc
