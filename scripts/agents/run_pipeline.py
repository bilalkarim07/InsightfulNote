"""Deterministic pipeline supervisor.

Runs the full agent chain over one candidate story. LLM agents are invoked
with invoke_structured; deterministic agents are plain functions.

    candidate story
      -> Discovery (LLM)
      -> Source Intelligence (LLM)
      -> Research (LLM + tools)
      -> Selection (LLM)
      -> Verification (LLM)
      -> Editorial (LLM)
      -> Tone (LLM)
      -> Writer (LLM)
      -> Platform Adapter (LLM)
      -> Validation (deterministic)
      -> Publisher (deterministic stub)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from schemas.common import new_run_id  # noqa: E402
from schemas.discovery import DiscoveryResult  # noqa: E402
from schemas.source_intelligence import SourceIntelligenceResult  # noqa: E402
from schemas.research import ResearchResult  # noqa: E402
from schemas.selection import SelectionDecision, SelectionState  # noqa: E402
from schemas.verification import (  # noqa: E402
    VerificationResult, VerificationStatus,
)
from schemas.editorial import EditorialDecision  # noqa: E402
from schemas.tone import ToneDecision  # noqa: E402
from schemas.writing import WriterDraft  # noqa: E402
from schemas.platform import PlatformPost  # noqa: E402
from schemas.validation import ValidationResult, ValidationState  # noqa: E402
from schemas.publishing import PublishResult  # noqa: E402

from core.llm.factory import get_chat_model  # noqa: E402
from core.llm.persistence import load_capabilities  # noqa: E402
from core.llm.providers import (  # noqa: E402
    OllamaProvider, GroqProvider, OpenRouterProvider, GeminiProvider, ProviderFactory,
)
from core.llm.registry import build_default_registry  # noqa: E402
from core.tools.search import search_web  # noqa: E402
from scripts.llm._structured import invoke_structured, StructuredOutputError  # noqa: E402

ProviderFactory.register(OllamaProvider(cloud=True))
ProviderFactory.register(GroqProvider())
ProviderFactory.register(OpenRouterProvider())
ProviderFactory.register(GeminiProvider())


def _model_for(provider: str, model_id: str):
    registry = build_default_registry()
    load_capabilities(registry)
    entry = registry.get(provider, model_id)
    if entry is None or not entry.capabilities:
        raise RuntimeError(f"Unknown or unverified model: {provider}/{model_id}")
    return get_chat_model(entry, timeout=180), entry


def _structured(client, schema, prompt: str, provider: str):
    supports_schema = provider != "ollama"
    try:
        return invoke_structured(client, schema, prompt, supports_json_schema=supports_schema)
    except StructuredOutputError as exc:
        print(f"    [retry] {str(exc)[:200]}")
        terse = prompt + "\n\nReturn ONLY the JSON object, no prose."
        return invoke_structured(client, schema, terse, supports_json_schema=supports_schema)



# ── Deterministic gates (spec §13, §53, §55, §107) ──────────────

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at",
    "for", "with", "by", "is", "are", "was", "were", "be", "been", "being",
    "that", "this", "these", "those", "it", "its", "as", "from", "will",
    "has", "have", "had", "not", "no", "than", "then", "so", "such",
}


def _ngrams(text: str, n: int = 3) -> set[str]:
    """Return set of lowercase n-word phrases, stripping punctuation and stopwords."""
    words = [
        w.lower().strip(".,;:!?\"'()[]{}—–-")
        for w in text.split()
    ]
    words = [w for w in words if w and w not in _STOPWORDS]
    return {
        " ".join(words[i:i + n])
        for i in range(len(words) - n + 1)
    }


def _claim_has_verbatim_support(claim_text: str, quotes: list[str], n: int = 3) -> bool:
    """True iff claim shares at least one n-word phrase with any quote."""
    claim_grams = _ngrams(claim_text, n)
    if not claim_grams:
        return False
    for q in quotes:
        if claim_grams & _ngrams(q, n):
            return True
    return False


def _seed_subject_in_post(seed: dict, post_text: str) -> bool:
    """True iff at least one distinctive word from the seed subject appears in the post."""
    subject_tokens = [
        w.lower().strip(".,;:!?\"'()[]{}—–-")
        for w in f"{seed['title']} {seed['summary']}".split()
        if w.lower() not in _STOPWORDS and len(w) > 2
    ]
    if not subject_tokens:
        return True  # no distinctive seed → skip this gate
    post_lower = post_text.lower()
    return any(tok in post_lower for tok in subject_tokens)

# ── stages ──────────────────────────────────────────────────

def stage_discovery(client, provider, run_id: str, seed: dict) -> DiscoveryResult:
    prompt = (
        f'Produce a DiscoveryResult with run_id="{run_id}" and one CandidateStory '
        f'with story_id="{seed["story_id"]}", title="{seed["title"]}", '
        f'summary="{seed["summary"]}", topic="{seed["topic"]}", '
        f'is_breaking=true, independent_source_count=2. '
        f'Return JSON only with this shape: '
        f'{{"run_id": "{run_id}", "candidates": [{{"story_id": "...", "title": "...", '
        f'"summary": "...", "topic": "...", "source_ids": [], "is_breaking": true, '
        f'"is_emerging": false, "independent_source_count": 2, '
        f'"first_seen_at": null, "discovery_rationale": ""}}], "notes": ""}}'
    )
    parsed, _ = _structured(client, DiscoveryResult, prompt, provider)
    return parsed


def stage_source_intel(client, provider, run_id: str, story_id: str) -> SourceIntelligenceResult:
    prompt = (
        f'Produce a SourceIntelligenceResult with run_id="{run_id}", '
        f'story_id="{story_id}", and one SourceAssessment '
        f'with story_id="{story_id}", source_id="s1", '
        f'source_type="PRIMARY", authority="official press release", '
        f'independence="independent". '
        f'Return JSON only: '
        f'{{"run_id": "{run_id}", "story_id": "{story_id}", "assessments": '
        f'[{{"story_id": "{story_id}", "source_id": "s1", "source_name": "", '
        f'"source_type": "PRIMARY", "authority": "", "independence": "", '
        f'"attribution": "", "confidence": null, "conflicts": [], "uncertainty": []}}], '
        f'"independent_reporting": true, "copying_detected": false, "notes": ""}}'
    )
    parsed, _ = _structured(client, SourceIntelligenceResult, prompt, provider)
    return parsed


def stage_research(client, provider, run_id: str, story_id: str) -> ResearchResult:
    ev1 = search_web.invoke({"query": "Company X product Y"})
    ev2 = search_web.invoke({"query": "Company X analyst reaction"})

    prompt = f"""
