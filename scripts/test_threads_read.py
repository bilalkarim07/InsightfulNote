"""Step 11: Threads read/auth smoke tests.

Tests:
  1. Authentication (via get_token_status)
  2. Read own posts (get_my_posts with limit=1)
  3. Search (query="news" with small limit)

Does NOT create, delete, or modify anything.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402


def section(title: str) -> None:
    print()
    print("=" * 74)
    print("  " + title)
    print("=" * 74)


def preview(obj, n: int = 300) -> str:
    import json
    try:
        s = json.dumps(obj, default=str)
    except Exception:
        s = repr(obj)
    return s[:n] + ("..." if len(s) > n else "")


def main() -> int:
    print("=" * 74)
    print("  Threads Smoke Tests (read-only)")
    print("=" * 74)

    results: list[tuple[str, bool, str]] = []
    def record(name, ok, detail=""):
        results.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:36} {detail}")

    # ── Build API ──
    try:
        from tools.threads._api_factory import build_threads_api
        api = build_threads_api()
        record("build_threads_api", True, type(api).__name__)
    except Exception as exc:
        record("build_threads_api", False, f"{type(exc).__name__}: {exc}")
        return 1

    # ── Test 1: auth ──
    section("Test 1 — authentication")
    try:
        status = api.get_token_status()
        authed = getattr(status, "authenticated", False)
        record("token authenticated", authed, f"user_id={getattr(status, 'user_id', None)}")
        if not authed:
            print()
            print("  Cannot continue — token not authenticated.")
            return 1
    except Exception as exc:
        record("token authenticated", False, f"{type(exc).__name__}: {exc}")
        return 1

    # ── Test 2: read own posts ──
    section("Test 2 — read own posts")
    try:
        result = api.get_my_posts(limit=1, max_pages=1)
        data = result.get("data") if isinstance(result, dict) else None
        count = len(data) if isinstance(data, list) else "?"
        record("get_my_posts", True, f"returned {count} post(s)")
        if isinstance(data, list) and data:
            first = data[0]
            pid = first.get("id") if isinstance(first, dict) else None
            snippet = (first.get("text") or "")[:60] if isinstance(first, dict) else ""
            print(f"    first post id: {pid}")
            print(f"    preview: {snippet}")
    except Exception as exc:
        record("get_my_posts", False, f"{type(exc).__name__}: {exc}")

    # ── Test 3: search ──
    section("Test 3 — search")
    try:
        result = api.search(query="news", limit=1, max_pages=1)
        data = result.get("data") if isinstance(result, dict) else None
        count = len(data) if isinstance(data, list) else "?"
        record("search('news')", True, f"returned {count} result(s)")
    except Exception as exc:
        record("search", False, f"{type(exc).__name__}: {exc}")

    # ── Summary ──
    section("Summary")
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"  {passed}/{total} tests passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
