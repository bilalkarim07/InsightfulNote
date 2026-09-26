"""Router tests — verify task requirements, eligibility, fallback chain."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.llm.capabilities.models import CapabilityStatus  # noqa: E402
from core.llm.registry import build_default_registry  # noqa: E402
from core.llm.routing.router import AgentTask, ModelRouter  # noqa: E402


def main() -> None:
    registry = build_default_registry()
    router = ModelRouter(registry)

    print("Router tests")
    print("=" * 70)

    # Initially no model has verified capabilities, so research has no eligible model.
    research = router.route(AgentTask.RESEARCH)
    if research is not None:
        print(f"  [FAIL] research should have no eligible model yet, got {research.model_id}")
        sys.exit(1)
    print("  [PASS] research has no eligible model before benchmarks")

    # Manually mark one model as fully verified.
    entry = registry.get("ollama", "gpt-oss:120b")
    assert entry is not None
    caps = entry.capabilities
    caps.verified_basic_invocation = CapabilityStatus.PASS
    caps.verified_pydantic_output = CapabilityStatus.PASS
    caps.verified_tool_calling = CapabilityStatus.PASS
    caps.verified_tool_plus_structure = CapabilityStatus.PASS
    caps.reliability_score = 0.95

    research = router.route(AgentTask.RESEARCH)
    if research is None or research.model_id != "gpt-oss:120b":
        print(f"  [FAIL] research should now route to gpt-oss:120b, got {research}")
        sys.exit(1)
    print(f"  [PASS] research routes to {research.provider}/{research.model_id}")

    # Writer only needs structured output — the same model is fine, but a
    # structured-only model could also be eligible. Verify the writer chain
    # is capability-appropriate.
    writer_chain = router.fallback_chain(AgentTask.WRITER)
    if not writer_chain:
        print("  [FAIL] writer chain is empty")
        sys.exit(1)
    print(f"  [PASS] writer chain has {len(writer_chain)} eligible model(s)")

    print()
    print("ALL ROUTER TESTS PASS")


if __name__ == "__main__":
    main()
