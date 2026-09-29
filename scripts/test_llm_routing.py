"""Executable test for LLM capability routing, structured outputs, and fallbacks.

Per ammendments.md Section 75 & 76.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403
from core.llm.registry import build_default_registry
from core.llm.persistence import load_capabilities
from core.llm.routing.router import ModelRouter, AgentTask
from schemas.editorial import EditorialDecision
from schemas.tone import ToneDecision, ToneType
from schemas.writing import WriterDraft


def test_llm_routing_and_contracts() -> None:
    print("=" * 60)
    print("Testing LLM Routing & Pydantic Contract Validations")
    print("=" * 60)

    # 1. Registry & Router check
    registry = build_default_registry()
    loaded = load_capabilities(registry)
    assert loaded >= 6, f"expected at least 6 manifest models, loaded {loaded}"

    print(f"[OK] Model registry loaded ({len(registry.all())} model configurations available).")

    router = ModelRouter(registry)
    research_models = {
        f"{entry.provider}/{entry.model_id}"
        for entry in router.eligible_models(
            router.get_task_requirements(AgentTask.RESEARCH)
        )
    }
    assert "ollama/gpt-oss:120b" in research_models
    assert "groq/openai/gpt-oss-120b" in research_models
    print("[OK] Verified research routes include Ollama 120B and Groq 120B.")

    selected_entry = router.route(AgentTask.EDITORIAL)
    fallback_entries = router.fallback_chain(AgentTask.EDITORIAL)

    if selected_entry:
        print(f"[OK] Capability router selected primary model: {selected_entry.provider}/{selected_entry.model_id}")
        print(f"  Fallback models ({len(fallback_entries)}): {[f'{e.provider}/{e.model_id}' for e in fallback_entries]}")
    else:
        print("  Notice: No active verified model found in registry for capability match.")

    # 2. Test agent Pydantic contracts
    editorial = EditorialDecision(
        run_id="run_test",
        story_id="story_test",
        central_event="Test central event statement.",
        must_include=["fact 1"],
        do_not_include=["speculation"],
        framing="Informative framing",
        allowed_claim_ids=["claim_1"],
    )
    assert editorial.central_event == "Test central event statement."
    print("[OK] EditorialDecision contract validated.")

    tone = ToneDecision(
        run_id="run_test",
        story_id="story_test",
        tone=ToneType.INFORMATIVE,
        rationale="Serious news event",
    )
    assert tone.tone == ToneType.INFORMATIVE
    print("[OK] ToneDecision contract validated.")

    draft = WriterDraft(
        run_id="run_test",
        story_id="story_test",
        headline="Short Test Headline",
        body="This is the test body of the post.",
        claim_ids=["claim_1"],
        tone=ToneType.INFORMATIVE,
    )
    assert len(draft.body) > 0
    print("[OK] WriterDraft contract validated.")

    print("\nALL LLM ROUTING & CONTRACT TESTS PASSED!")


if __name__ == "__main__":
    test_llm_routing_and_contracts()
