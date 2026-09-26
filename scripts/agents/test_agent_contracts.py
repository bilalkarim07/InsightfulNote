"""Contract tests — every Pydantic model must instantiate, serialize, deserialize."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from schemas.common import new_run_id  # noqa: E402
from schemas.discovery import DiscoveryResult, CandidateStory  # noqa: E402
from schemas.source_intelligence import SourceIntelligenceResult, SourceAssessment, SourceType  # noqa: E402
from schemas.research import ResearchResult, Claim, Evidence  # noqa: E402
from schemas.selection import SelectionDecision, SelectionState  # noqa: E402
from schemas.verification import VerificationResult, ClaimVerification, VerificationStatus  # noqa: E402
from schemas.editorial import EditorialDecision  # noqa: E402
from schemas.tone import ToneDecision, ToneType  # noqa: E402
from schemas.writing import WriterDraft  # noqa: E402
from schemas.platform import PlatformPost  # noqa: E402
from schemas.validation import ValidationResult, ValidationState  # noqa: E402
from schemas.publishing import PublishResult  # noqa: E402


def roundtrip(model):
    payload = model.model_dump()
    again = type(model).model_validate(payload)
    assert again == model
    return True


def main() -> None:
    rid = new_run_id()
    sid = "story_test"
    failures: list[str] = []

    def check(name: str, fn) -> None:
        try:
            fn()
            print(f"  [PASS] {name}")
        except Exception as exc:  # noqa: BLE001
            failures.append(name)
            print(f"  [FAIL] {name}: {type(exc).__name__}: {exc}")

    print("Contract roundtrip tests")
    print("=" * 70)

    check("DiscoveryResult", lambda: roundtrip(DiscoveryResult(
        run_id=rid, candidates=[CandidateStory(story_id=sid, title="T")])))
    check("SourceIntelligenceResult", lambda: roundtrip(SourceIntelligenceResult(
        run_id=rid, story_id=sid,
        assessments=[SourceAssessment(story_id=sid, source_id="s1",
                                       source_type=SourceType.PRIMARY)])))
    check("ResearchResult", lambda: roundtrip(ResearchResult(
        run_id=rid, story_id=sid,
        claims=[Claim(text="c1")],
        evidence=[Evidence(source_id="s1", quote="q")])))
    check("SelectionDecision", lambda: roundtrip(SelectionDecision(
        run_id=rid, story_id=sid, state=SelectionState.SELECT)))
    check("VerificationResult", lambda: roundtrip(VerificationResult(
        run_id=rid, story_id=sid,
        verifications=[ClaimVerification(claim_id="c1",
                                          status=VerificationStatus.SUPPORTED)])))
    check("EditorialDecision", lambda: roundtrip(EditorialDecision(
        run_id=rid, story_id=sid, central_event="ev")))
    check("ToneDecision", lambda: roundtrip(ToneDecision(
        run_id=rid, story_id=sid, tone=ToneType.INFORMATIVE)))
    check("WriterDraft", lambda: roundtrip(WriterDraft(
        run_id=rid, story_id=sid, headline="h", body="b")))
    check("PlatformPost", lambda: roundtrip(PlatformPost(
        run_id=rid, story_id=sid, text="hello")))
    check("ValidationResult", lambda: roundtrip(ValidationResult(
        run_id=rid, story_id=sid, state=ValidationState.PASS)))
    check("PublishResult", lambda: roundtrip(PublishResult(
        run_id=rid, story_id=sid)))

    print()
    if failures:
        print(f"FAILED: {len(failures)} contracts")
        sys.exit(1)
    print("ALL CONTRACTS PASS")


if __name__ == "__main__":
    main()
