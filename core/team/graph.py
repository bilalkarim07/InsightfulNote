"""The NewsRoom team graph.

This is not a pipeline. Every node can:
  - produce output
  - emit messages
  - route to a different node (loop back, escalate, or continue)
  - decide the run is done
"""
from __future__ import annotations
import re

import json
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import END, StateGraph

from schemas.common import new_run_id  # not used here, for callers
from schemas.discovery import DiscoveryResult
from schemas.source_intelligence import SourceIntelligenceResult
from schemas.research import ResearchResult, Evidence, Claim
from schemas.research_claims import ResearchClaims
from schemas.selection import SelectionDecision
from schemas.verification import VerificationResult, VerificationStatus
from schemas.editorial import EditorialDecision
from schemas.tone import ToneDecision
from schemas.writing import WriterDraft
from schemas.platform import PlatformPost
from schemas.validation import ValidationResult, ValidationState
from schemas.publishing import PublishResult

from core.llm.factory import get_chat_model
from core.llm.persistence import load_capabilities
from core.llm.providers import (
    OllamaProvider, GroqProvider, OpenRouterProvider, GeminiProvider, ProviderFactory,
)
from core.llm.registry import build_default_registry
from core.tools.search import search_web
from core.tools.compact import (
    compact_search_results, render_evidence_block, total_chars,
)
from core.tools.publishing import publish_threads
from core.observability.runlog import stage
from core.team.state import (
    MAX_EDITORIAL_FIXES, MAX_RESEARCH_LOOPS, MAX_WRITER_RETRIES,
    TeamState, msg,
)
from scripts.llm._structured import invoke_structured, StructuredOutputError

ProviderFactory.register(OllamaProvider(cloud=True))
ProviderFactory.register(GroqProvider())
ProviderFactory.register(OpenRouterProvider())
ProviderFactory.register(GeminiProvider())


# ── helpers ─────────────────────────────────────────────────────

def _model(state: TeamState):
    registry = build_default_registry()
    load_capabilities(registry)
    entry = registry.get(state["provider"], state["model_id"])
    if entry is None or not entry.capabilities:
        raise RuntimeError(f"Unknown or unverified model: {state['provider']}/{state['model_id']}")
    return get_chat_model(entry, timeout=180)


def _structured(client, schema, prompt: str, provider: str, context: dict | None = None):
    supports_schema = provider != "ollama"
    try:
        return invoke_structured(
            client, schema, prompt,
            supports_json_schema=supports_schema,
            context=context,
        )
    except StructuredOutputError:
        terse = prompt + "\n\nReturn ONLY the JSON object, no prose."
        return invoke_structured(
            client, schema, terse,
            supports_json_schema=supports_schema,
            context=context,
        )


_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at",
    "for", "with", "by", "is", "are", "was", "were", "be", "been", "being",
    "that", "this", "these", "those", "it", "its", "as", "from", "will",
    "has", "have", "had", "not", "no", "than", "then", "so", "such",
}


def _ngrams(text: str, n: int = 3) -> set[str]:
    words = [w.lower().strip(".,;:!?\"'()[]{}—–-") for w in text.split()]
    words = [w for w in words if w and w not in _STOPWORDS]
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def _verbatim_ok(claim_text: str, quotes: list[str], n: int) -> bool:
    grams = _ngrams(claim_text, n)
    if not grams:
        return False
    return any(grams & _ngrams(q, n) for q in quotes)


def _bump_iteration(state: TeamState, key: str) -> int:
    it = dict(state.get("iteration") or {})
    it[key] = it.get(key, 0) + 1
    return it[key]


def _trace(node: str, out: TeamState, messages: list[dict]) -> TeamState:
    """Helper to merge node output back into the state."""
    merged = dict(out)
    merged["current_node"] = node
    merged["messages"] = messages
    return merged  # type: ignore[return-value]



def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

def _escalated(state: TeamState) -> bool:
    """Return True if any prior node marked the run as ESCALATE."""
    return state.get("outcome") == "ESCALATE"


def _safe_node(fn):
    """Wrap a graph node with observability + exception safety.

    Every node execution writes one row to data/pipeline_log.jsonl with
    run_id, agent, provider, model_id, latency_ms, and status (PASS/FAILED).
    Exceptions become ESCALATE — a broken LLM response never crashes the graph.
    """
    def wrapped(state: TeamState) -> TeamState:
        node_name = fn.__name__.replace("node_", "")
        run_id = state.get("run_id", "unknown")
        provider = state.get("provider", "")
        model_id = state.get("model_id", "")
        try:
            with stage(run_id=run_id, agent=node_name,
                       provider=provider, model_id=model_id):
                return fn(state)
        except Exception as exc:  # noqa: BLE001
            import traceback
            print(f"  [{node_name}] FAILED: {type(exc).__name__}: {str(exc)[:300]}")
            print(f"  [{node_name}] traceback:")
            for line in traceback.format_exc().splitlines()[-6:]:
                print(f"    {line}")
            return _trace(node_name, state, [
                msg(node_name, "all", "BLOCKER",
                    f"{type(exc).__name__}: {str(exc)[:300]}"),
            ]) | {
                "outcome": "ESCALATE",
                "blockers": (state.get("blockers") or [])
                            + [f"{node_name}: {exc}"],
            }
    wrapped.__name__ = fn.__name__
    return wrapped


# ── nodes ───────────────────────────────────────────────────────


