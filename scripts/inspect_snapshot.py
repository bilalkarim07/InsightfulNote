"""Inspect the newest run snapshot for traceability."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "data" / "runs"


def main() -> None:
    snaps = sorted(RUNS.glob("run_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not snaps:
        print("No snapshots found.")
        return
    p = snaps[0]
    print(f"Snapshot: {p.name}")
    print(f"Outcome:  ", end="")
    data = json.loads(p.read_text(encoding="utf-8"))
    print(data.get("outcome", "?"))
    print()

    state = data.get("state", {})

    # ── Claims in Research ──
    research = state.get("research", {})
    claims = research.get("claims", []) or []
    print(f"[Research]  {len(claims)} claim(s):")
    for c in claims:
        print(f"  {c['claim_id']:10} evidence_ids={c.get('evidence_ids')}")
    print()

    # ── Evidence in Research ──
    evidence = research.get("evidence", []) or []
    print(f"[Evidence]  {len(evidence)} item(s):")
    for e in evidence:
        print(f"  {e['evidence_id']:8} source_id={e.get('source_id')}")
    print()

    # ── Verifications ──
    verification = state.get("verification", {})
    verifications = verification.get("verifications", []) or []
    print(f"[Verification]  {len(verifications)} entry(ies):")
    for v in verifications:
        print(f"  {v['claim_id']:10} status={v.get('status'):30} evidence_ids={v.get('evidence_ids')}")
    print()

    # ── Editorial ──
    editorial = state.get("editorial", {})
    print(f"[Editorial]  allowed_claim_ids={editorial.get('allowed_claim_ids')}")
    print()

    # ── Draft ──
    draft = state.get("draft", {})
    print(f"[Draft]  claim_ids={draft.get('claim_ids')}")
    print(f"         headline={(draft.get('headline') or '')[:60]!r}")
    print()

    # ── Post ──
    post = state.get("post", {})
    print(f"[Post]  claim_ids={post.get('claim_ids')}")
    print(f"        text={(post.get('text') or '')[:80]!r}")
    print()

    # ── Traceability check ──
    print("=" * 60)
    print("Traceability chain:")
    print("=" * 60)
    for c in claims:
        cid = c["claim_id"]
        ev_ids = c.get("evidence_ids") or []
        ev_srcs = [e.get("source_id") for e in evidence if e["evidence_id"] in ev_ids]
        in_editorial = cid in (editorial.get("allowed_claim_ids") or [])
        in_post = cid in (post.get("claim_ids") or [])
        print(f"  {cid}")
        print(f"    → evidence: {ev_ids} (sources: {ev_srcs})")
        print(f"    → editorial allowed: {in_editorial}")
        print(f"    → post claim_ids: {in_post}")


if __name__ == "__main__":
    main()
