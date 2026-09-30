"""Manual regression check for one evidence-bound empty-claims retry."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.team import graph  # noqa: E402
from schemas.research import Claim  # noqa: E402
from schemas.research_claims import ResearchClaims  # noqa: E402


class FakeSearch:
    def invoke(self, _payload: dict) -> dict:
        return {"items": []}


def _run_research(responses: list[ResearchClaims]) -> tuple[dict, list[str]]:
    original_model = graph._model
    original_search = graph.search_web
    original_compact = graph.compact_search_results
    original_structured = graph._structured
    prompts: list[str] = []

    def structured(_client, _schema, prompt: str, _provider: str):
        prompts.append(prompt)
        return responses.pop(0), "manual-test"

    graph._model = lambda _state: object()
    graph.search_web = FakeSearch()
    graph.compact_search_results = lambda *_args, **_kwargs: [{
        "evidence_id": "ev_test",
        "source_id": "src_test",
        "title": "A verified news report",
        "url": "https://example.com/report",
        "quote": "A verified news report",
    }]
    graph._structured = structured
    try:
        result = graph.node_research({
            "run_id": "run_test",
            "story_id": "story_test",
            "topic": "A verified news report",
            "seed": {"title": "A verified news report"},
            "provider": "ollama",
            "model_id": "manual-test",
            "iteration": {},
            "research_questions": [],
            "outcome": "RUNNING",
        })
        return result, prompts
    finally:
        graph._model = original_model
        graph.search_web = original_search
        graph.compact_search_results = original_compact
        graph._structured = original_structured


def main() -> int:
    supported_claim = Claim(
        claim_id="claim_test",
        text="A verified news report was published.",
        evidence_ids=["ev_test"],
    )
    recovered, prompts = _run_research([
        ResearchClaims(claims=[]),
        ResearchClaims(claims=[supported_claim]),
    ])
    assert len(prompts) == 2
    assert "Recovery attempt" in prompts[1]
    assert len(recovered["research"]["claims"]) == 1

    still_empty, prompts = _run_research([
        ResearchClaims(claims=[]),
        ResearchClaims(claims=[]),
    ])
    assert len(prompts) == 2
    rejected = graph.node_research_gate(still_empty)
    assert rejected["outcome"] == "CANDIDATE_REJECTED"
    assert rejected["candidate_rejection_reason"] == "INSUFFICIENT_EVIDENCE"

    print("[PASS] empty claim output retries once; the evidence gate remains fail-closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