def node_discovery(state: TeamState) -> TeamState:
    # Short-circuit: upstream failure → skip this node.
    if state.get("outcome") == "ESCALATE":
        return state
    client = _model(state)
    seed = state["seed"]
    run_id, story_id = state["run_id"], state["story_id"]
    prompt = (
        f'Produce a DiscoveryResult with run_id="{run_id}" and one CandidateStory '
        f'with story_id="{story_id}", title="{seed["title"]}", '
        f'summary="{seed["summary"]}", topic="{seed["topic"]}", '
        f'is_breaking=true, independent_source_count=2. '
        f'Return JSON only with shape: {{"run_id": "{run_id}", "candidates": '
        f'[{{"story_id": "{story_id}", "title": "...", "summary": "...", '
        f'"topic": "...", "source_ids": [], "is_breaking": true, '
        f'"is_emerging": false, "independent_source_count": 2, '
        f'"first_seen_at": null, "discovery_rationale": ""}}], "notes": ""}}'
    )
    result, _ = _structured(client, DiscoveryResult, prompt, state["provider"])
    return _trace("discovery", state, [
        msg("discovery", "all", "HANDOFF",
            f"Selected story: {seed['title']!r}"),
    ]) | {"discovery": result.model_dump(mode="json")}


def node_source_intel(state: TeamState) -> TeamState:
    # Short-circuit: upstream failure → skip this node.
    if state.get("outcome") == "ESCALATE":
        return state
    client = _model(state)
    run_id, story_id = state["run_id"], state["story_id"]
    prompt = (
        f'Produce a SourceIntelligenceResult with run_id="{run_id}", '
        f'story_id="{story_id}", one SourceAssessment with story_id="{story_id}", '
        f'source_id="s1", source_type="SECONDARY", authority="aggregated search", '
        f'independence="to be confirmed". Return JSON only.'
    )
    result, _ = _structured(client, SourceIntelligenceResult, prompt, state["provider"])
    return _trace("source_intel", state, [
        msg("source_intel", "research", "HANDOFF",
            "Sources assessed. Proceed to evidence collection."),
    ]) | {"source_intel": result.model_dump(mode="json")}


def node_research(state: TeamState) -> TeamState:
    """Research — deterministic evidence, LLM-only-for-claims."""
    # Short-circuit: upstream failure → skip this node.
    if state.get("outcome") == "ESCALATE":
        return state
    client = _model(state)
    run_id, story_id = state["run_id"], state["story_id"]
    seed = state.get("seed") or {}
    topic = (seed.get("title") or state.get("topic") or "").strip()
    questions = state.get("research_questions") or []
    it = _bump_iteration(state, "research")
    print(f"  [research] attempt {it} for topic={topic!r}")

    # ── Step 1: deterministic search + compaction ──
    queries = [topic] + (questions[:1] if questions else [])
    all_items: list[dict] = []
    for q in queries:
        try:
            raw = search_web.invoke({"query": q})
        except Exception as exc:  # noqa: BLE001
            print(f"  [research] search error for {q!r}: {exc}")
            continue
        items = compact_search_results(raw, max_items=4)
        for item in items:
            item["evidence_id"] = f"ev_{len(all_items) + 1}"
            item["source_id"] = f"s{len(all_items) + 1}"
            all_items.append(item)
        if len(all_items) >= 5:
            break

    # Dedupe across queries by URL.
    deduped: list[dict] = []
    seen_urls: set[str] = set()
    for item in all_items:
        url = item.get("url") or ""
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        deduped.append(item)
    all_items = deduped[:5]

    if not all_items:
        return _trace("research", state, [
            msg("research", "all", "BLOCKER",
                f"No usable evidence for topic {topic!r}.", iteration=it),
        ]) | {
            "research": ResearchResult(
                run_id=run_id, story_id=story_id, notes="no evidence",
            ).model_dump(mode="json"),
            "iteration": {**(state.get("iteration") or {}), "research": it},
        }

    print(f"  [research] compacted to {len(all_items)} evidence item(s), "
          f"{total_chars(all_items)} chars")

    # ── Step 2: build Evidence objects in code (deterministic) ──
    evidence_objects: list[Evidence] = []
    for item in all_items:
        evidence_objects.append(Evidence(
            evidence_id=item["evidence_id"],
            source_id=item["source_id"],
            quote=item["quote"],
            url=item.get("url"),
        ))

    # ── Step 3: ask the LLM only for claims ──
    evidence_block = render_evidence_block(all_items)
    allowed_ids = [e.evidence_id for e in evidence_objects]
    prompt = f"""
You are the Research Agent. Extract 1-3 FACTUAL claims supported by the
evidence below.

run_id = "{run_id}"
story_id = "{story_id}"
topic = "{topic}"

Evidence ({len(all_items)} items). Available evidence_ids: {allowed_ids}
{evidence_block}

Output JSON with this EXACT shape. DO NOT include an evidence array — the
system already has the evidence and will attach it for you.

{{
  "claims": [
    {{
      "claim_id": "claim_1",
      "text": "one factual sentence, <= 200 chars, drawn from the evidence",
      "evidence_ids": ["ev_1"],
      "attribution": "",
      "uncertainty": "",
      "is_forecast": false,
      "is_allegation": false,
      "is_opinion": false
    }}
  ],
  "notes": ""
}}

CRITICAL RULES:
- Output claims and notes ONLY. NO evidence array.
- Use field name "text" (NOT "claim
        + "VERBATIM RULE (critical): Each claim's text MUST share at"
        + " least THREE consecutive content words with its evidence quote."
        + " If you cannot satisfy this, DO NOT include that claim." + chr(10)").
- Use field name "evidence_ids" (NOT "sources").
- Each claim MUST cite at least one evidence_id from this exact list: {allowed_ids}
- Text in the claim must be directly supported by the evidence block above.
- If the evidence is not about {topic!r}, return claims=[] and explain in notes.
- Keep it under 3 claims total.

Return JSON only, no prose, no markdown fences.
""".strip()

    claims_result, method = _structured(
        client, ResearchClaims, prompt, state["provider"],
    )
    print(f"  [research] structured output via {method}: "
          f"{len(claims_result.claims)} claim(s)")

    # ── Step 4: drop any claims referencing unknown evidence_ids ──
    valid_claims: list[Claim] = []
    for c in claims_result.claims:
        good_ids = [eid for eid in c.evidence_ids if eid in allowed_ids]
        if not good_ids:
            print(f"  [research] dropping {c.claim_id}: cites no known evidence")
            continue
        c.evidence_ids = good_ids
        valid_claims.append(c)

    # ── Step 5: assemble the final ResearchResult ──
    # Filter out claims that fail the verbatim-overlap check BEFORE
    # assembly. Partial claims shouldn't block a valid story.
    kept_claims = []
    dropped_claims = []
    for c in valid_claims:
        quotes_for_c = [
            e.quote for e in evidence_objects
            if e.evidence_id in c.evidence_ids
        ]
        n_gram = 2 if c.is_forecast else 3
        if quotes_for_c and _verbatim_ok(c.text, quotes_for_c, n_gram):
            kept_claims.append(c)
        else:
            dropped_claims.append(c.claim_id)
    if dropped_claims:
        print("  [research] dropped claims without verbatim support: "
              + str(dropped_claims))
    valid_claims = kept_claims
    result = ResearchResult(
        run_id=run_id,
        story_id=story_id,
        claims=valid_claims,
        evidence=evidence_objects,
        notes=claims_result.notes,
    )
    print(f"  [research] assembled: {len(result.claims)} claims, "
          f"{len(result.evidence)} evidence")

    return _trace("research", state, [
        msg("research", "verification", "HANDOFF",
            f"Produced {len(result.claims)} claims with {len(result.evidence)} evidence items.",
            iteration=it),
    ]) | {
        "research": result.model_dump(mode="json"),
        "research_questions": [],
        "iteration": {**(state.get("iteration") or {}), "research": it},
    }


