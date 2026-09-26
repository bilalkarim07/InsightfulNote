"""Failure tests — verify middleware handles error conditions.

Cases:
  1. ToolCallLimit — budget exhaustion
  2. ModelCallLimit — budget exhaustion
  3. ToolRetry — transient failure recovers
  4. ModelFallback — first model fails, second succeeds
  5. Fallback — all models fail (raises with clear reason)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.agents.runtime.middleware import (  # noqa: E402
    ToolCallBudget,
    ModelCallBudget,
    FallbackTrace,
    TodoList,
    with_tool_retry,
    with_model_fallback,
)


def expect_raises(fn, exc_type) -> bool:
    try:
        fn()
        return False
    except exc_type:
        return True
    except Exception:
        return False


def main() -> None:
    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        mark = "PASS" if cond else "FAIL"
        if not cond:
            failures.append(name)
        print(f"  [{mark}] {name}")

    print("Failure / middleware tests")
    print("=" * 70)

    # 1. ToolCallLimit
    budget = ToolCallBudget(limit=2)
    budget.consume("a")
    budget.consume("b")
    check(
        "ToolCallLimit raises on 3rd call",
        expect_raises(lambda: budget.consume("c"), RuntimeError),
    )

    # 2. ModelCallLimit
    mbudget = ModelCallBudget(limit=1)
    mbudget.consume()
    check(
        "ModelCallLimit raises on 2nd call",
        expect_raises(mbudget.consume, RuntimeError),
    )

    # 3. ToolRetry — transient failure recovers
    state = {"calls": 0}

    def flaky():
        state["calls"] += 1
        if state["calls"] < 3:
            raise ConnectionError("transient")
        return "ok"

    wrapped = with_tool_retry(flaky, max_retries=3, backoff_seconds=0.01)
    check("ToolRetry recovers after transient failure", wrapped() == "ok")

    # 4. ModelFallback — first fails, second succeeds
    class M:
        def __init__(self, name: str, fail: bool):
            self.model_name = name
            self.fail = fail

    m1, m2 = M("model-a", fail=True), M("model-b", fail=False)

    def invoke(m: M):
        if m.fail:
            raise RuntimeError("boom")
        return f"result-from-{m.model_name}"

    result, trace = with_model_fallback([m1, m2], invoke)
    check("ModelFallback returns second model result", result == "result-from-model-b")
    check("ModelFallback records failure", trace.attempts[0]["success"] is False)
    check("ModelFallback records success", trace.attempts[1]["success"] is True)

    # 5. All models fail
    m3 = M("model-c", fail=True)

    def invoke_all_fail(m: M):
        raise RuntimeError("all fail")

    check(
        "ModelFallback raises when all models fail",
        expect_raises(lambda: with_model_fallback([m1, m3], invoke_all_fail), RuntimeError),
    )

    # 6. Todo
    todo = TodoList()
    todo.add("step 1")
    todo.add("step 2")
    todo.complete(0)
    check("Todo tracks pending", todo.pending() == ["step 2"])

    print()
    if failures:
        print(f"FAILED: {len(failures)} checks")
        sys.exit(1)
    print("ALL FAILURE TESTS PASS")


if __name__ == "__main__":
    main()
