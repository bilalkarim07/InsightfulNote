"""Minimal test runner for plain-Python test scripts.

Each test module defines functions whose names start with ``test_``.
This runner discovers and executes them and reports pass/fail.
"""

from __future__ import annotations

import traceback
from typing import Callable


def run_module(namespace: dict, *, title: str = "tests") -> int:
    """Run all test_* callables in ``namespace``. Return 0 on success."""
    tests: list[tuple[str, Callable]] = [
        (name, fn)
        for name, fn in namespace.items()
        if name.startswith("test_") and callable(fn)
    ]
    tests.sort(key=lambda kv: kv[1].__code__.co_firstlineno)

    print(f"\n=== {title} — {len(tests)} test(s) ===")
    failed: list[tuple[str, BaseException]] = []
    for name, fn in tests:
        try:
            fn()
            print(f"  [PASS] {name}")
        except AssertionError as exc:
            print(f"  [FAIL] {name}: assertion failed: {exc}")
            failed.append((name, exc))
        except Exception as exc:
            print(f"  [FAIL] {name}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            failed.append((name, exc))

    print(f"--- {len(tests) - len(failed)} passed, {len(failed)} failed ---")
    return 1 if failed else 0