def node_research_gate(state: TeamState) -> TeamState:
    """Deterministic. Blocks if research produced no claims or verbatim fails."""
    # Short-circuit: upstream failure → skip this node.
    if state.get("outcome") == "ESCALATE":
        return state
    research = ResearchResult.model_validate(state["research"])
    evidence_by_id = {e.evidence_id: e.quote for e in research.evidence}
    gate_errors: list[str] = []
    for c in research.claims:
        quotes = [evidence_by_id[eid] for eid in c.evidence_ids if eid in evidence_by_id]
        if not quotes:
            gate_errors.append(f"claim {c.claim_id} cites no known evidence")
            continue
        n = 2 if c.is_forecast else 3
        if not _verbatim_ok(c.text, quotes, n):
            gate_errors.append(f"claim {c.claim_id}: no verbatim support")

    if not research.claims:
        return _trace("research_gate", state, [
            msg("research_gate", "all", "BLOCKER", "Research produced no claims."),
        ]) | {
            "outcome": "INSUFFICIENT_EVIDENCE",
            "blockers": gate_errors + ["no claims produced"],
        }

    if gate_errors:
        return _trace("research_gate", state, [
            msg("research_gate", "all", "BLOCKER", "; ".join(gate_errors)),
        ]) | {
            "outcome": "INSUFFICIENT_EVIDENCE",
            "blockers": gate_errors,
        }

    return _trace("research_gate", state, [
        msg("research_gate", "verification", "HANDOFF", "All claims have verbatim support."),
    ])


def node_verification(state: TeamState) -> TeamState:
    """Verification - judges claims against the evidence they cite."""
    # Short-circuit: upstream failure → skip this node.
    if state.get("outcome") == "ESCALATE":
        return state
    client = _model(state)
    run_id, story_id = state["run_id"], state["story_id"]
    research = ResearchResult.model_validate(state["research"])

    evidence_by_id = {e.evidence_id: e for e in research.evidence}
    blocks = []
    for c in research.claims:
        quotes = []
        for eid in c.evidence_ids:
            ev = evidence_by_id.get(eid)
            if ev is not None:
                quotes.append("      [" + eid + "] " + ev.quote)
        if quotes:
            quotes_str = chr(10).join(quotes)
        else:
            quotes_str = "      (no evidence attached)"
        blocks.append(
            "  - claim_id: " + c.claim_id + chr(10)
            + "    text: " + repr(c.text) + chr(10)
            + "    is_forecast: " + str(c.is_forecast) + chr(10)
            + "    attribution: " + repr(c.attribution) + chr(10)
            + "    evidence:" + chr(10) + quotes_str
        )
    claims_block = chr(10).join(blocks)

    prompt = (
        "You are the Verification Agent. Judge each claim against its evidence." + chr(10) + chr(10)
        + "run_id = " + repr(run_id) + chr(10)
        + "story_id = " + repr(story_id) + chr(10) + chr(10)
        + "Claims and evidence:" + chr(10) + claims_block + chr(10) + chr(10)
        + "Rules:" + chr(10)
        + "- SUPPORTED: evidence supports the claim." + chr(10)
        + "- SUPPORTED_AS_ATTRIBUTED: forecast with matching evidence." + chr(10)
        + "- UNSUPPORTED: unrelated evidence." + chr(10) + chr(10)
        + "Return JSON matching VerificationResult exactly, one per claim."
    )

    result, _ = _structured(
        client, VerificationResult, prompt, state["provider"],
        context={"run_id": run_id, "story_id": story_id},
    )

    # Deterministic backfill: every verification must cite the claim's
    # evidence. If the LLM left evidence_ids empty, copy from the claim it
    # judged so the published artefact remains traceable to sources.
    claims_by_id = {c.claim_id: c for c in research.claims}
    for _v in result.verifications:
        if _v.evidence_ids and all(eid for eid in _v.evidence_ids):
            continue
        _claim = claims_by_id.get(_v.claim_id)
        if _claim and _claim.evidence_ids:
            _v.evidence_ids = list(_claim.evidence_ids)

    print("  [verification] " + str(len(result.verifications)) + " verification(s)")

    unsupported = [
        v.claim_id for v in result.verifications
        if v.status in (VerificationStatus.UNSUPPORTED,
                        VerificationStatus.CONTRADICTED,
                        VerificationStatus.UNCERTAIN)
    ]
    supported_count = len(result.verifications) - len(unsupported)

    messages = [
        msg("verification", "editorial", "HANDOFF",
            str(supported_count) + " supported, " + str(len(unsupported)) + " unsupported."),
    ]
    out = {"verification": result.model_dump(mode="json")}
    if unsupported:
        out["research_questions"] = [
            "Additional evidence for claim " + cid for cid in unsupported
        ]
        messages.append(msg(
            "verification", "research", "REQUEST",
            "Need more evidence for: " + str(unsupported),
        ))
    return _trace("verification", state, messages) | out