Produce a ResearchResult with run_id="{run_id}", story_id="{story_id}",
TWO claims and TWO evidence items.

Evidence:
- source_id="s1", quote={ev1!r}
- source_id="s2", quote={ev2!r}

Return this exact shape:
{{
  "run_id": "{run_id}",
  "story_id": "{story_id}",
  "claims": [
    {{"claim_id": "claim_1", "text": "<fact from s1>", "evidence_ids": ["ev_1"],
      "attribution": "", "uncertainty": "",
      "is_forecast": false, "is_allegation": false, "is_opinion": false}},
    {{"claim_id": "claim_2", "text": "<attributed forecast from s2>",
      "evidence_ids": ["ev_2"], "attribution": "<who>", "uncertainty": "<how certain>",
      "is_forecast": true, "is_allegation": false, "is_opinion": false}}
  ],
  "evidence": [
    {{"evidence_id": "ev_1", "source_id": "s1", "quote": "<verbatim>",
      "url": null, "retrieved_at": null, "context": ""}},
    {{"evidence_id": "ev_2", "source_id": "s2", "quote": "<verbatim>",
      "url": null, "retrieved_at": null, "context": ""}}
  ],
  "missing_information": [], "conflicting_claims": [], "notes": ""
}}

Rules:
- If the evidence is NOT about the story subject, do NOT fabricate a link.
  Instead, produce ZERO claims and note it in missing_information.
- claims and evidence are SIBLING arrays
- Claim.evidence_ids are STRING ids
- If a claim is a forecast, set is_forecast=true AND fill attribution
""".strip()
    parsed, _ = _structured(client, ResearchResult, prompt, provider)
    return parsed


def stage_selection(client, provider, run_id: str, story_id: str) -> SelectionDecision:
    prompt = (
        f'Produce a SelectionDecision with run_id="{run_id}", '
        f'story_id="{story_id}", state="SELECT", '
        f'reason="fresh, primary source available", '
        f'priority=10, topic="technology", novelty_score=0.9. '
        f'Return JSON only: {{"run_id": "{run_id}", "story_id": "{story_id}", '
        f'"state": "SELECT", "reason": "", "priority": 10, "topic": "technology", '
        f'"novelty_score": 0.9, "previous_publication_ids": [], "notes": ""}}'
    )
    parsed, _ = _structured(client, SelectionDecision, prompt, provider)
    return parsed


def stage_verification(
    client, provider, run_id: str, story_id: str, research: ResearchResult
) -> VerificationResult:
    claims_block = "\n".join(
        f"- claim_id={c.claim_id}, text={c.text!r}, is_forecast={c.is_forecast}"
        for c in research.claims
    )
    prompt = f"""
