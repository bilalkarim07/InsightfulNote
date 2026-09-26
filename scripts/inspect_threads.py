"""Inspect the Threads factory/API mismatch."""
from __future__ import annotations
import inspect
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


def main() -> None:
    # ── 1. What does the factory look like? ──
    section("tools/threads/_api_factory.py")
    try:
        from tools.threads import _api_factory
        print("File:", _api_factory.__file__)
        print()
        print(inspect.getsource(_api_factory))
    except Exception as exc:
        print(f"Import failed: {type(exc).__name__}: {exc}")

    # ── 2. What is the ThreadsAPI constructor signature? ──
    section("sources.threads.ThreadsAPI signature")
    try:
        from sources.threads import ThreadsAPI
        print("File:", inspect.getfile(ThreadsAPI))
        print()
        print("__init__ signature:")
        print("  " + str(inspect.signature(ThreadsAPI.__init__)))
        print()
        print("Public methods:")
        for name, fn in inspect.getmembers(ThreadsAPI, inspect.isfunction):
            if name.startswith("_"):
                continue
            try:
                print(f"  {name}{inspect.signature(fn)}")
            except (ValueError, TypeError):
                print(f"  {name}(...)")
    except Exception as exc:
        print(f"Import failed: {type(exc).__name__}: {exc}")

    # ── 3. What does tools.threads expose? ──
    section("tools.threads public API")
    try:
        import tools.threads as t
        for name in dir(t):
            if name.startswith("_"):
                continue
            obj = getattr(t, name)
            if inspect.ismodule(obj):
                continue
            kind = type(obj).__name__
            print(f"  {name:32} {kind}")
    except Exception as exc:
        print(f"Import failed: {type(exc).__name__}: {exc}")

    # ── 4. What does sources.threads expose? ──
    section("sources.threads public API")
    try:
        import sources.threads as s
        for name in dir(s):
            if name.startswith("_"):
                continue
            obj = getattr(s, name)
            if inspect.ismodule(obj):
                continue
            kind = type(obj).__name__
            print(f"  {name:32} {kind}")
    except Exception as exc:
        print(f"Import failed: {type(exc).__name__}: {exc}")

    # ── 5. Our publisher facade ──
    section("core/tools/publishing.py")
    try:
        from core.tools import publishing
        print("File:", publishing.__file__)
        print()
        print(inspect.getsource(publishing))
    except Exception as exc:
        print(f"Import failed: {type(exc).__name__}: {exc}")

    print()


if __name__ == "__main__":
    main()