def node_editorial(state: TeamState) -> TeamState:
    """Editorial — decides what the story is actually about."""
    if state.get("outcome") == "ESCALATE":
        return state
    client = _model(state)
    run_id, story_id = state["run_id"], state["story_id"]
    research = ResearchResult.model_validate(state["research"])
    verification = VerificationResult.model_validate(state["verification"])

    allowed = [
        v.claim_id for v in verification.verifications
        if v.status in (VerificationStatus.SUPPORTED,
                        VerificationStatus.SUPPORTED_AS_ATTRIBUTED)
    ]
    allowed_claims = [c for c in research.claims if c.claim_id in allowed]
    claims_block = chr(10).join(
        "  [" + c.claim_id + "] " + c.text
        + (" (FORECAST - attribution: " + c.attribution + ")" if c.is_forecast else "")
        for c in allowed_claims
    )
    fixes = state.get("editorial_fixes") or []
    fixes_block = chr(10).join("- " + f for f in fixes) if fixes else "(none)"

    prompt = (
        "You are the Editorial Agent. Decide what this story is about." + chr(10) + chr(10)
        + "run_id = " + repr(run_id) + chr(10)
        + "story_id = " + repr(story_id) + chr(10) + chr(10)
        + "Verified claims you may use:" + chr(10)
        + claims_block + chr(10) + chr(10)
        + "Writer feedback to address (if any): " + fixes_block + chr(10) + chr(10)
        + "Your job:" + chr(10)
        + "1. Write central_event as ONE sentence stating the central fact." + chr(10)
        + "2. List must_include — the specific facts that MUST appear." + chr(10)
        + "3. List do_not_include — what must NOT appear (e.g. unsupported speculation)." + chr(10)
        + "4. Write framing — one sentence on the angle a reader should take." + chr(10)
        + "5. Set allowed_claim_ids to the list of claim_ids you approve." + chr(10) + chr(10)
        + "Rules:" + chr(10)
        + "- central_event MUST be non-empty and specific." + chr(10)
        + "- Forecasts stay forecasts. Never mark a forecast as a fact." + chr(10)
        + "- Use only claim_ids from the list above." + chr(10) + chr(10)
        + "Return JSON matching EditorialDecision exactly."
    )

    result, _ = _structured(
        client, EditorialDecision, prompt, state["provider"],
        context={"run_id": run_id, "story_id": story_id},
    )
    print("  [editorial] central_event=" + repr(result.central_event[:80]))
    print("  [editorial] allowed=" + str(result.allowed_claim_ids))

    # Deterministic: central_event must be non-empty.
    if not result.central_event or not result.central_event.strip():
        result.central_event = allowed_claims[0].text if allowed_claims else "(no approved claims)"
        print("  [editorial] central_event empty — substituted")

    return _trace("editorial", state, [
        msg("editorial", "tone", "HANDOFF",
            "Central event: " + result.central_event[:120]),
    ]) | {
        "editorial": result.model_dump(mode="json"),
        "editorial_fixes": [],
    }


def node_tone(state: TeamState) -> TeamState:
    """Tone — chooses presentation tone based on subject sensitivity."""
    if state.get("outcome") == "ESCALATE":
        return state
    client = _model(state)
    run_id, story_id = state["run_id"], state["story_id"]

    from core.team.tone_bank import TONES, allowed_tones, description_for

    editorial = EditorialDecision.model_validate(state["editorial"])
    research = ResearchResult.model_validate(state["research"])

    # Simple sensitivity heuristic — expands later.
    subject = (editorial.central_event or "").lower()
    sensitive_keywords = ("died", "death", "war", "disaster", "killed",
                          "shooting", "attack", "victim", "election", "referendum")
    sensitive = any(k in subject for k in sensitive_keywords)

    choices = allowed_tones(subject, sensitive)
    tone_menu = chr(10).join(
        "- " + t + ": " + description_for(t) for t in choices
    )

    claims_summary = chr(10).join(
        "- " + c.text for c in research.claims[:4]
    )

    prompt = (
        "You are the Tone Agent. Choose the presentation tone for a news post." + chr(10) + chr(10)
        + "run_id = " + repr(run_id) + chr(10)
        + "story_id = " + repr(story_id) + chr(10) + chr(10)
        + "Central event: " + repr(editorial.central_event) + chr(10) + chr(10)
        + "Story claims:" + chr(10) + claims_summary + chr(10) + chr(10)
        + "Sensitive: " + str(sensitive) + chr(10) + chr(10)
        + "Allowed tones:" + chr(10) + tone_menu + chr(10) + chr(10)
        + "Choose ONE. Provide a one-sentence rationale." + chr(10)
        + "Return JSON matching ToneDecision exactly."
    )

    result, _ = _structured(
        client, ToneDecision, prompt, state["provider"],
        context={"run_id": run_id, "story_id": story_id},
    )
    print("  [tone] " + result.tone.value + " — " + result.rationale[:80])

    return _trace("tone", state, [
        msg("tone", "writer", "INFO", "Tone: " + result.tone.value),
    ]) | {"tone": result.model_dump(mode="json")}