Produce a VerificationResult with run_id="{run_id}", story_id="{story_id}".

Claims:
{claims_block}

Rules:
- Factual claim with matching evidence -> SUPPORTED
- Forecast / attributed claim -> SUPPORTED_AS_ATTRIBUTED
- Preserve attribution and uncertainty in notes.

Return JSON only:
{{
  "run_id": "{run_id}",
  "story_id": "{story_id}",
  "verifications": [
    {{"claim_id": "claim_1", "status": "SUPPORTED", "evidence_ids": ["ev_1"],
      "contradictions": [], "notes": ""}},
    {{"claim_id": "claim_2", "status": "SUPPORTED_AS_ATTRIBUTED",
      "evidence_ids": ["ev_2"], "contradictions": [], "notes": ""}}
  ],
  "blocking": false, "escalate": false, "notes": ""
}}
""".strip()
    parsed, _ = _structured(client, VerificationResult, prompt, provider)
    return parsed


def stage_editorial(
    client, provider, run_id: str, story_id: str, verification: VerificationResult
) -> EditorialDecision:
    allowed = [
        v.claim_id for v in verification.verifications
        if v.status in (VerificationStatus.SUPPORTED,
                        VerificationStatus.SUPPORTED_AS_ATTRIBUTED)
    ]
    prompt = (
        f'Produce an EditorialDecision with run_id="{run_id}", '
        f'story_id="{story_id}", central_event="Company X announced product Y", '
        f'allowed_claim_ids={json.dumps(allowed)}, blocked_claim_ids=[], '
        f'must_include=["the announcement", "attribution for any forecast"], '
        f'do_not_include=["unsupported speculation"]. '
        f'Return JSON with fields: run_id, story_id, central_event, '
        f'allowed_claim_ids, blocked_claim_ids, must_include, optional, '
        f'do_not_include, attribution_notes, uncertainty_notes, framing.'
    )
    parsed, _ = _structured(client, EditorialDecision, prompt, provider)
    return parsed


def stage_tone(client, provider, run_id: str, story_id: str) -> ToneDecision:
    prompt = (
        f'Produce a ToneDecision with run_id="{run_id}", story_id="{story_id}", '
        f'tone="INFORMATIVE", rationale="tech product, no sensitivity". '
        f'Return JSON only: {{"run_id": "{run_id}", "story_id": "{story_id}", '
        f'"tone": "INFORMATIVE", "rationale": "", "constraints": []}}'
    )
    parsed, _ = _structured(client, ToneDecision, prompt, provider)
    return parsed


def stage_writer(
    client, provider, run_id: str, story_id: str,
    research: ResearchResult, editorial: EditorialDecision, tone: ToneDecision,
) -> WriterDraft:
    approved_lines = "\n".join(
        f"- {c.claim_id}: {c.text} (attribution={c.attribution!r}, "
        f"is_forecast={c.is_forecast})"
        for c in research.claims if c.claim_id in editorial.allowed_claim_ids
    )
    prompt = f"""
Produce a WriterDraft with run_id="{run_id}", story_id="{story_id}".

Approved claims:
{approved_lines}

Rules:
- Use ONLY information from the approved claims above.
- For forecast claims, PRESERVE attribution and uncertainty.
  Write "Analysts at Firm Z expect..." NOT "X will...".
- Tone: {tone.tone.value}
- claim_ids must include every claim_id used.

Return JSON with fields: run_id, story_id, headline, body, source_reference,
claim_ids, tone, warnings.
""".strip()
    parsed, _ = _structured(client, WriterDraft, prompt, provider)
    return parsed


def stage_platform_adapter(
    client, provider, run_id: str, story_id: str, draft: WriterDraft
) -> PlatformPost:
    """Adapt the writer draft to a Threads post.

    Preserves facts, attribution and uncertainty. Does not invent.
    Threads posts are short — target under 500 chars for this pipeline.
    """
    prompt = f"""
Produce a PlatformPost for Threads.

run_id="{run_id}"
story_id="{story_id}"
platform="threads"

