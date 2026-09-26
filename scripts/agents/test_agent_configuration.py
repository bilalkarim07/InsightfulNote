"""Agent configuration tests."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.agents.base.config import DEFAULT_AGENT_CONFIGS  # noqa: E402


def main() -> None:
    failures: list[str] = []
    print("Agent configuration tests")
    print("=" * 70)

    expected = {
        "discovery", "source_intelligence", "research", "selection",
        "verification", "editorial", "tone", "writer",
        "platform_adapter", "validation", "publisher",
    }
    missing = expected - set(DEFAULT_AGENT_CONFIGS.keys())
    if missing:
        failures.append(f"missing configs: {missing}")
        print(f"  [FAIL] missing configs: {missing}")
    else:
        print("  [PASS] all 11 agent configs present")

    writer = DEFAULT_AGENT_CONFIGS["writer"]
    if writer.tools:
        failures.append("writer must have no tools")
        print("  [FAIL] writer has tools")
    else:
        print("  [PASS] writer has no tools")

    publisher = DEFAULT_AGENT_CONFIGS["publisher"]
    if not publisher.is_deterministic:
        failures.append("publisher must be deterministic")
        print("  [FAIL] publisher is not deterministic")
    else:
        print("  [PASS] publisher is deterministic")

    research = DEFAULT_AGENT_CONFIGS["research"]
    for cap in ("tool_calling", "structured_output", "tool_plus_structure"):
        if cap not in research.required_capabilities:
            failures.append(f"research missing capability {cap}")
            print(f"  [FAIL] research missing {cap}")
    print("  [PASS] research requires tools + structured output")

    print()
    if failures:
        print(f"FAILED: {len(failures)} checks")
        sys.exit(1)
    print("ALL CONFIG TESTS PASS")


if __name__ == "__main__":
    main()