def node_writer(state: TeamState) -> TeamState:
    """Writer — writes using ONLY approved claims, in the chosen tone."""
    if state.get("outcome") == "ESCALATE":
        return state

    # Track writer retries so the loop is bounded.
    _it = dict(state.get("iteration") or {})
    _it["writer"] = _it.get("writer", 0) + 1
    state = {**state, "iteration": _it}
    client = _model(state)
    run_id, story_id = state["run_id"], state["story_id"]
    research = ResearchResult.model_validate(state["research"])
    editorial = EditorialDecision.model_validate(state["editorial"])
    tone_decision = ToneDecision.model_validate(state["tone"])

    from core.team.tone_bank import example_for, description_for
    tone_example = example_for(tone_decision.tone.value)
    tone_desc = description_for(tone_decision.tone.value)

    approved = [c for c in research.claims if c.claim_id in editorial.allowed_claim_ids]
    if not approved:
        return _trace("writer", state, [
            msg("writer", "editorial", "BLOCKER",
                "No approved claims — need more verified evidence."),
        ]) | {
            "draft": WriterDraft(
                run_id=run_id, story_id=story_id,
                headline="", body="", claim_ids=[], tone=tone_decision.tone,
            ).model_dump(mode="json"),
            "editorial_fixes": ["no approved claims"],
        }

    approved_block = chr(10).join(
        "- " + c.claim_id + ": " + c.text
        + (" [FORECAST — attribute to: " + c.attribution + "]" if c.is_forecast else "")
        for c in approved
    )
    must_include = chr(10).join("- " + m for m in editorial.must_include) if editorial.must_include else "(none)"
    do_not = chr(10).join("- " + m for m in editorial.do_not_include) if editorial.do_not_include else "(none)"

    prompt = (
        "You are the Writer. Produce a WriterDraft in the specified tone." + chr(10) + chr(10)
        + "run_id = " + repr(run_id) + chr(10)
        + "story_id = " + repr(story_id) + chr(10) + chr(10)
        + "Central event: " + repr(editorial.central_event) + chr(10) + chr(10)
        + "Approved claims (USE ONLY THESE):" + chr(10)
        + approved_block + chr(10) + chr(10)
        + "Must include:" + chr(10) + must_include + chr(10) + chr(10)
        + "Do NOT include:" + chr(10) + do_not + chr(10) + chr(10)
        + "Tone: " + tone_decision.tone.value + chr(10)
        + "Tone description: " + tone_desc + chr(10)
        + "Tone STYLE example (mimic style, not content):" + chr(10)
        + tone_example + chr(10) + chr(10)
        + "Rules:" + chr(10)
        + "- Use ONLY the approved claims above." + chr(10)
        + "- For forecasts, PRESERVE attribution." + chr(10)
        + "- claim_ids must list every claim_id you used." + chr(10)
        + "- Do NOT use the field name 'text'. Use 'body'." + chr(10) + chr(10)
        + "Return JSON EXACTLY matching this shape:" + chr(10)
        + "{" + chr(10)
        + "  \"run_id\": " + repr(run_id) + "," + chr(10)
        + "  \"story_id\": " + repr(story_id) + "," + chr(10)
        + "  \"headline\": \"short headline (30-100 chars)\", " + chr(10)
        + "  \"body\": \"the post body\"," + chr(10)
        + "  \"source_reference\": \"\"," + chr(10)
        + "  \"claim_ids\": [<claim_id strings>]," + chr(10)
        + "  \"tone\": " + repr(tone_decision.tone.value) + "," + chr(10)
        + "  \"warnings\": []" + chr(10)
        + "}" + chr(10)
        + "No other fields. No markdown. JSON only."
    )

    result, _ = _structured(
        client, WriterDraft, prompt, state["provider"],
        context={"run_id": run_id, "story_id": story_id},
    )

    # Deterministic fallback: if the LLM omitted headline, derive it from the
    # first sentence of the body. Never crash the pipeline over a missing field.
    if not (result.headline or "").strip():
        body = (result.body or "").strip()
        if body:
            first = re.split(r"(?<=[.!?])\s+", body, maxsplit=1)[0].strip()
            if len(first) > 120:
                first = first[:117].rsplit(" ", 1)[0] + "..."
            result.headline = first
            print(f"  [writer] headline derived from body: {first[:80]!r}")
        else:
            print("  [writer] WARNING: no body and no headline produced")

    print("  [writer] " + str(len(result.body)) + " chars, " + str(len(result.claim_ids)) + " claims, headline=" + (result.headline[:40] if result.headline else "<empty>"))

    return _trace("writer", state, [
        msg("writer", "platform_adapter", "HANDOFF",
            "Draft ready (" + str(len(result.body)) + " chars)"),
    ]) | {"draft": result.model_dump(mode="json")}