Writer draft to adapt:
HEADLINE: {draft.headline}
BODY: {draft.body}

Rules:
- Preserve every fact, number, date and attribution exactly.
- NEVER change "Analysts expect" into "will". Attribution is frozen.
- Do NOT invent facts.
- Keep it under 500 characters if possible.
- Write in a clean, scannable style suitable for Threads.

Return JSON with these fields:
- text: the ACTUAL adapted post text (not a placeholder)
- char_count: the integer length of that text
- claim_ids: {json.dumps(draft.claim_ids)}
- source_reference: "{draft.source_reference}"
""".strip()
    parsed, _ = _structured(client, PlatformPost, prompt, provider)
    return parsed


def stage_validation(
    post: PlatformPost, draft: WriterDraft,
    editorial: EditorialDecision, research: ResearchResult,
    seed: dict,
) -> ValidationResult:
    errors: list[str] = []
    if not post.text.strip():
        errors.append("empty post text")
    # char_count is now computed deterministically before validation,
    # so any mismatch here means post-processing was bypassed.
    if post.char_count != len(post.text):
        errors.append(
            f"char_count mismatch after post-processing: "
            f"{post.char_count} vs {len(post.text)}"
        )
    for cid in post.claim_ids:
        if cid not in editorial.allowed_claim_ids:
            errors.append(f"post references unapproved claim: {cid}")
    for cid in draft.claim_ids:
        if cid not in editorial.allowed_claim_ids:
            errors.append(f"draft references unapproved claim: {cid}")

    # Deterministic: seed subject must appear in the post.
    if not _seed_subject_in_post(seed, post.text):
        errors.append(
            f"post does not mention any distinctive seed subject: {seed['title']!r}"
        )
    # Deterministic: forecast attributions must survive to the post.
    for c in research.claims:
        if not c.is_forecast:
            continue
        if c.claim_id not in editorial.allowed_claim_ids:
            continue
        attr = (c.attribution or "").strip()
        if not attr:
            continue
        anchor = max(attr.split(), key=len).strip(".,;:")
        if anchor and anchor.lower() not in post.text.lower():
            errors.append(
                f"forecast claim {c.claim_id} attribution '{attr}' "
                f"missing from post"
            )

    # Threads enforces 500 chars.
    if len(post.text) > 500:
        errors.append(f"post exceeds Threads limit: {len(post.text)} > 500")

    state = ValidationState.PASS if not errors else ValidationState.BLOCK
    return ValidationResult(
        run_id=post.run_id, story_id=post.story_id, state=state, errors=errors,
    )


def stage_publisher(post: PlatformPost, run_id: str, dry_run: bool = True) -> PublishResult:
    from core.tools.publishing import publish_threads
    result = publish_threads(post.text, dry_run=dry_run)
    return PublishResult(
        run_id=run_id, story_id=post.story_id,
        platform="threads",
        status=result["status"],
        url=result.get("url"),
        error=result.get("error"),
    )


# ── supervisor ──────────────────────────────────────────────

def run_pipeline(provider: str, model_id: str, dry_run: bool = True, topic: str | None = None) -> int:
    print("=" * 70)
    print(f"Pipeline supervisor - {provider}/{model_id} (dry_run={dry_run})")
    print("=" * 70)

    try:
        client, _ = _model_for(provider, model_id)
    except RuntimeError as exc:
        print(f"[SKIP] {exc}")
        return 2

    run_id = new_run_id()
    if topic:
        seed = {
            "story_id": f"story_{run_id[4:]}",
            "title": topic,
            "summary": f"Latest developments regarding: {topic}",
            "topic": "news",
        }
    else:
        seed = {
            "story_id": f"story_{run_id[4:]}",
            "title": "Company X announces product Y",
            "summary": "Company X today announced product Y, available Q2 2026.",
            "topic": "technology",
        }
    story_id = seed["story_id"]

    # Step 1: up to Research
    pre_stages = [
        ("Discovery",    lambda: stage_discovery(client, provider, run_id, seed)),
        ("Source Intel", lambda: stage_source_intel(client, provider, run_id, story_id)),
        ("Research",     lambda: stage_research(client, provider, run_id, story_id)),
    ]
    results: dict[str, object] = {}
    for name, fn in pre_stages:
        print(f"\n[{name}]")
        try:
            out = fn()
            results[name] = out
            print(f"  OK  ({type(out).__name__})")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL: {type(exc).__name__}: {exc}")
            print(f"\nPIPELINE FAIL at {name}")
            return 3

    research: ResearchResult = results["Research"]  # type: ignore[assignment]

    # ── Deterministic evidence-verbatim gate (spec §53, §107) ──
    print("\n[Evidence Gate]")
    evidence_by_id = {e.evidence_id: e.quote for e in research.evidence}
    gate_errors: list[str] = []
    for c in research.claims:
        quotes = [evidence_by_id[eid] for eid in c.evidence_ids
                  if eid in evidence_by_id]
        if not quotes:
            gate_errors.append(f"claim {c.claim_id} cites no known evidence")
            continue
        n = 2 if c.is_forecast else 3
        if not _claim_has_verbatim_support(c.text, quotes, n=n):
            gate_errors.append(
                f"claim {c.claim_id} ({n}-gram check) has no verbatim "
                f"overlap with its evidence: {c.text!r}"
            )
    if gate_errors:
        for err in gate_errors:
            print(f"  [BLOCK] {err}")
        print("\nINSUFFICIENT EVIDENCE — NOT PUBLISHED")
        return 5
    print(f"  all {len(research.claims)} claim(s) have verbatim evidence support")

    print("\n[Selection]")
    selection = stage_selection(client, provider, run_id, story_id)
    print(f"  state={selection.state.value}  reason={selection.reason!r}")

    print("\n[Verification]")
    verification = stage_verification(client, provider, run_id, story_id, research)
    for v in verification.verifications:
        print(f"  {v.claim_id}: {v.status.value}")

    print("\n[Editorial]")
    editorial = stage_editorial(client, provider, run_id, story_id, verification)
    print(f"  central_event={editorial.central_event!r}")
    print(f"  allowed_claims={editorial.allowed_claim_ids}")

    print("\n[Tone]")
    tone = stage_tone(client, provider, run_id, story_id)
    print(f"  tone={tone.tone.value}")

    print("\n[Writer]")
    draft = stage_writer(client, provider, run_id, story_id, research, editorial, tone)
    print(f"  headline: {draft.headline}")
    print(f"  body:     {draft.body[:140]}...")

    print("\n[Platform Adapter]")
    post = stage_platform_adapter(client, provider, run_id, story_id, draft)
    # Deterministic post-processing: never trust LLM character counting.
    post.char_count = len(post.text)
    THREADS_LIMIT = 500
    if post.char_count > THREADS_LIMIT:
        trimmed = post.text[:THREADS_LIMIT - 1].rsplit(" ", 1)[0] + "…"
        print(f"  [trim] {post.char_count} -> {len(trimmed)} (threads limit)")
        post.text = trimmed
        post.char_count = len(post.text)
    print(f"  text ({post.char_count} chars): {post.text[:140]}...")

    print("\n[Validation]")
    validation = stage_validation(post, draft, editorial, research, seed)
    print(f"  state={validation.state.value}  errors={validation.errors}")

    if validation.state != ValidationState.PASS:
        print("\nPIPELINE BLOCKED at Validation")
        return 4

    print("\n[Publisher]")
    publication = stage_publisher(post, run_id, dry_run=dry_run)
    print(f"  status={publication.status}  url={publication.url}")

    snap = Path("data/runs")
    snap.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "story_id": story_id,
        "stages": {
            "discovery":    results["Discovery"].model_dump(mode="json"),     # type: ignore[union-attr]
            "source_intel": results["Source Intel"].model_dump(mode="json"),  # type: ignore[union-attr]
            "research":     research.model_dump(mode="json"),
            "selection":    selection.model_dump(mode="json"),
            "verification": verification.model_dump(mode="json"),
            "editorial":    editorial.model_dump(mode="json"),
            "tone":         tone.model_dump(mode="json"),
            "draft":        draft.model_dump(mode="json"),
            "post":         post.model_dump(mode="json"),
            "validation":   validation.model_dump(mode="json"),
            "publication":  publication.model_dump(mode="json"),
        },
    }
    (snap / f"{run_id}.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8",
    )

    print(f"\n  snapshot: data/runs/{run_id}.json")
    print("\nPIPELINE PASS")
    return 0


def main() -> None:
    provider = sys.argv[1] if len(sys.argv) > 1 else "ollama"
    model_id = sys.argv[2] if len(sys.argv) > 2 else "gpt-oss:120b"
    topic = sys.argv[3] if len(sys.argv) > 3 else None
    sys.exit(run_pipeline(provider, model_id, topic=topic))


if __name__ == "__main__":
    main()



