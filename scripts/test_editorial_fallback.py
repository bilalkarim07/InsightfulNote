"""Manual checks for deterministic editorial fallback calibration."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.team import graph  # noqa: E402
from schemas.editorial import EditorialDecision  # noqa: E402
from schemas.research import Claim, Evidence, ResearchResult  # noqa: E402
from schemas.tone import ToneDecision, ToneType  # noqa: E402
from schemas.verification import (  # noqa: E402
    ClaimVerification,
    VerificationResult,
    VerificationStatus,
)
from schemas.writing import WriterDraft  # noqa: E402


class _RecordHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _story_state(
    claims: list[Claim],
    statuses: dict[str, VerificationStatus],
    *,
    evidence: list[Evidence] | None = None,
    editorial_memory: dict[str, Any] | None = None,
    story_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = evidence or [
        Evidence(
            evidence_id=claim.evidence_ids[0],
            source_id=f"source-{index}",
            url=f"https://example-{index}.org/report",
            quote=claim.text,
        )
        for index, claim in enumerate(claims, start=1)
        if claim.evidence_ids
    ]
    return {
        "run_id": "run_editorial_fallback",
        "story_id": "story_editorial_fallback",
        "provider": "test",
        "model_id": "test-model",
        "outcome": "RUNNING",
        "seed": {"title": "Pentagon personnel database breach"},
        "story_record": {"metadata": story_metadata or {}},
        "editorial_memory": editorial_memory or {},
        "source_intel": {
            "assessments": [
                {
                    "source_id": item.source_id,
                    "source_type": (
                        "OFFICIAL" if item.source_id == "source-1" else "SECONDARY"
                    ),
                }
                for item in evidence
            ],
        },
        "research": ResearchResult(
            run_id="run_editorial_fallback",
            story_id="story_editorial_fallback",
            claims=claims,
            evidence=evidence,
        ).model_dump(mode="json"),
        "verification": VerificationResult(
            run_id="run_editorial_fallback",
            story_id="story_editorial_fallback",
            verifications=[
                ClaimVerification(
                    claim_id=claim.claim_id,
                    status=statuses[claim.claim_id],
                    evidence_ids=list(claim.evidence_ids),
                )
                for claim in claims
            ],
        ).model_dump(mode="json"),
    }


def _invoke_editorial(
    state: dict[str, Any],
    selection: list[str] | None = None,
) -> dict[str, Any]:
    response = EditorialDecision(
        run_id=state["run_id"],
        story_id=state["story_id"],
        central_event="A foreign government directed the breach.",
        allowed_claim_ids=selection or [],
    )
    original_model = graph._model
    original_structured = graph._structured
    graph._model = lambda _state: object()
    graph._structured = lambda *_args, **_kwargs: (response, {})
    try:
        return graph.node_editorial(state)
    finally:
        graph._model = original_model
        graph._structured = original_structured


def _test_supported_fallback_and_logging() -> None:
    claims = [
        Claim(
            claim_id="claim_secondary",
            text="A defense official said unauthorized access exposed personnel data.",
            evidence_ids=["evidence-secondary"],
            attribution="A defense official",
        ),
        Claim(
            claim_id="claim_official",
            text="The Pentagon confirmed unauthorized access to a personnel database.",
            evidence_ids=["evidence-official"],
        ),
        Claim(
            claim_id="claim_forecast",
            text="The breach may lead to further investigations.",
            evidence_ids=["evidence-forecast"],
            is_forecast=True,
        ),
    ]
    evidence = [
        Evidence(
            evidence_id="evidence-secondary",
            source_id="source-2",
            url="https://news.example.org/breach",
            quote=claims[0].text,
        ),
        Evidence(
            evidence_id="evidence-official",
            source_id="source-1",
            url="https://agency.example.gov/statement",
            quote=claims[1].text,
        ),
        Evidence(
            evidence_id="evidence-forecast",
            source_id="source-3",
            url="https://news.example.net/forecast",
            quote=claims[2].text,
        ),
    ]
    statuses = {
        "claim_secondary": VerificationStatus.SUPPORTED_AS_ATTRIBUTED,
        "claim_official": VerificationStatus.SUPPORTED,
        "claim_forecast": VerificationStatus.SUPPORTED,
    }
    state = _story_state(
        claims,
        statuses,
        evidence=evidence,
        story_metadata={"topic_fit": True, "newsworthiness": True},
    )
    handler = _RecordHandler()
    graph._LOGGER.addHandler(handler)
    graph._LOGGER.setLevel(logging.WARNING)
    try:
        result = _invoke_editorial(state)
    finally:
        graph._LOGGER.removeHandler(handler)

    editorial = result["editorial"]
    assert editorial["allowed_claim_ids"] == ["claim_official"]
    assert editorial["central_event"] == (
        "The Pentagon confirmed unauthorized access to a personnel database."
    )
    assert next(c.text for c in claims if c.claim_id == "claim_official") == (
        "The Pentagon confirmed unauthorized access to a personnel database."
    )
    assert result["current_node"] == "editorial"
    assert len(handler.records) == 1
    record = handler.records[0]
    assert record.story_id == state["story_id"]
    assert record.selected_claim_id == "claim_official"
    assert record.verification_status == "SUPPORTED"
    assert record.fallback_reason == "EDITORIAL_EMPTY_SELECTION_FALLBACK"
    print("[PASS] supported story proceeds and logs deterministic fallback")


def _test_attributed_claim_is_publishable() -> None:
    claim = Claim(
        claim_id="claim_attributed",
        text="According to a U.S. defense official, about 3 million people were affected.",
        evidence_ids=["evidence-attributed"],
        attribution="A U.S. defense official",
    )
    state = _story_state(
        [claim],
        {"claim_attributed": VerificationStatus.SUPPORTED_AS_ATTRIBUTED},
    )
    result = _invoke_editorial(state)
    assert result["editorial"]["allowed_claim_ids"] == ["claim_attributed"]
    assert claim.text.startswith("According to a U.S. defense official")
    assert result["editorial"]["central_event"] == claim.text
    print("[PASS] supported-as-attributed claim retains its original attribution")


def _test_supported_status_breaks_otherwise_equal_tie() -> None:
    evidence = Evidence(
        evidence_id="evidence-shared",
        source_id="source-official",
        url="https://agency.example.gov/statement",
    )
    claims = [
        Claim(
            claim_id="claim-attributed",
            text="The Pentagon confirmed unauthorized access to a personnel database.",
            evidence_ids=[evidence.evidence_id],
        ),
        Claim(
            claim_id="claim-supported",
            text="The Pentagon confirmed unauthorized access to a personnel database.",
            evidence_ids=[evidence.evidence_id],
        ),
    ]
    research = ResearchResult(
        run_id="run_tie_break",
        story_id="story_tie_break",
        claims=claims,
        evidence=[evidence],
    )
    verification = VerificationResult(
        run_id="run_tie_break",
        story_id="story_tie_break",
        verifications=[
            ClaimVerification(
                claim_id="claim-attributed",
                status=VerificationStatus.SUPPORTED_AS_ATTRIBUTED,
                evidence_ids=[evidence.evidence_id],
            ),
            ClaimVerification(
                claim_id="claim-supported",
                status=VerificationStatus.SUPPORTED,
                evidence_ids=[evidence.evidence_id],
            ),
        ],
    )
    selected = graph._select_strongest_verified_claim(
        research,
        verification,
        {"assessments": [{"source_id": evidence.source_id, "source_type": "OFFICIAL"}]},
    )
    assert selected is not None and selected[0].claim_id == "claim-supported"
    print("[PASS] SUPPORTED wins an otherwise equal claim-selection tie")


def _test_unsupported_claims_are_excluded() -> None:
    safe = Claim(
        claim_id="claim_safe",
        text="The Pentagon confirmed unauthorized access to a personnel database.",
        evidence_ids=["evidence-safe"],
    )
    unsupported_claims = [
        Claim(
            claim_id="claim_attacker",
            text="Hackers linked to a foreign government accessed the database.",
            evidence_ids=["evidence-attacker"],
        ),
        Claim(
            claim_id="claim_foreign",
            text="A foreign government directed the breach.",
            evidence_ids=["evidence-foreign"],
        ),
        Claim(
            claim_id="claim_misuse",
            text="The accessed information was used for identity theft.",
            evidence_ids=["evidence-misuse"],
        ),
    ]
    claims = [safe, *unsupported_claims]
    state = _story_state(
        claims,
        {
            "claim_safe": VerificationStatus.SUPPORTED,
            "claim_attacker": VerificationStatus.UNCERTAIN,
            "claim_foreign": VerificationStatus.UNSUPPORTED,
            "claim_misuse": VerificationStatus.CONTRADICTED,
        },
    )
    result = _invoke_editorial(state)
    assert result["editorial"]["allowed_claim_ids"] == ["claim_safe"]
    assert all(
        claim.claim_id not in result["editorial"]["allowed_claim_ids"]
        for claim in unsupported_claims
    )
    print("[PASS] uncertain attacker, foreign involvement, and misuse stay excluded")


def _test_duplicate_and_quality_gates() -> None:
    claim = Claim(
        claim_id="claim_verified",
        text="The Pentagon confirmed unauthorized access to a personnel database.",
        evidence_ids=["evidence-verified"],
    )
    statuses = {"claim_verified": VerificationStatus.SUPPORTED}
    duplicate_state = _story_state(
        [claim],
        statuses,
        editorial_memory={
            "similar_stories": [
                {"relationship": "REPETITIVE", "title": "Earlier breach report"},
            ],
        },
    )
    duplicate = _invoke_editorial(duplicate_state)
    assert duplicate["outcome"] == "CANDIDATE_REJECTED"
    assert duplicate["candidate_rejection_reason"] == "DUPLICATE_NO_MATERIAL_UPDATE"

    material_update = _invoke_editorial(duplicate_state, ["claim_verified"])
    assert material_update.get("outcome") != "CANDIDATE_REJECTED"
    assert material_update["editorial"]["allowed_claim_ids"] == ["claim_verified"]

    failed_quality = _invoke_editorial(_story_state(
        [claim],
        statuses,
        story_metadata={"topic_fit": True, "newsworthiness": False},
    ))
    assert failed_quality["outcome"] == "CANDIDATE_REJECTED"
    assert failed_quality["candidate_rejection_reason"] == "EDITORIAL_QUALITY_GATE_FAILED"

    no_verified = _story_state(
        [claim],
        {"claim_verified": VerificationStatus.UNCERTAIN},
    )
    result = _invoke_editorial(no_verified)
    assert result["candidate_rejection_reason"] == "NO_EDITORIAL_PATH"
    print("[PASS] duplicate/no-update and failed quality gates remain hard rejections")


def _test_writer_preserves_attribution_status() -> None:
    claim = Claim(
        claim_id="claim_attributed",
        text="According to a U.S. defense official, about 3 million people were affected.",
        evidence_ids=["evidence-attributed"],
        attribution="A U.S. defense official",
    )
    state = _story_state(
        [claim],
        {"claim_attributed": VerificationStatus.SUPPORTED_AS_ATTRIBUTED},
    )
    state.update({
        "editorial": EditorialDecision(
            run_id=state["run_id"],
            story_id=state["story_id"],
            central_event=claim.text,
            allowed_claim_ids=[claim.claim_id],
        ).model_dump(mode="json"),
        "tone": ToneDecision(
            run_id=state["run_id"],
            story_id=state["story_id"],
            tone=ToneType.INFORMATIVE,
            rationale="Factual report.",
        ).model_dump(mode="json"),
    })
    captured: dict[str, str] = {}
    original_model = graph._model
    original_structured = graph._structured
    graph._model = lambda _state: object()

    def structured(_client, _schema, prompt, *_args, **_kwargs):
        captured["prompt"] = prompt
        return (
            WriterDraft(
                run_id=state["run_id"],
                story_id=state["story_id"],
                body=claim.text,
                claim_ids=[claim.claim_id],
            ),
            {},
        )

    graph._structured = structured
    try:
        graph.node_writer(state)
        retry_state = dict(state)
        retry_state.update({
            "iteration": {"writer": 1},
            "validation": {"failed_sentences": ["A paraphrased unsupported sentence."]},
            "validation_feedback": ["post contains a sentence not grounded in an approved claim"],
        })
        graph.node_writer(retry_state)
    finally:
        graph._model = original_model
        graph._structured = original_structured
    assert "[SUPPORTED_AS_ATTRIBUTED]" in captured["prompt"]
    assert "never state the attributed fact as independently confirmed" in captured["prompt"]
    assert claim.text in captured["prompt"]
    assert "copy the text of one approved claim" in captured["prompt"]
    assert "list only that claim ID" in captured["prompt"]
    print("[PASS] writer receives explicit attribution preservation instructions")


def _test_writer_uses_exact_claim_after_grounding_failure() -> None:
    claim = Claim(
        claim_id="claim_climate",
        text="The IPCC says attribution science helps assess climate change impacts.",
        evidence_ids=["evidence-climate"],
    )
    state = _story_state(
        [claim],
        {"claim_climate": VerificationStatus.SUPPORTED},
    )
    state.update({
        "editorial": EditorialDecision(
            run_id=state["run_id"],
            story_id=state["story_id"],
            central_event=claim.text,
            allowed_claim_ids=[claim.claim_id],
        ).model_dump(mode="json"),
        "tone": ToneDecision(
            run_id=state["run_id"],
            story_id=state["story_id"],
            tone=ToneType.ANALYTICAL,
        ).model_dump(mode="json"),
    })
    calls = 0
    original_model = graph._model
    original_structured = graph._structured
    graph._model = lambda _state: object()

    def structured(_client, _schema, *_args, **_kwargs):
        nonlocal calls
        calls += 1
        return (
            WriterDraft(
                run_id=state["run_id"],
                story_id=state["story_id"],
                body="It helps understand and assess climate change impacts.",
                claim_ids=[claim.claim_id],
            ),
            {},
        )

    graph._structured = structured
    try:
        first = graph.node_writer(state)
        retry_state = dict(state)
        retry_state.update({
            "iteration": {"writer": 1},
            "validation": {
                "failed_sentences": [
                    "It helps understand and assess climate change impacts."
                ],
            },
            "validation_feedback": [
                "post contains a sentence not grounded in an approved claim"
            ],
        })
        retried = graph.node_writer(retry_state)
    finally:
        graph._model = original_model
        graph._structured = original_structured

    assert first["draft"]["body"] == "It helps understand and assess climate change impacts."
    assert retried["draft"]["body"] == claim.text
    assert retried["draft"]["claim_ids"] == [claim.claim_id]
    assert calls == 1
    print("[PASS] grounding retry uses exact verified claim without another LLM rewrite")


def _test_verified_source_link() -> None:
    claim = Claim(
        claim_id="claim_link",
        text="The agency announced a new public program.",
        evidence_ids=["evidence-secondary", "evidence-official"],
    )
    evidence = [
        Evidence(
            evidence_id="evidence-secondary",
            source_id="source-secondary",
            url="https://news.example.org/program",
            quote=claim.text,
        ),
        Evidence(
            evidence_id="evidence-official",
            source_id="source-official",
            url="https://agency.gov/program",
            quote=claim.text,
        ),
    ]
    state = _story_state(
        [claim],
        {"claim_link": VerificationStatus.SUPPORTED},
        evidence=evidence,
    )
    state["editorial"] = EditorialDecision(
        run_id=state["run_id"],
        story_id=state["story_id"],
        central_event=claim.text,
        allowed_claim_ids=[claim.claim_id],
    ).model_dump(mode="json")
    state["source_intel"] = {
        "assessments": [
            {"source_id": "source-secondary", "source_type": "SECONDARY"},
            {"source_id": "source-official", "source_type": "OFFICIAL"},
        ],
    }

    source_url = graph._verified_source_reference(state, [claim.claim_id])
    assert source_url == "https://agency.gov/program"
    linked_text = graph._append_source_reference(
        claim.text, source_url, limit=200,
    )
    assert linked_text.endswith("\nSource: https://agency.gov/program")
    assert len(linked_text) <= 200
    assert graph._append_source_reference(claim.text, source_url, limit=30) == claim.text

    adapter_state = dict(state)
    adapter_state.update({
        "iteration": {"writer": 2},
        "validation_feedback": ["retry"],
        "draft": WriterDraft(
            run_id=state["run_id"],
            story_id=state["story_id"],
            body=claim.text,
            claim_ids=[claim.claim_id],
        ).model_dump(mode="json"),
    })
    adapted = graph.node_platform_adapter(adapter_state)["post"]
    assert adapted["text"].endswith("\nSource: https://agency.gov/program")
    assert adapted["source_reference"] == source_url
    assert adapted["char_count"] == len(adapted["text"])

    validation_state = {
        "run_id": state["run_id"],
        "story_id": state["story_id"],
        "seed": {"title": "agency program", "summary": claim.text},
        "research": ResearchResult(
            run_id=state["run_id"],
            story_id=state["story_id"],
            claims=[claim],
            evidence=evidence,
        ).model_dump(mode="json"),
        "verification": VerificationResult(
            run_id=state["run_id"],
            story_id=state["story_id"],
            verifications=[
                ClaimVerification(
                    claim_id=claim.claim_id,
                    status=VerificationStatus.SUPPORTED,
                    evidence_ids=list(claim.evidence_ids),
                ),
            ],
        ).model_dump(mode="json"),
        "editorial": state["editorial"],
        "draft": WriterDraft(
            run_id=state["run_id"],
            story_id=state["story_id"],
            body=claim.text,
            claim_ids=[claim.claim_id],
        ).model_dump(mode="json"),
        "post": {
            "run_id": "run_source_link",
            "story_id": "story_source_link",
            "platform": "threads",
            **adapted,
        },
        "tone": ToneDecision(
            run_id="run_source_link",
            story_id="story_source_link",
            tone=ToneType.INFORMATIVE,
            rationale="Factual report.",
        ).model_dump(mode="json"),
        "outcome": "RUNNING",
        "iteration": {},
    }
    valid_link = graph.node_validation(validation_state)
    assert valid_link["validation"]["state"] == "PASS"

    validation_state["post"] = {
        **validation_state["post"],
        "text": linked_text.replace("https://agency.gov/program", "https://unverified.invalid"),
    }
    invalid_link = graph.node_validation(validation_state)
    assert invalid_link["validation"]["state"] == "BLOCK"
    assert "post contains an unverified URL" in invalid_link["validation"]["errors"]
    print("[PASS] only a cited verified source link is accepted when it fits")


def _test_length_validation_remains_strict() -> None:
    from core.tools.compress import compress_to_limit

    text = compress_to_limit(
        "Tesla announced the Model Y today. The company said production will "
        "begin in California after additional testing.",
        limit=38,
    )
    assert len(text) <= 38
    assert text.endswith((".", "!", "?"))
    assert not text.endswith(("…", "..."))
    assert text == "Tesla announced the Model Y today."

    claim = Claim(
        claim_id="claim_post",
        text="Tesla announced the Model Y today.",
        evidence_ids=["evidence-post"],
    )
    evidence = Evidence(
        evidence_id="evidence-post",
        source_id="source-post",
        url="https://tesla.example.org/announcement",
        quote=claim.text,
    )
    validation_state = {
        "run_id": "run_length_validation",
        "story_id": "story_length_validation",
        "seed": {"title": "Tesla Model Y", "summary": "Tesla announced the Model Y today."},
        "research": ResearchResult(
            run_id="run_length_validation",
            story_id="story_length_validation",
            claims=[claim],
            evidence=[evidence],
        ).model_dump(mode="json"),
        "verification": VerificationResult(
            run_id="run_length_validation",
            story_id="story_length_validation",
            verifications=[
                ClaimVerification(
                    claim_id=claim.claim_id,
                    status=VerificationStatus.SUPPORTED,
                    evidence_ids=[evidence.evidence_id],
                ),
            ],
        ).model_dump(mode="json"),
        "editorial": EditorialDecision(
            run_id="run_length_validation",
            story_id="story_length_validation",
            central_event=claim.text,
            allowed_claim_ids=[claim.claim_id],
        ).model_dump(mode="json"),
        "draft": WriterDraft(
            run_id="run_length_validation",
            story_id="story_length_validation",
            body=text,
            claim_ids=[claim.claim_id],
        ).model_dump(mode="json"),
        "post": {
            "run_id": "run_length_validation",
            "story_id": "story_length_validation",
            "platform": "threads",
            "text": text,
            "char_count": len(text),
            "claim_ids": [claim.claim_id],
        },
        "tone": ToneDecision(
            run_id="run_length_validation",
            story_id="story_length_validation",
            tone=ToneType.INFORMATIVE,
            rationale="Factual report.",
        ).model_dump(mode="json"),
        "outcome": "RUNNING",
        "iteration": {},
    }
    result = graph.node_validation(validation_state)
    assert result["validation"]["state"] == "PASS"
    print("[PASS] complete compressed sentence passes unchanged final validation")


def main() -> None:
    _test_supported_fallback_and_logging()
    _test_attributed_claim_is_publishable()
    _test_supported_status_breaks_otherwise_equal_tie()
    _test_unsupported_claims_are_excluded()
    _test_duplicate_and_quality_gates()
    _test_writer_preserves_attribution_status()
    _test_writer_uses_exact_claim_after_grounding_failure()
    _test_verified_source_link()
    _test_length_validation_remains_strict()
    print("\nALL EDITORIAL FALLBACK CHECKS PASSED")


if __name__ == "__main__":
    main()