def node_platform_adapter(state: TeamState) -> TeamState:
    """Platform Adapter - produces a 2-3 line Threads post."""
    import os
    client = _model(state)
    run_id, story_id = state["run_id"], state["story_id"]
    draft = WriterDraft.model_validate(state["draft"])

    max_chars = int(os.environ.get("THREADS_MAX_CHARS", "280"))

    headline = (draft.headline or "").strip()
    body = (draft.body or "").strip()

    prompt = (
        "You are the Platform Adapter for Threads. Compress the draft"
        + chr(10)
        + "into a single cohesive post of 2-3 short sentences." + chr(10) + chr(10)
        + "run_id = " + repr(run_id) + chr(10)
        + "story_id = " + repr(story_id) + chr(10) + chr(10)
        + "Draft headline: " + repr(headline) + chr(10)
        + "Draft body: " + repr(body) + chr(10) + chr(10)
        + "Rules:" + chr(10)
        + "- Target 200-280 characters TOTAL. Hard max: " + str(max_chars) + "." + chr(10)
        + "- 2-3 short sentences. No headline line. No bullet lists." + chr(10)
        + "- Lead with the most newsworthy fact." + chr(10)
        + "- Preserve every number, date, name, and attribution exactly." + chr(10)
        + "- NEVER change \"analysts expect\" to \"will\"." + chr(10)
        + "- Drop context that is not essential to the central fact." + chr(10)
        + "- Do NOT invent facts. Do NOT add hashtags unless the draft had them."
        + chr(10) + chr(10)
        + "Return JSON matching PlatformPost exactly."
    )

    result, _ = _structured(
        client, PlatformPost, prompt, state["provider"],
        context={"run_id": run_id, "story_id": story_id},
    )

    # ── Deterministic traceability ──
    if not result.claim_ids:
        result.claim_ids = list(draft.claim_ids)
    else:
        for cid in draft.claim_ids:
            if cid not in result.claim_ids:
                result.claim_ids.append(cid)
    if not result.source_reference:
        result.source_reference = draft.source_reference

    # ── Deterministic compression if over the ceiling ──
    text = result.text.strip()
    if len(text) > max_chars:
        try:
            from core.tools.compress import compress_to_limit
            compressed = compress_to_limit(text, limit=max_chars)
            print("  [platform_adapter] compressed " + str(len(text))
                  + " -> " + str(len(compressed)) + " chars")
            text = compressed
        except Exception as exc:
            # Fallback: truncate on word boundary.
            print("  [platform_adapter] compressor failed: " + type(exc).__name__)
            text = text[:max_chars - 1].rsplit(" ", 1)[0] + chr(8230)

    result.text = text
    result.char_count = len(text)

    return _trace("platform_adapter", state, [
        msg("platform_adapter", "validation", "HANDOFF",
            "Post adapted (" + str(result.char_count) + " chars)"),
    ]) | {"post": result.model_dump(mode="json")}


def node_validation(state: TeamState) -> TeamState:
    """Deterministic. Can route back to writer or editorial, or forward to publisher."""
    if state.get("outcome") == "ESCALATE":
        return state
    post = PlatformPost.model_validate(state["post"])
    draft = WriterDraft.model_validate(state["draft"])
    editorial = EditorialDecision.model_validate(state["editorial"])
    research = ResearchResult.model_validate(state["research"])
    seed = state["seed"]

    errors: list[str] = []
    if not post.text.strip():
        errors.append("empty post text")
    for cid in post.claim_ids:
        if cid not in editorial.allowed_claim_ids:
            errors.append(f"post references unapproved claim: {cid}")
    for cid in draft.claim_ids:
        if cid not in editorial.allowed_claim_ids:
            errors.append(f"draft references unapproved claim: {cid}")

    # Forecast attribution survival.
    for c in research.claims:
        if not c.is_forecast or c.claim_id not in editorial.allowed_claim_ids:
            continue
        attr = (c.attribution or "").strip()
        if not attr:
            continue
        anchor = max(attr.split(), key=len).strip(".,;:")
        if anchor and anchor.lower() not in post.text.lower():
            errors.append(f"forecast {c.claim_id} lost attribution: {attr!r}")

    # Seed subject survival.
    tokens = [w.lower().strip(".,;:!?\"'()[]{}—–-")
              for w in f"{seed['title']} {seed['summary']}".split()
              if w.lower() not in _STOPWORDS and len(w) > 2]
    if tokens and not any(tok in post.text.lower() for tok in tokens):
        errors.append(f"post lost seed subject: {seed['title']!r}")

    import os as _os
    _max = int(_os.environ.get("THREADS_MAX_CHARS", "280"))
    if len(post.text) > _max:
        errors.append(f"post exceeds 500 chars: {len(post.text)}")

    state_out: ValidationResult = ValidationResult(
        run_id=post.run_id, story_id=post.story_id,
        state=ValidationState.PASS if not errors else ValidationState.BLOCK,
        errors=errors,
    )
    messages = [msg("validation", "publisher" if not errors else "writer",
                    "HANDOFF" if not errors else "FEEDBACK",
                    "OK" if not errors else "; ".join(errors))]
    return _trace("validation", state, messages) | {
        "validation": state_out.model_dump(mode="json"),
    }


