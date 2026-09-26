"""Isolated verification test — bypasses research gate.

Feeds the verification node a claim and matching evidence directly, so we
can observe whether the backfill fires regardless of research quality.
"""
from __future__ import annotations
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from schemas.research import ResearchResult, Claim, Evidence
from core.team.graph import node_verification


def main() -> None:
    research = ResearchResult(
        run_id="run_test_verif",
        story_id="story_test_verif",
        claims=[
            Claim(
                claim_id="claim_1",
                text="Lead Stories fact-checked the TikTok video as AI-generated clickbait.",
                evidence_ids=["ev_1"],
            ),
            Claim(
                claim_id="claim_2",
                text="The video falsely claims JD Vance was confirmed as a candidate.",
                evidence_ids=["ev_2"],
            ),
        ],
        evidence=[
            Evidence(
                evidence_id="ev_1", source_id="s1",
                quote=("Fact Check: FAKE Breaking News Video Titled 'Sad News: "
                       "30 Minutes Ago In Ohio, JD Vance Was Confirmed As...' "
                       "Is AI-Generated Clickbait Headline Tease"),
            ),
            Evidence(
                evidence_id="ev_2", source_id="s2",
                quote=("Lead Stories labeled the TikTok video claiming JD Vance "
                       "was confirmed as a candidate in Ohio as AI-generated "
                       "clickbait, not a genuine news report."),
            ),
        ],
    )

    state = {
        "run_id": "run_test_verif",
        "story_id": "story_test_verif",
        "provider": "ollama",
        "model_id": "gpt-oss:120b",
        "research": research.model_dump(mode="json"),
        "messages": [],
        "iteration": {},
    }

    print("=" * 70)
    print("Isolated verification test")
    print("=" * 70)

    out = node_verification(state)
    verifications = (out.get("verification") or {}).get("verifications", [])

    print()
    print(f"Verifications returned: {len(verifications)}")
    for v in verifications:
        print(f"  {v['claim_id']:10} status={v['status']:30} evidence_ids={v['evidence_ids']}")

    # Verify backfill worked
    all_have_evidence = all(v.get("evidence_ids") for v in verifications)
    if all_have_evidence:
        print()
        print("BACKFILL OK — every verification carries evidence_ids")
    else:
        print()
        print("BACKFILL NOT FIRING — some verifications still have empty evidence_ids")


if __name__ == "__main__":
    main()
