"""Research vertical slice — uses the structured-output cascade."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from langchain_core.tools import tool  # noqa: E402

from schemas.common import new_run_id  # noqa: E402
from schemas.research import ResearchResult  # noqa: E402
from core.llm.factory import get_chat_model, structured_method_for  # noqa: E402
from core.llm.persistence import load_capabilities  # noqa: E402
from core.llm.providers import (  # noqa: E402
    OllamaProvider, GroqProvider, OpenRouterProvider, GeminiProvider, ProviderFactory,
)
from core.llm.registry import build_default_registry  # noqa: E402
from core.agents.runtime.middleware import (  # noqa: E402
    ToolCallBudget, with_tool_retry, TodoList,
)
from scripts.llm._structured import invoke_structured, StructuredOutputError  # noqa: E402

ProviderFactory.register(OllamaProvider(cloud=True))
ProviderFactory.register(GroqProvider())
ProviderFactory.register(OpenRouterProvider())
ProviderFactory.register(GeminiProvider())


@tool
def search_web(query: str) -> str:
    """Search the web for a given query. Returns matching snippets."""
    fixture = {
        "Company X product Y": (
            "Official press release (companyx.com, 2026-01-01): "
            "Company X today announced product Y, available Q2 2026."
        ),
        "Company X analyst reaction": (
            "Analyst at Firm Z: 'We expect product Y to lift revenue by 5% in FY27.' "
            "(attributed forecast, not confirmed)"
        ),
    }
    for key, value in fixture.items():
        if key.lower() in query.lower():
            return value
    return "No results."


def _long_prompt(run_id: str, story_id: str, evidence_block: str) -> str:
    return f"""
You are the Research Agent. Given the following evidence, produce a
ResearchResult matching this JSON shape:

{{
  "run_id": "{run_id}",
  "story_id": "{story_id}",
  "claims": [
    {{
      "claim_id": "claim_1",
      "text": "<factual statement>",
      "evidence_ids": ["ev_1"],
      "attribution": "",
      "uncertainty": "",
      "is_forecast": false,
      "is_allegation": false,
      "is_opinion": false
    }}
  ],
  "evidence": [
    {{
      "evidence_id": "ev_1",
      "source_id": "s1",
      "quote": "<verbatim from evidence>",
      "url": null,
      "retrieved_at": null,
      "context": ""
    }}
  ],
  "missing_information": [],
  "conflicting_claims": [],
  "notes": ""
}}

Evidence:
{evidence_block}