def node_quota_gate(state: TeamState) -> TeamState:
    """Deterministic: gate publishing on daily quota + active hours."""
    from core.team import quota as quota_mod

    allowed, reason, _state = quota_mod.can_publish()
    if allowed:
        return _trace("quota_gate", state, [
            msg("quota_gate", "publisher", "HANDOFF", "quota ok"),
        ])

    # Not allowed — record deferral and return early.
    quota_mod.record_deferral()
    return _trace("quota_gate", state, [
        msg("quota_gate", "all", "INFO", "deferred: " + reason),
    ]) | {
        "outcome": "DEFERRED_QUOTA",
        "blockers": (state.get("blockers") or []) + ["quota: " + reason],
    }

def node_publisher(state: TeamState) -> TeamState:
    """Publish to Threads via ThreadsAPI. Never refreshes tokens."""
    import os
    post = PlatformPost.model_validate(state["post"])
    story_id = state.get("story_id", "")
    run_id = state.get("run_id", "")

    live = os.environ.get("NEWSROOM_LIVE", "").strip().lower() in ("1", "true", "yes")
    dry_run = not live

    # ── Duplicate check (fail-closed) ──
    if live and story_id:
        try:
            from core.tools.database.stories import find_duplicate_publication
            existing = find_duplicate_publication(story_id, platform="threads")
            if existing:
                pub = PublishResult(
                    run_id=run_id, story_id=story_id,
                    platform="threads", status="DUPLICATE_SKIPPED", url=None,
                )
                return _trace("publisher", state, [
                    msg("publisher", "all", "DONE",
                        "Duplicate publication — skipping."),
                ]) | {
                    "publication": pub.model_dump(mode="json"),
                    "outcome": "PASS",
                }
        except Exception as exc:
            print("  [publisher] duplicate check failed: " + type(exc).__name__)
            pub = PublishResult(
                run_id=run_id, story_id=story_id,
                platform="threads",
                status="BLOCKED_DUPLICATE_CHECK_UNAVAILABLE",
                url=None, error=str(exc),
            )
            return _trace("publisher", state, [
                msg("publisher", "all", "BLOCKER",
                    "duplicate check unavailable — BLOCKED"),
            ]) | {
                "publication": pub.model_dump(mode="json"),
                "outcome": "BLOCKED",
            }

    # ── Publish ──
    from core.tools.publishing import publish_threads
    result = publish_threads(post.text, dry_run=dry_run)
    status = result.get("status", "FAILED")
    external_id = result.get("external_id")
    url = result.get("url")
    error = result.get("error")

    pub = PublishResult(
        run_id=run_id, story_id=story_id,
        platform="threads", status=status,
        external_id=external_id, url=url, error=error,
    )

    # ── Persist publication record ──
    if story_id:
        try:
            from core.tools.database import stories as _db
            _db.save_publication_result(story_id, {
                "platform": "threads",
                "status": status,
                "content": post.text,
                "external_post_id": external_id,
                "published_at": None if dry_run else _now_iso(),
                "metadata": {"run_id": run_id, "error": error},
            })
            if status == "PUBLISHED":
                _db.update_story_status(story_id, "published")
        except Exception as exc:
            print("  [publisher] persist failed: " + type(exc).__name__ + ": " + str(exc))

    # ── Update local quota (no-op in production) ──
    if status == "PUBLISHED":
        try:
            from core.team import quota as quota_mod
            quota_mod.record_publication()
        except Exception:
            pass

    return _trace("publisher", state, [
        msg("publisher", "all", "DONE",
            "Publication: " + status + " (live=" + str(live) + ")"),
    ]) | {
        "publication": pub.model_dump(mode="json"),
        "outcome": "PASS" if status in ("PUBLISHED", "SKIPPED_DRY_RUN") else "BLOCKED",
    }


def node_escalate(state: TeamState) -> TeamState:
    return _trace("escalate", state, [
        msg("escalate", "all", "BLOCKER",
            f"Escalated. Blockers: {state.get('blockers', [])}"),
    ]) | {"outcome": "ESCALATE"}


# ── routing ──────────────────────────────────────────────────────

def route_after_research_gate(state: TeamState) -> Literal["verification", "escalate", "__end__"]:
    if state.get("outcome") == "ESCALATE":
        return "escalate"
    if state.get("outcome") == "INSUFFICIENT_EVIDENCE":
        return "__end__"
    return "verification"


def route_after_verification(state: TeamState) -> Literal["editorial_and_tone", "research", "escalate"]:
    """If verification flagged unsupported claims, loop back to research (bounded)."""
    it = (state.get("iteration") or {}).get("research", 0)
    if state.get("research_questions") and it < MAX_RESEARCH_LOOPS:
        return "research"
    if state.get("research_questions"):
        # loop limit reached — escalate instead of looping forever
        return "escalate"
    return "editorial_and_tone"


def route_after_validation(state: TeamState) -> Literal["publisher", "writer", "editorial", "escalate"]:
    # Short-circuit: any upstream node crashed → escalate, never crash here.
    if state.get("outcome") == "ESCALATE":
        return "escalate"
    validation = state.get("validation")
    if not validation:
        # A node failed before validation ran. Escalate cleanly.
        return "escalate"
    if validation["state"] == "PASS":
        return "publisher"

    writer_retries = (state.get("iteration") or {}).get("writer", 0)
    editorial_fixes = (state.get("iteration") or {}).get("editorial_fix", 0)

    errors = validation.get("errors") or []
    needs_editorial = any("unapproved" in e for e in errors)
    needs_writer = any(
        "attribution" in e or "seed subject" in e or "empty post" in e
        for e in errors
    )

    if needs_editorial and editorial_fixes < MAX_EDITORIAL_FIXES:
        return "editorial"
    if needs_writer and writer_retries < MAX_WRITER_RETRIES:
        return "writer"
    return "escalate"


