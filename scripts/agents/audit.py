"""Real executable audit — every PASS must come from actual execution.

No more `contracts_work = True`. Each check function actually exercises
the code path it claims to verify and returns (bool, detail).
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402


# ── Individual checks ──────────────────────────────────────────

def check_contracts() -> tuple[bool, str]:
    try:
        from schemas.common import new_run_id
        from schemas.discovery import DiscoveryResult, CandidateStory
        from schemas.source_intelligence import SourceIntelligenceResult, SourceAssessment
        from schemas.research import ResearchResult, Claim, Evidence
        from schemas.selection import SelectionDecision, SelectionState
        from schemas.verification import VerificationResult, ClaimVerification, VerificationStatus
        from schemas.editorial import EditorialDecision
        from schemas.tone import ToneDecision, ToneType
        from schemas.writing import WriterDraft
        from schemas.platform import PlatformPost
        from schemas.validation import ValidationResult, ValidationState
        from schemas.publishing import PublishResult
        rid = new_run_id()
        sid = "s_test"
        models = [
            DiscoveryResult(run_id=rid, candidates=[CandidateStory(story_id=sid, title="T")]),
            SourceIntelligenceResult(run_id=rid, story_id=sid,
                assessments=[SourceAssessment(story_id=sid, source_id="s1")]),
            ResearchResult(run_id=rid, story_id=sid,
                claims=[Claim(text="c")], evidence=[Evidence(source_id="s1", quote="q")]),
            SelectionDecision(run_id=rid, story_id=sid, state=SelectionState.SELECT),
            VerificationResult(run_id=rid, story_id=sid,
                verifications=[ClaimVerification(claim_id="c1", status=VerificationStatus.SUPPORTED)]),
            EditorialDecision(run_id=rid, story_id=sid, central_event="e"),
            ToneDecision(run_id=rid, story_id=sid, tone=ToneType.INFORMATIVE),
            WriterDraft(run_id=rid, story_id=sid, headline="h", body="b"),
            PlatformPost(run_id=rid, story_id=sid, text="t"),
            ValidationResult(run_id=rid, story_id=sid, state=ValidationState.PASS),
            PublishResult(run_id=rid, story_id=sid),
        ]
        for m in models:
            rt = type(m).model_validate(m.model_dump())
            assert rt == m, f"roundtrip failed: {type(m).__name__}"
        return True, f"{len(models)} contracts roundtrip"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:150]}"


def check_providers() -> tuple[bool, str]:
    try:
        from core.llm.providers import (
            ProviderFactory, OllamaProvider, GroqProvider,
            OpenRouterProvider, GeminiProvider,
        )
        ProviderFactory.register(OllamaProvider(cloud=True))
        ProviderFactory.register(GroqProvider())
        ProviderFactory.register(OpenRouterProvider())
        ProviderFactory.register(GeminiProvider())
        names = []
        for n in ("ollama", "groq", "openrouter", "gemini"):
            p = ProviderFactory.get(n)
            assert p.config.base_url, f"{n} has no base_url"
            names.append(n)
        return True, f"{len(names)} providers constructed"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:150]}"


def check_registry() -> tuple[bool, str]:
    try:
        from core.llm.registry import build_default_registry
        reg = build_default_registry()
        entries = reg.all(enabled_only=False)
        assert len(entries) >= 5, "too few models registered"
        return True, f"{len(entries)} models registered"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:150]}"


def check_capabilities() -> tuple[bool, str]:
    try:
        from core.llm.persistence import load_capabilities
        from core.llm.registry import build_default_registry
        reg = build_default_registry()
        loaded = load_capabilities(reg)
        assert loaded >= 1, f"no verified capabilities loaded (got {loaded})"
        return True, f"{loaded} model capabilities loaded"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:150]}"


def check_routing() -> tuple[bool, str]:
    try:
        from core.llm.persistence import load_capabilities
        from core.llm.registry import build_default_registry
        from core.llm.routing.router import AgentTask, ModelRouter
        reg = build_default_registry()
        load_capabilities(reg)
        router = ModelRouter(reg)
        primary = router.route(AgentTask.RESEARCH)
        assert primary is not None, "no eligible model for RESEARCH"
        chain = router.fallback_chain(AgentTask.RESEARCH)
        return True, f"research={primary.provider}/{primary.model_id}, {len(chain)} in chain"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:150]}"


def check_fallback() -> tuple[bool, str]:
    try:
        from core.agents.runtime.middleware import with_model_fallback, FallbackTrace
        class M:
            def __init__(self, name, fail): self.model_name = name; self.fail = fail
        def invoke(m):
            if m.fail: raise RuntimeError("forced")
            return f"ok-{m.model_name}"
        result, trace = with_model_fallback([M("a", True), M("b", False)], invoke)
        assert result == "ok-b", "fallback did not select second model"
        return True, "primary failure → fallback succeeded"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:150]}"


def check_tools() -> tuple[bool, str]:
    try:
        from core.tools.search import search_web, real_tools_status
        status = real_tools_status()
        r = search_web.invoke({"query": "test"})
        assert isinstance(r, str), "search did not return str"
        return True, f"search status={status}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:150]}"


def check_prompts() -> tuple[bool, str]:
    try:
        from core.prompts.loader import compose_prompt
        p = compose_prompt(agent_role="test", input_state="test")
        assert "# GLOBAL POLICY" in p, "no global policy"
        assert "Accuracy > engagement" in p or "accuracy" in p.lower(), "no accuracy policy"
        return True, f"{len(p)} chars composed"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:150]}"


def check_middleware() -> tuple[bool, str]:
    try:
        from core.agents.runtime.middleware import ToolCallBudget, ModelCallBudget, TodoList
        tb = ToolCallBudget(limit=1)
        tb.consume("x")
        raised = False
        try:
            tb.consume("y")
        except RuntimeError:
            raised = True
        assert raised, "ToolCallBudget did not enforce limit"
        todo = TodoList()
        todo.add("task1")
        assert todo.pending() == ["task1"]
        return True, "budgets + todo exercised"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:150]}"


def check_team_graph_compiles() -> tuple[bool, str]:
    try:
        from core.team.graph import compile_graph
        g = compile_graph()
        assert g is not None
        return True, "graph compiled"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:150]}"


def check_quota() -> tuple[bool, str]:
    try:
        from core.team import quota
        allowed, reason, state = quota.can_publish()
        s = quota.status()
        assert "published" in s and "max_per_day" in s
        return True, f"published={s['published']}/{s['max_per_day']}, allowed={allowed}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:150]}"


def check_tone_bank() -> tuple[bool, str]:
    try:
        from core.team.tone_bank import TONES, example_for
        assert len(TONES) >= 5, f"only {len(TONES)} tones"
        ex = example_for("INFORMATIVE")
        assert ex, "empty tone example"
        return True, f"{len(TONES)} tones with examples"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:150]}"


# ── Runner ─────────────────────────────────────────────────────

CHECKS = [
    ("contracts work", check_contracts),
    ("provider layer works", check_providers),
    ("model registry works", check_registry),
    ("capabilities are testable", check_capabilities),
    ("routing works", check_routing),
    ("fallback works", check_fallback),
    ("semantic tools work", check_tools),
    ("prompts load correctly", check_prompts),
    ("middleware works", check_middleware),
    ("team graph compiles", check_team_graph_compiles),
    ("quota gate works", check_quota),
    ("tone bank works", check_tone_bank),
]


def main() -> None:
    print("=" * 74)
    print("  NewsRoom Audit — every PASS is an executed check")
    print("  " + datetime.now(timezone.utc).isoformat())
    print("=" * 74)
    results = []
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"unexpected: {type(exc).__name__}: {exc}"
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name:32} — {detail}")
        results.append(ok)
    print()
    print(f"  {sum(results)}/{len(results)} checks passed")
    print()
    if all(results):
        print("PHASE 2.1 COMPLETE")
    else:
        print("PHASE 2.1 INCOMPLETE")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()