Rules:
- claims and evidence are SIBLING arrays
- Claim.evidence_ids is a list of evidence_id STRINGS
- Do NOT nest evidence inside claims
- Return the object directly
""".strip()


def _terse_prompt(run_id: str, story_id: str, evidence_block: str) -> str:
    """Short, single-claim prompt used as retry when the long one fails."""
    return (
        f'Produce a ResearchResult JSON for run_id="{run_id}", '
        f'story_id="{story_id}". '
        'Use exactly one claim and one evidence. '
        'The claim has claim_id="claim_1", text="Company X announced product Y", '
        'evidence_ids=["ev_1"]. '
        'The evidence has evidence_id="ev_1", source_id="s1", '
        'quote="Company X announced product Y". '
        f'Evidence: {evidence_block}'
    )


def run_slice(provider: str, model_id: str) -> int:
    registry = build_default_registry()
    loaded = load_capabilities(registry)

    entry = registry.get(provider, model_id)
    if entry is None:
        print(f"[FAIL] Unknown model: {provider}/{model_id}")
        return 1

    cap = entry.capabilities
    tool_status = cap.verified_tool_calling.value if cap else "UNVERIFIED"
    struct_status = cap.verified_pydantic_output.value if cap else "UNVERIFIED"

    print("=" * 70)
    print(f"Research vertical slice — {provider}/{model_id}")
    print(f"  loaded persisted capabilities for {loaded} model(s)")
    print(f"  tool_calling verified:      {tool_status}")
    print(f"  structured_output verified: {struct_status}")
    print("=" * 70)

    if tool_status != "PASS":
        print(f"[SKIP] {provider}/{model_id} has not passed tool_calling benchmark.")
        print(f"       Run: python scripts\\llm\\test_tool_calling.py {provider} {model_id}")
        return 2
    if struct_status != "PASS":
        print(f"[SKIP] {provider}/{model_id} has not passed structured_output benchmark.")
        print(f"       Run: python scripts\\llm\\test_structured_output.py {provider} {model_id}")
        return 2

    run_id = new_run_id()
    story_id = "story_vertical_slice"

    todo = TodoList()
    todo.add("Search for the primary announcement")
    todo.add("Search for analyst reaction (attributed)")
    todo.add("Produce ResearchResult contract")
    print("\n[plan]")
    print(todo.render())

    tool_budget = ToolCallBudget(limit=4)
    safe_search = with_tool_retry(search_web.invoke, max_retries=1, backoff_seconds=0.1)

    model = get_chat_model(entry, timeout=180)
    method_hint = structured_method_for(entry)
    print(f"\n[model] preferred structured method = {method_hint}")

    queries = ["Company X product Y", "Company X analyst reaction"]
    for q in queries:
        tool_budget.consume("search_web")
    todo.complete(0)
    todo.complete(1)

    results = [safe_search(q) for q in queries]
    print("\n[evidence collected]")
    for q, r in zip(queries, results):
        print(f"  Q: {q}")
        print(f"  A: {r[:100]}...")

    evidence_block = "\n".join(
        f"- source_id='s{i+1}', quote={r!r}" for i, r in enumerate(results)
    )

    # ── Attempt 1: long prompt via cascade ──
    parsed = None
    used_method = None
    try:
        parsed, used_method = invoke_structured(
            model, ResearchResult,
            _long_prompt(run_id, story_id, evidence_block),
            supports_json_schema=(provider != "ollama"),
        )
    except StructuredOutputError as exc:
        print("\n[attempt 1 failed]")
        print(str(exc))
        print("\n[retrying with terse prompt]")

    # ── Attempt 2: terse prompt via cascade ──
    if parsed is None:
        try:
            parsed, used_method = invoke_structured(
                model, ResearchResult,
                _terse_prompt(run_id, story_id, evidence_block),
                supports_json_schema=(provider != "ollama"),
            )
        except StructuredOutputError as exc:
            print("\n[attempt 2 failed]")
            print(str(exc))
            print("\nVERTICAL SLICE FAIL")
            return 3

    if not isinstance(parsed, ResearchResult):
        print(f"[FAIL] structured output produced {type(parsed).__name__}, not ResearchResult")
        return 3

    print(f"\n[structured output ok] method={used_method}")
    todo.complete(2)

    # ── Deterministic validation ──
    assert parsed.run_id == run_id, f"run_id mismatch: {parsed.run_id}"
    assert parsed.story_id == story_id
    assert len(parsed.claims) >= 1, "at least one claim required"
    assert len(parsed.evidence) >= 1, "at least one evidence required"

    evidence_ids = {e.evidence_id for e in parsed.evidence}
    for c in parsed.claims:
        for eid in c.evidence_ids:
            assert eid in evidence_ids, f"claim {c.claim_id} references unknown evidence {eid}"

    snapshot_dir = Path("data/slices")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot_dir / f"{run_id}.json"
    snapshot.write_text(
        json.dumps(parsed.model_dump(mode="json"), indent=2, default=str),
        encoding="utf-8",
    )

    print("\n[result]")
    print(f"  claims:   {len(parsed.claims)}")
    print(f"  evidence: {len(parsed.evidence)}")
    for c in parsed.claims:
        print(f"    • {c.text}  [forecast={c.is_forecast}]")
    print(f"  snapshot: {snapshot}")
    print(f"  tool_budget used: {tool_budget.used}/{tool_budget.limit}")
    print("\n[plan final]")
    print(todo.render())
    print("\nVERTICAL SLICE PASS")
    return 0


def main() -> None:
    if len(sys.argv) >= 3:
        provider, model_id = sys.argv[1], sys.argv[2]
    else:
        provider, model_id = "ollama", "gpt-oss:120b"
    sys.exit(run_slice(provider, model_id))


if __name__ == "__main__":
    main()
