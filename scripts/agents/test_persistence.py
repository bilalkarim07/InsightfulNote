"""Roundtrip test for capability persistence."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.llm.capabilities.models import CapabilityStatus  # noqa: E402
from core.llm.registry import build_default_registry  # noqa: E402
from core.llm.persistence import (  # noqa: E402
    save_capabilities, load_capabilities, mark_verified,
)


def main() -> None:
    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        mark = "PASS" if cond else "FAIL"
        if not cond:
            failures.append(name)
        print(f"  [{mark}] {name}")

    print("Capability persistence test")
    print("=" * 70)

    reg = build_default_registry()
    mark_verified(
        reg, "ollama", "gpt-oss:120b",
        basic_invocation=True,
        pydantic_output=True,
        tool_calling=True,
        tool_plus_structure=True,
        newsroom_contracts=True,
        reliability_score=0.95,
    )
    path = save_capabilities(reg)
    check("save wrote file", path.exists())

    # Load into a fresh registry and verify roundtrip
    reg2 = build_default_registry()
    loaded = load_capabilities(reg2)
    check("load reported >=1", loaded >= 1)

    entry = reg2.get("ollama", "gpt-oss:120b")
    cap = entry.capabilities if entry else None
    check("capabilities loaded", cap is not None)
    if cap:
        check(
            "tool_calling PASS preserved",
            cap.verified_tool_calling == CapabilityStatus.PASS,
        )
        check(
            "reliability preserved",
            cap.reliability_score == 0.95,
        )

    print()
    if failures:
        print(f"FAILED: {len(failures)} checks")
        sys.exit(1)
    print("ALL PERSISTENCE TESTS PASS")


if __name__ == "__main__":
    main()