# ── graph construction ───────────────────────────────────────────

def build_graph() -> StateGraph:
    g = StateGraph(TeamState)

    g.add_node("discovery", _safe_node(node_discovery))
    g.add_node("source_intel", _safe_node(node_source_intel))
    g.add_node("research", _safe_node(node_research))
    g.add_node("research_gate", _safe_node(node_research_gate))
    g.add_node("verification", _safe_node(node_verification))

    # Parallel branch — editorial and tone both depend only on verification.
    g.add_node("editorial", _safe_node(node_editorial))
    g.add_node("tone", _safe_node(node_tone))
    g.add_node("writer", _safe_node(node_writer))

    g.add_node("platform_adapter", _safe_node(node_platform_adapter))
    g.add_node("validation", _safe_node(node_validation))
    g.add_node("quota_gate", _safe_node(node_quota_gate))
    g.add_node("publisher", _safe_node(node_publisher))
    g.add_node("escalate", _safe_node(node_escalate))

    g.set_entry_point("discovery")

    g.add_edge("discovery", "source_intel")
    g.add_edge("source_intel", "research")
    g.add_edge("research", "research_gate")

    g.add_conditional_edges("research_gate", route_after_research_gate, {
        "verification": "verification",
        "escalate": "escalate",
        "__end__": END,
    })

    g.add_conditional_edges("verification", route_after_verification, {
        "editorial_and_tone": "editorial",  # editorial and tone both fan out from here
        "research": "research",
        "escalate": "escalate",
    })

    # Fan-out from editorial → tone runs in parallel.
    g.add_edge("editorial", "tone")
    # Fan-in to writer — writer waits for both editorial and tone.
    g.add_edge("tone", "writer")

    g.add_edge("writer", "platform_adapter")
    g.add_edge("platform_adapter", "validation")

    g.add_conditional_edges("validation", route_after_validation, {
        "publisher": "quota_gate",
        "writer": "writer",
        "editorial": "editorial",
        "escalate": "escalate",
    })

    g.add_edge("quota_gate", "publisher")
    g.add_edge("publisher", END)
    g.add_edge("escalate", END)

    return g


def compile_graph():
    return build_graph().compile()


# ── runner ────────────────────────────────────────────────────────

def run_team(
    provider: str, model_id: str,
    story_id: str | None = None,
    mode: str = "synthetic",
    topic: str | None = None,
    dry_run: bool = True,
) -> int:
    from core.team.state import new_state
    run_id = f"run_{__import__('uuid').uuid4().hex[:12]}"
    # ── Step 7: load real story from Supabase in production modes ──
    production_context = None
    if story_id and mode in ("breaking", "reporting"):
        try:
            from core.tools.database import stories as _db
            _story = _db.get_story(story_id)
            if _story:
                _sources = _db.get_story_sources(story_id)
                production_context = {"story": _story, "sources": _sources}
                topic = _story.get("title", topic) or topic
                print("  [run] loaded real story: " + str(story_id))
                print("        title: " + str(topic)[:80])
                print("        sources: " + str(len(_sources)))
            else:
                print("  [run] WARNING: story not found in DB: " + str(story_id))
        except Exception as _exc:
            print("  [run] context load failed: " + type(_exc).__name__ + ": " + str(_exc))
    state = new_state(run_id=run_id, provider=provider, model_id=model_id, topic=topic)
    if production_context:
        state["production_context"] = production_context
        state["seed"] = {
            "story_id": story_id,
            "title": production_context["story"].get("title", ""),
            "summary": production_context["story"].get("summary") or "",
            "topic": (production_context["story"].get("metadata") or {}).get("topic") or "news",
            "sources": production_context.get("sources", []),
        }
    state["dry_run"] = dry_run
    if story_id:
        state["story_id"] = story_id


    # Production modes must receive a real story_id.
    if mode in ("breaking", "reporting") and not story_id:
        print("  [run] ERROR: PRODUCTION MODE requires a valid story_id")
        print("  [run]        got: " + repr(story_id))
        print("  [run] ABORTING")
        return 2
    print("=" * 70)
    print(f"Team graph run — {provider}/{model_id} (topic={topic!r}, dry_run={dry_run})")
    print(f"  mode={mode!r}  story_id={story_id!r}  dry_run={dry_run}")
    print("=" * 70)

    graph = compile_graph()
    final_state: TeamState = graph.invoke(state)

    # Print the conversation transcript.
    print("\n[team conversation]")
    for m in final_state.get("messages", []):
        kind = m.get("kind")
        src = m.get("from_agent")
        dst = m.get("to_agent")
        content = m.get("content")
        it = m.get("iteration", 0)
        suffix = f" (iter={it})" if it else ""
        print(f"  [{kind:8}] {src} -> {dst}: {content}{suffix}")

    # Print the outcome.
    outcome = final_state.get("outcome", "UNKNOWN")
    print(f"\n[outcome] {outcome}")
    if final_state.get("blockers"):
        print(f"[blockers] {final_state['blockers']}")

    # Snapshot.
    snap = Path("data/runs")
    snap.mkdir(parents=True, exist_ok=True)
    snapshot_payload = {
        "run_id": run_id,
        "outcome": outcome,
        "state": {k: v for k, v in final_state.items() if k != "messages"},
        "messages": final_state.get("messages", []),
    }
    (snap / f"{run_id}.json").write_text(
        json.dumps(snapshot_payload, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\n  snapshot: data/runs/{run_id}.json")

    return 0 if outcome == "PASS" else 1
