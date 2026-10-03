"""The NewsRoom team graph.

This is not a pipeline. Every node can:
  - produce output
  - emit messages
  - route to a different node (loop back, escalate, or continue)
  - decide the run is done
"""
from __future__ import annotations
import logging
import re

import json
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from langgraph.graph import END, StateGraph

from schemas.common import new_run_id  # not used here, for callers
from schemas.discovery import DiscoveryResult
from schemas.source_intelligence import (
    SourceIntelligenceResult,
    SourceType,
    normalize_source_intelligence_payload,
)
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
    MAX_EDITORIAL_FIXES, MAX_WRITER_ATTEMPTS,
    TeamState, msg,
)
from scripts.llm._structured import invoke_structured, StructuredOutputError

ProviderFactory.register(OllamaProvider(cloud=True))
ProviderFactory.register(GroqProvider())
ProviderFactory.register(OpenRouterProvider())
ProviderFactory.register(GeminiProvider())

_LOGGER = logging.getLogger(__name__)


# ── helpers ─────────────────────────────────────────────────────

def _model(state: TeamState):
    registry = build_default_registry()
    load_capabilities(registry)
    entry = registry.get(state["provider"], state["model_id"])
    if entry is None or not entry.capabilities:
        raise RuntimeError(f"Unknown or unverified model: {state['provider']}/{state['model_id']}")
    return get_chat_model(entry, timeout=180)


def _structured(
    client,
    schema,
    prompt: str,
    provider: str,
    context: dict | None = None,
    payload_normalizer=None,
):
    supports_schema = provider != "ollama"
    try:
        return invoke_structured(
            client, schema, prompt,
            supports_json_schema=supports_schema,
            context=context,
            payload_normalizer=payload_normalizer,
        )
    except StructuredOutputError:
        terse = prompt + "\n\nReturn ONLY the JSON object, no prose."
        return invoke_structured(
            client, schema, terse,
            supports_json_schema=supports_schema,
            context=context,
            payload_normalizer=payload_normalizer,
        )


_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at",
    "for", "with", "by", "is", "are", "was", "were", "be", "been", "being",
    "that", "this", "these", "those", "it", "its", "as", "from", "will",
    "has", "have", "had", "not", "no", "than", "then", "so", "such",
}

_CLAIM_STOPWORDS = {
    "a", "an", "the", "of", "to", "in", "on", "at", "for", "with", "by",
    "and", "or", "but", "is", "are", "was", "were", "be", "been", "being",
    "that", "this", "these", "those", "it", "its",
}


def _claim_tokens(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    normalized = set()
    for token in tokens:
        if token in _CLAIM_STOPWORDS:
            continue
        if token == "fell":
            token = "fall"
        elif token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("ed") and len(token) > 4:
            token = token[:-2]
        elif token.endswith("s") and len(token) > 3:
            token = token[:-1]
        normalized.add(token)
    return normalized


def _split_post_sentences(text: str) -> list[str]:
    protected = re.sub(
        r"\b(?:U\.S|U\.K|Mr|Mrs|Ms|Dr|Prof|e\.g|i\.e)\.",
        lambda match: match.group().replace(".", "<prd>"),
        text,
        flags=re.IGNORECASE,
    )
    return [
        sentence.replace("<prd>", ".").strip()
        for sentence in re.split(r"(?<=[.!?])\s+", protected.strip())
        if sentence.strip()
    ]


def _sentence_claim_ids(
    sentence: str,
    claim_ids: list[str],
    claims_by_id: dict[str, Claim],
) -> list[str]:
    sentence_tokens = _claim_tokens(sentence)
    if not sentence_tokens:
        return []
    return [
        claim_id
        for claim_id in claim_ids
        if claim_id in claims_by_id
        and sentence_tokens.issubset(_claim_tokens(claims_by_id[claim_id].text))
    ]


def _verified_source_reference(
    state: TeamState,
    claim_ids: list[str],
) -> str | None:
    """Choose one real source URL cited by a verified claim used in the post."""
    if not claim_ids:
        return None

    research = ResearchResult.model_validate(state["research"])
    verification = VerificationResult.model_validate(state["verification"])
    editorial = EditorialDecision.model_validate(state["editorial"])
    allowed_claim_ids = set(editorial.allowed_claim_ids)
    verifications = {
        item.claim_id: item
        for item in verification.verifications
        if item.status in (
            VerificationStatus.SUPPORTED,
            VerificationStatus.SUPPORTED_AS_ATTRIBUTED,
        )
    }
    claims = {item.claim_id: item for item in research.claims}

    source_ranks = {
        "PRIMARY": 4,
        "OFFICIAL": 4,
        "SECONDARY": 3,
        "AGGREGATOR": 1,
        "UNKNOWN": 0,
        "OPINION": -1,
    }
    source_intel = state.get("source_intel")
    assessments = (
        source_intel.get("assessments", [])
        if isinstance(source_intel, dict)
        else []
    )
    source_ranks_by_id = {
        str(item.get("source_id") or ""): source_ranks.get(
            str(item.get("source_type") or "UNKNOWN").upper(), 0,
        )
        for item in assessments
        if isinstance(item, dict)
    } if isinstance(assessments, list) else {}

    candidates: list[tuple[int, int, str]] = []
    for claim_id in claim_ids:
        claim = claims.get(claim_id)
        verified = verifications.get(claim_id)
        if (
            claim is None
            or verified is None
            or claim_id not in allowed_claim_ids
        ):
            continue
        evidence_ids = set(claim.evidence_ids)
        if verified.evidence_ids:
            evidence_ids &= set(verified.evidence_ids)
        for index, evidence in enumerate(research.evidence):
            if evidence.evidence_id not in evidence_ids or not evidence.url:
                continue
            parsed_url = urlsplit(evidence.url)
            if (
                parsed_url.scheme not in ("http", "https")
                or not parsed_url.hostname
                or _is_placeholder_source_url(evidence.url)
            ):
                continue
            candidates.append((
                source_ranks_by_id.get(evidence.source_id, 0),
                -index,
                evidence.url,
            ))
    return max(candidates)[2] if candidates else None


def _append_source_reference(text: str, source_url: str, limit: int) -> str:
    """Append a verified source link when it fits without breaking the post cap."""
    parsed_url = urlsplit(source_url)
    if (
        parsed_url.scheme not in ("http", "https")
        or not parsed_url.hostname
        or _is_placeholder_source_url(source_url)
        or re.search(r"https?://\S+", text)
    ):
        return text

    suffix = "\n" + source_url
    content_limit = limit - len(suffix)
    if content_limit < 1:
        return text
    content = text.strip()
    if len(content) + len(suffix) > limit:
        return text
    return content + suffix


def _is_verified_source_reference(sentence: str, allowed_urls: set[str]) -> bool:
    match = re.fullmatch(r"(https?://\S+)", sentence)
    if not match:
        return False
    return match.group(1).rstrip(".,;:!?)]}") in allowed_urls


def _story_publication_date(state: TeamState):
    from datetime import date

    source_rows = (
        (state.get("production_context") or {}).get("sources")
        or state.get("sources")
        or []
    )
    values = [row.get("published_at") for row in source_rows]
    values.append((state.get("seed") or {}).get("first_seen_at"))
    dates = []
    for value in values:
        if not value:
            continue
        try:
            dates.append(date.fromisoformat(str(value)[:10]))
        except ValueError:
            continue
    return max(dates) if dates else None


def _date_in_url(url: str):
    from datetime import date

    match = re.search(r"(?<!\d)(20\d{2}-\d{2}-\d{2})(?!\d)", url)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


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


def _is_terminal(state: TeamState) -> bool:
    return state.get("outcome") in ("ESCALATE", "CANDIDATE_REJECTED")


def _reject_candidate(
    state: TeamState,
    node: str,
    reason_code: str,
    detail: str,
) -> TeamState:
    message = f"{reason_code}: {detail}"
    return _trace(node, state, [
        msg(node, "all", "INFO", message),
    ]) | {
        "outcome": "CANDIDATE_REJECTED",
        "candidate_rejection_reason": reason_code,
        "blockers": (state.get("blockers") or []) + [message],
    }



def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _is_placeholder_source_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").strip(".").lower()
    return (
        host in {"example.com", "example.org", "example.net", "localhost"}
        or host.endswith((".example.com", ".example.org", ".example.net", ".invalid", ".test"))
    )


def _documented_source_type(name: str, domain: str) -> str:
    normalized_name = name.strip().casefold().replace(" ", "_")
    normalized_domain = domain.strip().casefold().strip(".")
    if normalized_name in {"google_news", "tavily", "ddgs", "gdelt"}:
        return "AGGREGATOR"
    if normalized_domain == "news.google.com":
        return "AGGREGATOR"
    return "UNKNOWN"


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
    if _is_terminal(state):
        return state
    client = _model(state)
    seed = state["seed"]
    run_id, story_id = state["run_id"], state["story_id"]
    sources = seed.get("sources") or []
    source_ids = list(dict.fromkeys(
        item.get("source_id") for item in sources if item.get("source_id")
    ))
    prompt = (
        "Interpret and validate the already-ingested database candidate below. "
        "External news discovery is performed by deterministic ETL, not this stage. "
        "Set is_breaking=true only when the supplied facts show a newly developing "
        "event with immediate, material public significance; do not rely on the word "
        "'breaking' in a headline. If significance or freshness is uncertain, set "
        "false and explain the uncertainty. Do not claim source independence or "
        "corroboration here; preserve only supplied source IDs. Return JSON matching "
        "DiscoveryResult with exactly one candidate for this supplied database record. "
        "Do not omit the candidate because evidence is limited; downstream research "
        "and verification decide whether it is publishable. Return no candidates only "
        "if the supplied record is malformed. The candidates array must contain one "
        "object with story_id, title, summary, topic, source_ids, is_breaking, "
        "is_emerging, independent_source_count, first_seen_at, and discovery_rationale. "
        "Copy the record's story ID, title, summary, topic, source IDs, and timestamp "
        "exactly; use 0 for independent_source_count because this stage does not assess "
        "source independence.\n"
        + json.dumps({
            "run_id": run_id,
            "candidate": {
                "story_id": story_id,
                "title": seed.get("title", ""),
                "summary": seed.get("summary", ""),
                "topic": seed.get("topic", ""),
                "source_ids": source_ids,
                "first_seen_at": (state.get("story_record") or {}).get("first_seen_at"),
            },
        }, ensure_ascii=False)
    )
    result, _ = _structured(
        client, DiscoveryResult, prompt, state["provider"],
        context={"run_id": run_id, "story_id": story_id},
    )
    if not result.candidates:
        return _reject_candidate(
            state,
            "discovery",
            "MALFORMED_CANDIDATE",
            "candidate interpretation returned no candidate for the database record",
        )
    candidate = result.candidates[0]
    candidate = candidate.model_copy(update={
        "story_id": story_id,
        "title": seed.get("title", ""),
        "summary": seed.get("summary", ""),
        "topic": seed.get("topic", ""),
        "source_ids": source_ids,
        "first_seen_at": (state.get("story_record") or {}).get("first_seen_at"),
        "independent_source_count": 0,
    })
    result.candidates = [candidate]
    return _trace("discovery", state, [
        msg("discovery", "all", "HANDOFF",
            f"Interpreted existing candidate: {seed.get('title', '')!r}"),
    ]) | {"discovery": result.model_dump(mode="json")}


def node_source_intel(state: TeamState) -> TeamState:
    if _is_terminal(state):
        return state
    run_id, story_id = state["run_id"], state["story_id"]
    source_rows = (
        (state.get("production_context") or {}).get("sources")
        or state.get("sources")
        or (state.get("seed") or {}).get("sources")
        or []
    )
    source_inputs = []
    incomplete_sources = False
    for row in source_rows:
        source = row.get("source") or {}
        source_id = row.get("source_id") or source.get("id")
        source_url = row.get("canonical_url") or row.get("url") or ""
        parsed_url = urlsplit(str(source_url))
        if (
            not source_id
            or parsed_url.scheme not in ("http", "https")
            or not parsed_url.hostname
            or _is_placeholder_source_url(str(source_url))
        ):
            incomplete_sources = True
            continue
        publisher_name = str(row.get("source_name") or "").strip()
        ingestion_name = str(source.get("name") or "").strip()
        ingestion_domain = str(source.get("domain") or "").strip()
        if (
            publisher_name
            and (
                urlsplit(publisher_name).scheme in ("http", "https")
                or publisher_name.casefold() == ingestion_name.casefold()
                or publisher_name.casefold() == ingestion_domain.casefold()
            )
        ):
            publisher_name = ""
        documented_source_type = _documented_source_type(
            ingestion_name, ingestion_domain,
        )
        source_inputs.append({
            "source_id": str(source_id),
            "source_url": str(source_url),
            "publisher_name": publisher_name,
            "source_identity": publisher_name or (
                ingestion_name if documented_source_type == "AGGREGATOR" else ""
            ),
            "documented_source_type": documented_source_type,
            "ingestion_source_name": ingestion_name,
            "ingestion_source_type": source.get("source_type") or "",
            "ingestion_source_domain": ingestion_domain,
            "article_title": row.get("title") or "",
            "article_summary": row.get("description") or row.get("summary") or "",
            "source_metadata": source.get("metadata") or {},
            "documented_authority": (
                (source.get("metadata") or {}).get("authority")
                or (source.get("metadata") or {}).get("quality")
                or (source.get("metadata") or {}).get("authority_level")
            ),
        })
    if not source_inputs or incomplete_sources:
        return _reject_candidate(
            state,
            "source_intel",
            "SOURCE_VALIDATION_FAILED",
            "linked sources lack valid source IDs or HTTP(S) URLs",
        )

    story = (state.get("production_context") or {}).get("story") or state.get("story_record") or {}
    prompt = (
        "Assess only the linked source records provided. The ingestion-source fields "
        "identify the collection provider, not necessarily the publisher. Copy "
        "publisher_name exactly when present. Otherwise copy source_identity exactly "
        "when present; this is the documented collection source, not the publisher. "
        "Do not guess the publisher. Copy documented_source_type exactly when it is "
        "not UNKNOWN; otherwise use UNKNOWN unless the source records establish a "
        "classification. A URL or publisher name alone does not establish "
        "authority or quality; leave authority empty unless documented_authority "
        "contains evidence, and copy that value exactly. authority must always be "
        "a string, never null. Do not wrap source URLs in Markdown; copy all source "
        "identifiers and URLs unchanged from the supplied records. If publisher_name is empty, "
        "keep independence=UNKNOWN unless multiple actual publishers are documented. "
        "If fewer than two distinct "
        "publisher names are present, independence must be UNKNOWN for every assessment. "
        "Set independent_reporting to null when independence cannot be established; "
        "false means evidence establishes that the reporting is not independent. "
        "Do not infer independence, corroboration, or conflict. Use UNKNOWN and "
        "explicit uncertainty when the records do not establish a fact. Every assessment "
        "must include story_id=\""
        + story_id
        + "\" and copy an exact source_id and source_url from the input. Return one "
        "assessment for every source and include all SourceAssessment fields: story_id, "
        "source_id, source_url, source_name, source_type, authority, independence, "
        "attribution (string or null), confidence (number from 0 to 1 or null), "
        "conflicts, and uncertainty. Use null, not the string UNKNOWN, for unknown "
        "confidence or attribution. Return a "
        "SourceIntelligenceResult JSON object.\n"
        + json.dumps({
            "run_id": run_id,
            "story_id": story_id,
            "story": {
                "title": story.get("title") or "",
                "summary": story.get("summary") or "",
                "category": story.get("category") or (
                    story.get("metadata") or {}
                ).get("categories"),
                "first_seen_at": story.get("first_seen_at"),
            },
            "sources": source_inputs,
        }, ensure_ascii=False, default=str)
    )
    client = _model(state)
    result, _ = _structured(
        client, SourceIntelligenceResult, prompt, state["provider"],
        context={
            "run_id": run_id,
            "story_id": story_id,
            "source_inputs": source_inputs,
        },
        payload_normalizer=normalize_source_intelligence_payload,
    )
    expected = [(row["source_id"], row["source_url"]) for row in source_inputs]
    returned = {
        (assessment.source_id, assessment.source_url): assessment
        for assessment in result.assessments
    }
    expected_names = {
        (row["source_id"], row["source_url"]): row["source_identity"]
        for row in source_inputs
    }
    expected_types = {
        (row["source_id"], row["source_url"]): row["documented_source_type"]
        for row in source_inputs
    }
    enough_publishers = len({
        name.strip().casefold() for name in expected_names.values() if name.strip()
    }) >= 2
    if len(source_inputs) == 1 and len(result.assessments) == 1:
        # The database is authoritative for source identity. With a single
        # linked source, restore omitted or altered identifiers by position;
        # keep only the model's qualitative fields that survive validation.
        row = source_inputs[0]
        assessment = result.assessments[0].model_copy(update={
            "story_id": story_id,
            "source_id": row["source_id"],
            "source_url": row["source_url"],
            "source_name": row["source_identity"],
            "source_type": SourceType(row["documented_source_type"]),
            "authority": str(row["documented_authority"] or ""),
            "independence": "UNKNOWN",
        })
        result.assessments = [assessment]
        result.independent_reporting = None
        result.copying_detected = False
    if (
        len(result.assessments) != len(expected)
        or set(returned) != set(expected)
        or any(
            returned[key].source_name != publisher_name
            for key, publisher_name in expected_names.items()
        )
        or any(
            returned[key].source_type.value != source_type
            for key, source_type in expected_types.items()
            if source_type != "UNKNOWN"
        )
        or any(
            returned[(row["source_id"], row["source_url"])].authority
            != str(row["documented_authority"] or "")
            for row in source_inputs
        )
        or any(
            not row["publisher_name"]
            and row["documented_source_type"] == "UNKNOWN"
            and returned[(row["source_id"], row["source_url"])].source_type.value != "UNKNOWN"
            for row in source_inputs
        )
        or (
            not enough_publishers
            and (
                result.independent_reporting
                or any(
                    returned[key].independence.strip().upper() != "UNKNOWN"
                    for key in expected
                )
            )
        )
    ):
        return _reject_candidate(
            state,
            "source_intel",
            "SOURCE_VALIDATION_FAILED",
            "source assessment did not preserve the database source references",
        )
    result.run_id = run_id
    result.story_id = story_id
    result.assessments = [
        returned[(row["source_id"], row["source_url"])] for row in source_inputs
    ]
    return _trace("source_intel", state, [
        msg("source_intel", "research", "HANDOFF",
            f"Assessed {len(source_inputs)} linked database sources."),
    ]) | {"source_intel": result.model_dump(mode="json")}


def node_research(state: TeamState) -> TeamState:
    """Research — deterministic evidence, LLM-only-for-claims."""
    if _is_terminal(state):
        return state
    client = _model(state)
    run_id, story_id = state["run_id"], state["story_id"]
    seed = state.get("seed") or {}
    topic = (seed.get("title") or state.get("topic") or "").strip()
    story_date = _story_publication_date(state)
    questions = state.get("research_questions") or []
    it = _bump_iteration(state, "research")
    print(f"  [research] attempt {it} for topic={topic!r}")

    # ── Step 1: deterministic search + compaction ──
    queries = [topic] + (questions[:1] if questions else [])
    all_items: list[dict] = []
    stale_items = 0
    search_errors: list[str] = []
    for q in queries:
        try:
            raw = search_web.invoke({"query": q})
        except Exception as exc:  # noqa: BLE001
            print(f"  [research] search error for {q!r}: {exc}")
            search_errors.append(f"{type(exc).__name__}: {exc}")
            continue
        items = compact_search_results(raw, max_items=4)
        for item in items:
            parsed_url = urlsplit(str(item.get("url") or ""))
            if parsed_url.scheme not in ("http", "https") or not parsed_url.hostname:
                continue
            evidence_date = _date_in_url(str(item.get("url") or ""))
            if (
                story_date
                and evidence_date
                and (story_date - evidence_date).days > 1
            ):
                stale_items += 1
                continue
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
    if stale_items:
        print(
            f"  [research] excluded {stale_items} dated result(s) older than "
            "the selected story"
        )

    if not all_items:
        if search_errors:
            raise RuntimeError(
                "Research search failed before any evidence was found: "
                + "; ".join(search_errors)
            )
        return _trace("research", state, [
            msg("research", "research_gate", "INFO",
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
    example_evidence = allowed_ids[0]
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
      "evidence_ids": ["{example_evidence}"],
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
- Use field name "text" (NOT "claim").
- Use field name "evidence_ids" (NOT "sources").
- Each claim MUST cite at least one evidence_id from this exact list: {allowed_ids}
- Claims must accurately summarize what the cited evidence establishes. Do not
 add facts, causes, motivations, numbers, dates, or certainty not in evidence.
- Preserve attribution, uncertainty, opinion, allegation, and forecast status.
- If the evidence is not about {topic!r}, return claims=[] and explain in notes.
- Keep it under 3 claims total.

Return JSON only, no prose, no markdown fences.
""".strip()

    claims_result, method = _structured(
        client, ResearchClaims, prompt, state["provider"],
    )
    if not claims_result.claims:
        print(
            "[research] model returned no claims; retrying once against the "
            "same evidence"
        )
        recovery_prompt = (
            prompt
            + "\n\nRecovery attempt: Recheck only the evidence supplied above. "
            "If it supports any factual statement about the topic, return "
            "1-3 concise claims citing the exact available evidence_ids. "
            "Do not infer or add facts. Return claims=[] only if the evidence "
            "does not support a relevant factual statement."
        )
        try:
            retried_claims, retry_method = _structured(
                client, ResearchClaims, recovery_prompt, state["provider"],
            )
        except StructuredOutputError as exc:
            print(
                "[research] recovery attempt failed; retaining empty result "
                f"({type(exc).__name__})"
            )
        else:
            claims_result = retried_claims
            method = f"{method}+empty-retry:{retry_method}"
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

    # ── Step 5: assemble claims with known evidence references. ──
    # Semantic support is assessed by verification against the cited evidence.
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
    """Require evidence-backed claims; verification judges semantic support."""
    if _is_terminal(state):
        return state
    research = ResearchResult.model_validate(state["research"])
    evidence_by_id = {e.evidence_id: e for e in research.evidence}
    gate_errors: list[str] = []
    for c in research.claims:
        cited_evidence = [
            evidence_by_id[eid]
            for eid in c.evidence_ids
            if eid in evidence_by_id
        ]
        if not c.text.strip() or not cited_evidence:
            gate_errors.append(f"claim {c.claim_id} cites no known evidence")
            continue
        if any(
            not (item.url or "").startswith(("https://", "http://"))
            for item in cited_evidence
        ):
            gate_errors.append(f"claim {c.claim_id} cites evidence without a valid URL")

    if not research.claims:
        return _reject_candidate(
            state,
            "research_gate",
            "INSUFFICIENT_EVIDENCE",
            "research produced no evidence-backed claims",
        )

    if gate_errors:
        return _reject_candidate(
            state, "research_gate", "INSUFFICIENT_EVIDENCE", "; ".join(gate_errors),
        )

    return _trace("research_gate", state, [
        msg("research_gate", "verification", "HANDOFF",
            "All claims have evidence references and valid source URLs."),
    ])


def node_verification(state: TeamState) -> TeamState:
    """Verification - judges claims against the evidence they cite."""
    if _is_terminal(state):
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
    supported_ids = {
        v.claim_id for v in result.verifications
        if v.status in (
            VerificationStatus.SUPPORTED,
            VerificationStatus.SUPPORTED_AS_ATTRIBUTED,
        )
    }
    supported_count = len(supported_ids)

    messages = [
        msg("verification", "editorial", "HANDOFF",
            str(supported_count) + " supported, " + str(len(unsupported)) + " unsupported."),
    ]
    out = {"verification": result.model_dump(mode="json"), "research_questions": []}
    if not supported_ids:
        return _trace("verification", state, messages) | out | {
            "outcome": "CANDIDATE_REJECTED",
            "candidate_rejection_reason": "VERIFICATION_FAILED",
            "blockers": (state.get("blockers") or [])
            + ["verification found no publishable supported claims"],
        }
    return _trace("verification", state, messages) | out


def _editorial_memory_context(editorial_memory: dict | None) -> str:
    if not isinstance(editorial_memory, dict):
        return "(no similar recent stories)"
    similar_stories = editorial_memory.get("similar_stories", [])
    memory_lines = []
    if isinstance(similar_stories, list):
        for similar in similar_stories[:5]:
            if not isinstance(similar, dict):
                continue
            title = str(similar.get("title") or "").strip()
            if not title:
                continue
            relationship = str(similar.get("relationship") or "RELATED").upper()
            published_at = str(similar.get("published_at") or "unknown")
            memory_lines.append(
                f"- {relationship}: {title} (published/seen: {published_at})"
            )
    return chr(10).join(memory_lines) or "(no similar recent stories)"


def _select_strongest_verified_claim(
    research: ResearchResult,
    verification: VerificationResult,
    source_intel: dict[str, Any] | None,
) -> tuple[Claim, VerificationStatus] | None:
    """Choose an evidence-backed, non-speculative claim deterministically."""
    verifications = {
        item.claim_id: item
        for item in verification.verifications
        if item.status in (
            VerificationStatus.SUPPORTED,
            VerificationStatus.SUPPORTED_AS_ATTRIBUTED,
        )
    }
    evidence_by_id = {
        item.evidence_id: item
        for item in research.evidence
        if item.url
        and urlsplit(item.url).scheme in ("http", "https")
        and urlsplit(item.url).hostname
        and not _is_placeholder_source_url(item.url)
    }
    source_ranks = {
        "PRIMARY": 4,
        "OFFICIAL": 4,
        "SECONDARY": 3,
        "AGGREGATOR": 1,
        "UNKNOWN": 0,
        "OPINION": -1,
    }
    assessments = (source_intel or {}).get("assessments", [])
    if not isinstance(assessments, list):
        assessments = []
    assessment_ranks = {
        str(item.get("source_id") or ""): source_ranks.get(
            str(item.get("source_type") or "UNKNOWN").upper(), 0,
        )
        for item in assessments
        if isinstance(item, dict)
    }

    ranked: list[tuple[tuple[int, int, int, int, int], str, Claim, VerificationStatus]] = []
    for claim in research.claims:
        item = verifications.get(claim.claim_id)
        if (
            item is None
            or claim.is_forecast
            or claim.is_allegation
            or claim.is_opinion
        ):
            continue
        claim_evidence_ids = set(claim.evidence_ids)
        verification_evidence_ids = set(item.evidence_ids)
        referenced_evidence_ids = (
            claim_evidence_ids & verification_evidence_ids
            if verification_evidence_ids
            else claim_evidence_ids
        )
        evidence = [
            evidence_by_id[evidence_id]
            for evidence_id in dict.fromkeys(item.evidence_ids or claim.evidence_ids)
            if evidence_id in referenced_evidence_ids
            and evidence_id in evidence_by_id
        ]
        if not evidence:
            continue

        source_ids = {entry.source_id for entry in evidence}
        source_quality = max(
            (assessment_ranks.get(source_id, 0) for source_id in source_ids),
            default=0,
        )
        verified_status_rank = int(item.status == VerificationStatus.SUPPORTED)
        specificity = min(
            len(re.findall(r"\b[\w'-]+\b", claim.text)),
            100,
        )
        certainty = int(not bool(claim.uncertainty.strip()))
        score = (
            source_quality,
            len(source_ids),
            certainty,
            specificity,
            verified_status_rank,
        )
        ranked.append((score, claim.claim_id, claim, item.status))

    if not ranked:
        return None
    _, _, claim, status = min(ranked, key=lambda entry: (
        tuple(-value for value in entry[0]),
        entry[1],
    ))
    return claim, status


def _select_writer_fallback_claim(
    research: ResearchResult,
    verification: VerificationResult,
    editorial: EditorialDecision,
    source_intel: dict[str, Any] | None,
    max_chars: int,
) -> Claim | None:
    """Select an approved, central verified claim for exact-wording fallback."""
    approved_ids = set(editorial.allowed_claim_ids)
    eligible = [
        claim for claim in research.claims
        if claim.claim_id in approved_ids
        and not claim.is_forecast
        and not claim.is_allegation
        and not claim.is_opinion
        and 0 < len(claim.text.strip()) <= max_chars
        and re.search(r"[.!?][\"'”’)\]]*$", claim.text.strip())
        and len(_split_post_sentences(claim.text.strip())) == 1
    ]
    if not eligible:
        return None

    central_tokens = _claim_tokens(editorial.central_event)
    if central_tokens:
        centrality = {
            claim.claim_id: len(_claim_tokens(claim.text) & central_tokens)
            for claim in eligible
        }
        strongest_centrality = max(centrality.values(), default=0)
        if strongest_centrality:
            eligible = [
                claim for claim in eligible
                if centrality[claim.claim_id] == strongest_centrality
            ]

    approved_research = research.model_copy(update={"claims": eligible})
    selected = _select_strongest_verified_claim(
        approved_research,
        verification,
        source_intel,
    )
    return selected[0] if selected else None


def _has_unresolved_duplicate(editorial_memory: dict[str, Any] | None) -> bool:
    if not isinstance(editorial_memory, dict):
        return False
    similar_stories = editorial_memory.get("similar_stories")
    if not isinstance(similar_stories, list):
        return False
    return any(
        isinstance(item, dict)
        and str(item.get("relationship") or "").upper()
        in {"DUPLICATE", "REPETITIVE"}
        for item in similar_stories
    )


def node_editorial(state: TeamState) -> TeamState:
    """Editorial — decides what the story is actually about."""
    if _is_terminal(state):
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
    if not allowed_claims:
        return _reject_candidate(
            state,
            "editorial",
            "NO_EDITORIAL_PATH",
            "no verified claims remain for an evidence-based post",
        )
    claims_block = chr(10).join(
        "  [" + c.claim_id + "] " + c.text
        + (" (FORECAST - attribution: " + c.attribution + ")" if c.is_forecast else "")
        for c in allowed_claims
    )
    memory_block = _editorial_memory_context(state.get("editorial_memory"))
    fixes = state.get("editorial_fixes") or []
    fixes_block = chr(10).join("- " + f for f in fixes) if fixes else "(none)"

    prompt = (
        "You are the Editorial Agent. Decide what this story is about." + chr(10) + chr(10)
        + "run_id = " + repr(run_id) + chr(10)
        + "story_id = " + repr(story_id) + chr(10) + chr(10)
        + "Verified claims you may use:" + chr(10)
        + claims_block + chr(10) + chr(10)
        + "Recent similar published or candidate stories:" + chr(10)
        + memory_block + chr(10) + chr(10)
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
        + "- Treat DUPLICATE or REPETITIVE coverage as ineligible unless these verified claims establish a material new development." + chr(10)
        + "- If there is no material update to a DUPLICATE or REPETITIVE story, approve no claims." + chr(10)
        + "- RELATED coverage alone does not make this story ineligible." + chr(10)
        + "- Use only claim_ids from the list above." + chr(10) + chr(10)
        + "Return JSON matching EditorialDecision exactly."
    )

    result, _ = _structured(
        client, EditorialDecision, prompt, state["provider"],
        context={"run_id": run_id, "story_id": story_id},
    )
    print("  [editorial] central_event=" + repr(result.central_event[:80]))
    model_selected_claims = list(result.allowed_claim_ids)
    result.allowed_claim_ids = [
        claim_id for claim_id in result.allowed_claim_ids if claim_id in allowed
    ]
    print("  [editorial] allowed=" + str(result.allowed_claim_ids))
    if not result.allowed_claim_ids:
        if model_selected_claims:
            return _reject_candidate(
                state,
                "editorial",
                "NO_EDITORIAL_PATH",
                "editorial selected no verified claim IDs",
            )

        story_metadata = (
            (state.get("production_context") or {}).get("story")
            or state.get("story_record")
            or {}
        ).get("metadata") or {}
        if not isinstance(story_metadata, dict):
            story_metadata = {}
        if (
            story_metadata.get("topic_fit") is False
            or story_metadata.get("newsworthiness") is False
        ):
            return _reject_candidate(
                state,
                "editorial",
                "EDITORIAL_QUALITY_GATE_FAILED",
                "story failed the existing topic-fit or newsworthiness gate",
            )
        if _has_unresolved_duplicate(state.get("editorial_memory")):
            return _reject_candidate(
                state,
                "editorial",
                "DUPLICATE_NO_MATERIAL_UPDATE",
                "editorial memory identifies duplicate or repetitive coverage and no update was approved",
            )

        fallback = _select_strongest_verified_claim(
            research,
            verification,
            state.get("source_intel"),
        )
        if fallback is None:
            return _reject_candidate(
                state,
                "editorial",
                "NO_EDITORIAL_PATH",
                "no safe, URL-backed verified claim is available for deterministic fallback",
            )
        fallback_claim, fallback_status = fallback
        result.allowed_claim_ids = [fallback_claim.claim_id]
        result.central_event = fallback_claim.text
        fallback_reason = "EDITORIAL_EMPTY_SELECTION_FALLBACK"
        _LOGGER.warning(
            "Editorial LLM returned no allowed claims; using deterministic verified-claim fallback",
            extra={
                "story_id": story_id,
                "selected_claim_id": fallback_claim.claim_id,
                "verification_status": fallback_status.value,
                "fallback_reason": fallback_reason,
            },
        )
        print(
            "  [editorial] deterministic fallback selected "
            + fallback_claim.claim_id
            + " ("
            + fallback_status.value
            + ")"
        )
        fallback_message = msg(
            "editorial",
            "tone",
            "INFO",
            fallback_reason + ": selected " + fallback_claim.claim_id
            + " (" + fallback_status.value + ")",
        )
    else:
        fallback_message = None

    # Deterministic: central_event must be non-empty.
    if not result.central_event or not result.central_event.strip():
        result.central_event = allowed_claims[0].text if allowed_claims else "(no approved claims)"
        print("  [editorial] central_event empty — substituted")

    return _trace("editorial", state, [
        msg("editorial", "tone", "HANDOFF",
            "Central event: " + result.central_event[:120]),
    ] + ([fallback_message] if fallback_message else [])) | {
        "editorial": result.model_dump(mode="json"),
        "editorial_fixes": [],
    }


def node_tone(state: TeamState) -> TeamState:
    """Tone — chooses presentation tone based on subject sensitivity."""
    if _is_terminal(state):
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
    if _is_terminal(state):
        return state

    import os
    # Track writer retries so the loop is bounded.
    _it = dict(state.get("iteration") or {})
    _it["writer"] = _it.get("writer", 0) + 1
    state = {**state, "iteration": _it}
    client = _model(state)
    run_id, story_id = state["run_id"], state["story_id"]
    research = ResearchResult.model_validate(state["research"])
    editorial = EditorialDecision.model_validate(state["editorial"])
    verification = VerificationResult.model_validate(state["verification"])
    tone_decision = ToneDecision.model_validate(state["tone"])

    verification_statuses = {
        item.claim_id: item.status
        for item in verification.verifications
        if item.status in (
            VerificationStatus.SUPPORTED,
            VerificationStatus.SUPPORTED_AS_ATTRIBUTED,
        )
    }
    approved = [
        claim for claim in research.claims
        if claim.claim_id in editorial.allowed_claim_ids
        and claim.claim_id in verification_statuses
    ]
    if not approved:
        return _reject_candidate(
            state,
            "writer",
            "WRITER_FAILED",
            "no editorial-approved verified claims are available",
        )
    if set(editorial.allowed_claim_ids) - set(verification_statuses):
        return _reject_candidate(
            state,
            "writer",
            "WRITER_FAILED",
            "editorial selection contains claims not supported by verification",
        )

    approved_block = chr(10).join(
        "- " + c.claim_id + " ["
        + verification_statuses[c.claim_id].value
        + "]: " + c.text
        + (" [attribution: " + c.attribution + "]" if c.attribution else "")
        + (" [uncertainty: " + c.uncertainty + "]" if c.uncertainty else "")
        + (" [forecast]" if c.is_forecast else "")
        + (" [allegation]" if c.is_allegation else "")
        + (" [opinion]" if c.is_opinion else "")
        for c in approved
    )
    do_not = chr(10).join("- " + m for m in editorial.do_not_include) if editorial.do_not_include else "(none)"
    previous_validation = state.get("validation") or {}
    failed_sentences = previous_validation.get("failed_sentences") or []
    previous_post = (state.get("post") or {}).get("text") or ""
    if failed_sentences:
        retry_instructions = (
            "STRICT QA RETRY. The previous post failed because these exact "
            "sentence(s) could not be grounded in an approved claim:" + chr(10)
            + chr(10).join(repr(sentence) for sentence in failed_sentences)
            + chr(10) + "Remove each sentence and its unsupported idea entirely. "
            "Do not paraphrase it, replace it, or add a new factual sentence. "
            "For the replacement body, copy the text of one approved claim "
            "below verbatim as one complete sentence, and list only that "
            "claim ID. Do not add a headline or any other factual wording to "
            "the body. If no approved claim fits, return an empty body."
        )
    elif state.get("validation_feedback"):
        retry_instructions = (
            "STRICT QA RETRY. Correct these exact validation failures without "
            "adding facts:" + chr(10)
            + chr(10).join("- " + item for item in state.get("validation_feedback", []))
        )
    else:
        retry_instructions = "(not a retry)"

    prompt = (
        "You are the Writer. Write a concise Threads post using only the "
        "approved and verified claim text below." + chr(10) + chr(10)
        + "run_id = " + repr(run_id) + chr(10)
        + "story_id = " + repr(story_id) + chr(10) + chr(10)
        + "Approved claims (the only permitted source of factual content):" + chr(10)
        + approved_block + chr(10) + chr(10)
        + "Editorial exclusions (do not include):" + chr(10) + do_not + chr(10) + chr(10)
        + "Editorial central-event, framing, and must-include text are not "
        "verified facts. Do not use them to add information; include a requested "
        "idea only when it is stated by an approved claim." + chr(10) + chr(10)
        + "Previous post (for QA rewrite only):" + chr(10)
        + (repr(previous_post) if previous_post else "(none)") + chr(10) + chr(10)
        + "QA retry instructions:" + chr(10) + retry_instructions + chr(10) + chr(10)
        + "Tone: " + tone_decision.tone.value + chr(10)
        + "Target platform: Threads; keep one concise post within "
        + str(os.environ.get("THREADS_MAX_CHARS", "280"))
        + " characters." + chr(10)
        + "Write the complete post within the character limit. Do not rely on "
        "downstream truncation. Prefer 2-4 concise complete sentences. End "
        "naturally with '.', '!' or '?'. Never end with an ellipsis or leave "
        "a sentence incomplete." + chr(10)
        + "Rules:" + chr(10)
        + "- Every factual sentence must be directly grounded in one or more approved claims." + chr(10)
        + "- Lead with the central event, not a secondary detail. When multiple approved claims are available, prioritize the claim that explains what happened and why the story matters; do not choose a minor fact merely because it is shorter." + chr(10)
        + "- A person's age, arrest status, location detail, or other secondary fact should not replace the central event unless that detail is itself the main news." + chr(10)
        + "- Prefer exact approved-claim wording; do not substitute near-synonyms or add descriptive wording." + chr(10)
        + "- Do not add context, causal links, motivation, comparisons, names, dates, numbers, quotes, URLs, or conclusions not stated in those claims." + chr(10)
        + "- Preserve attribution, allegation status, forecast status, and uncertainty." + chr(10)
        + "- For SUPPORTED_AS_ATTRIBUTED claims, keep the claim's attribution in the post; never state the attributed fact as independently confirmed." + chr(10)
        + "- claim_ids must list only approved claim IDs directly used in the post." + chr(10)
        + "- If a supported post cannot be written, return an empty body; do not improvise." + chr(10)
        + "- Do not add a source label or URL; verified source links are attached separately." + chr(10)
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

    exact_claim_fallback = None
    if failed_sentences and _it["writer"] > 1:
        max_chars = int(os.environ.get("THREADS_MAX_CHARS", "280"))
        exact_claim_fallback = _select_writer_fallback_claim(
            research,
            verification,
            editorial,
            state.get("source_intel"),
            max_chars,
        )

    if exact_claim_fallback is not None:
        result = WriterDraft(
            run_id=run_id,
            story_id=story_id,
            body=exact_claim_fallback.text.strip(),
            claim_ids=[exact_claim_fallback.claim_id],
            tone=tone_decision.tone,
            warnings=["Used exact verified-claim wording after grounding retry."],
        )
        print(
            "[writer] using exact verified-claim fallback after "
            "grounding feedback"
        )
    else:
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
                from core.tools.compress import compress_to_limit
                first = compress_to_limit(first, limit=120)
            result.headline = first
            print(f"  [writer] headline derived from body: {first[:80]!r}")
        else:
            print("  [writer] WARNING: no body and no headline produced")

    print("  [writer] " + str(len(result.body)) + " chars, " + str(len(result.claim_ids)) + " claims, headline=" + (result.headline[:40] if result.headline else "<empty>"))
    if not (result.body or "").strip():
        return _reject_candidate(
            state,
            "writer",
            "WRITER_FAILED",
            "writer could not produce a post grounded in approved claims",
        )

    return _trace("writer", state, [
        msg("writer", "platform_adapter", "HANDOFF",
            "Draft ready (" + str(len(result.body)) + " chars)"),
    ]) | {"draft": result.model_dump(mode="json")}


def node_platform_adapter(state: TeamState) -> TeamState:
    """Platform Adapter - produces a 2-3 line Threads post."""

    if _is_terminal(state):
        return state
    import os
    run_id, story_id = state["run_id"], state["story_id"]
    draft = WriterDraft.model_validate(state["draft"])

    max_chars = int(os.environ.get("THREADS_MAX_CHARS", "280"))

    headline = (draft.headline or "").strip()
    body = (draft.body or "").strip()

    retrying_writer = (
        (state.get("iteration") or {}).get("writer", 0) > 1
        and bool(state.get("validation_feedback"))
    )
    if retrying_writer:
        result = PlatformPost(
            run_id=run_id,
            story_id=story_id,
            platform="threads",
            text=body,
            char_count=len(body),
            claim_ids=list(draft.claim_ids),
            source_reference=draft.source_reference,
        )
    else:
        client = _model(state)
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
        + "- Return only complete sentences and end naturally with '.', '!' or '?'." + chr(10)
        + "- Never end with an ellipsis or leave a sentence incomplete." + chr(10)
        + "- Shorten only. Do not add, repeat, or strengthen claims from the draft." + chr(10)
        + "- 2-3 short sentences. No headline line. No bullet lists." + chr(10)
        + "- Lead with the most newsworthy fact." + chr(10)
        + "- Preserve every number, date, name, and attribution exactly." + chr(10)
        + "- Preserve uncertainty and material caveats exactly." + chr(10)
        + "- Never add a 'Source:' label or invent or rewrite a source URL; verified URLs are appended deterministically." + chr(10)
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
            print("  [platform_adapter] compressor failed: " + type(exc).__name__)
            from core.tools.compress import _finish_sentence
            text = _finish_sentence(text, max_chars)

    research = ResearchResult.model_validate(state["research"])
    claims_by_id = {claim.claim_id: claim for claim in research.claims}
    result.claim_ids = sorted({
        claim_id
        for sentence in _split_post_sentences(text)
        for claim_id in _sentence_claim_ids(
            sentence, draft.claim_ids, claims_by_id,
        )
    })
    source_url = _verified_source_reference(state, result.claim_ids)
    if source_url:
        text = re.sub(
            r"(?im)^Source:\s*(https?://\S+)\s*$",
            lambda match: (
                match.group(1)
                if match.group(1).rstrip(".,;:!?)]}") == source_url.rstrip(".,;:!?)]}")
                else match.group(0)
            ),
            text,
        )
        linked_text = _append_source_reference(text, source_url, max_chars)
        if linked_text != text:
            text = linked_text
            result.source_reference = source_url
        elif any(
            _is_verified_source_reference(sentence, {source_url})
            for sentence in _split_post_sentences(text)
        ):
            result.source_reference = source_url
    result.text = text
    result.claim_ids = sorted({
        claim_id
        for sentence in _split_post_sentences(text)
        if not _is_verified_source_reference(
            sentence,
            {source_url} if source_url else set(),
        )
        for claim_id in _sentence_claim_ids(
            sentence, draft.claim_ids, claims_by_id,
        )
    })
    result.char_count = len(text)

    return _trace("platform_adapter", state, [
        msg("platform_adapter", "validation", "HANDOFF",
            "Post adapted (" + str(result.char_count) + " chars)"),
    ]) | {"post": result.model_dump(mode="json")}


def _validation_retry_target(
    state: TeamState, errors: list[str],
) -> Literal["writer", "editorial"] | None:
    writer_attempts = (state.get("iteration") or {}).get("writer", 0)
    editorial_fixes = (state.get("iteration") or {}).get("editorial_fix", 0)
    needs_editorial = any("unapproved" in error for error in errors)
    needs_writer = any(
        marker in error
        for error in errors
        for marker in (
            "attribution", "seed subject", "empty post", "not grounded",
            "repetitive", "without claim-bearing content",
            "exceeds Threads limit", "more than one source URL",
            "source label", "internal instructions", "null control character",
        )
    )
    if needs_editorial and editorial_fixes < MAX_EDITORIAL_FIXES:
        return "editorial"
    if needs_writer and writer_attempts < MAX_WRITER_ATTEMPTS:
        return "writer"
    return None


def node_validation(state: TeamState) -> TeamState:
    """Deterministic. Can route back to writer or editorial, or forward to publisher."""
    if _is_terminal(state):
        return state
    post = PlatformPost.model_validate(state["post"])
    draft = WriterDraft.model_validate(state["draft"])
    editorial = EditorialDecision.model_validate(state["editorial"])
    research = ResearchResult.model_validate(state["research"])
    verification = VerificationResult.model_validate(state["verification"])
    seed = state["seed"]

    errors: list[str] = []
    sentence_claims: list[dict[str, Any]] = []
    failed_sentences: list[str] = []
    if not post.text.strip():
        errors.append("empty post text")
    try:
        post.text.encode("utf-8")
    except UnicodeEncodeError:
        errors.append("post text is not valid UTF-8")
    if "\x00" in post.text:
        errors.append("post contains a null control character")
    if re.search(r"\bSource\s*[:-]", post.text, flags=re.IGNORECASE):
        errors.append("post contains a source label")
    if re.search(
        r"(?:return\s+json|you are the (?:writer|platform adaptor)|"
        r"approved claims\s*\(|system prompt|do not include this instruction)",
        post.text,
        flags=re.IGNORECASE,
    ):
        errors.append("post contains internal instructions")

    research_claims = {claim.claim_id: claim for claim in research.claims}
    evidence_by_id = {evidence.evidence_id: evidence for evidence in research.evidence}
    allowed_urls = {
        evidence.url.rstrip(".,;:!?)]}")
        for evidence in research.evidence
        if evidence.url
    }
    allowed_urls.update(
        str(item.get("canonical_url") or item.get("url") or "").rstrip(".,;:!?)]}")
        for item in ((state.get("production_context") or {}).get("sources") or [])
        if isinstance(item, dict) and (item.get("canonical_url") or item.get("url"))
    )
    verified_claim_ids = {
        item.claim_id for item in verification.verifications
        if item.status in (
            VerificationStatus.SUPPORTED,
            VerificationStatus.SUPPORTED_AS_ATTRIBUTED,
        )
    }
    allowed_claim_ids = set(editorial.allowed_claim_ids)
    if not allowed_claim_ids.issubset(verified_claim_ids):
        errors.append("editorial allows claims not approved by verification")
    for cid in post.claim_ids:
        if cid not in editorial.allowed_claim_ids:
            errors.append(f"post references unapproved claim: {cid}")
        claim = research_claims.get(cid)
        if claim is None:
            errors.append(f"post references unknown research claim: {cid}")
        elif not claim.evidence_ids or any(
            evidence_id not in evidence_by_id
            or not (evidence_by_id[evidence_id].url or "").startswith(("https://", "http://"))
            for evidence_id in claim.evidence_ids
        ):
            errors.append(f"approved claim has no URL-backed evidence: {cid}")
    for cid in draft.claim_ids:
        if cid not in editorial.allowed_claim_ids:
            errors.append(f"draft references unapproved claim: {cid}")

    approved_claim_texts = [
        research_claims[cid].text
        for cid in editorial.allowed_claim_ids
        if cid in research_claims and cid in verified_claim_ids
    ]
    if post.text.strip() and not post.claim_ids:
        errors.append("post references no approved claims")
    if approved_claim_texts:
        sentences = _split_post_sentences(post.text)
        sentence_token_sets = []
        for sentence in sentences:
            if _is_verified_source_reference(sentence, allowed_urls):
                continue
            sentence_tokens = _claim_tokens(sentence)
            sentence_token_sets.append(sentence_tokens)
            if len(sentence_tokens) < 2:
                errors.append("post contains a sentence without claim-bearing content")
                failed_sentences.append(sentence)
                continue
            matching_claim_ids = _sentence_claim_ids(
                sentence,
                [
                    claim_id for claim_id in editorial.allowed_claim_ids
                    if claim_id in verified_claim_ids
                ],
                research_claims,
            )
            if not matching_claim_ids:
                best_coverage = max(
                    (
                        len(sentence_tokens & _claim_tokens(claim_text))
                        / len(sentence_tokens)
                        for claim_text in approved_claim_texts
                    ),
                    default=0.0,
                )
                errors.append(
                    "post contains a sentence not grounded in an approved claim "
                    f"(best single-claim content-token coverage {best_coverage:.0%}; "
                    "all content tokens must be supported by one claim): "
                    + repr(sentence)
                )
                failed_sentences.append(sentence)
                break
            sentence_claims.append({
                "sentence": sentence,
                "claim_ids": matching_claim_ids,
            })
    mapped_claim_ids = {
        claim_id
        for mapping in sentence_claims
        for claim_id in mapping["claim_ids"]
    }
    if mapped_claim_ids != set(post.claim_ids):
        errors.append(
            "post claim IDs are not grounded accurately in sentence-level mappings"
        )
    if not mapped_claim_ids.issubset(set(draft.claim_ids)):
        errors.append("draft claim IDs omit claims used by grounded post sentences")
        if not errors:
            for index, left in enumerate(sentence_token_sets):
                for right in sentence_token_sets[index + 1:]:
                    shared = len(left & right)
                    smaller = min(len(left), len(right))
                    union = len(left | right)
                    if (
                        smaller
                        and shared / smaller >= 0.7
                        and union
                        and shared / union >= 0.4
                    ):
                        errors.append("post contains repetitive sentences")
                        break
                if errors:
                    break

    post_urls = re.findall(r"https?://\S+", post.text)
    if len(post_urls) > 1:
        errors.append("post contains more than one source URL")
    for raw_url in post_urls:
        if raw_url.rstrip(".,;:!?)]}") not in allowed_urls:
            errors.append("post contains an unverified URL")
            break

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
    _max = int(_os.environ.get("THREADS_MAX_CHARS", "500"))
    if len(post.text) > _max:
        errors.append(f"post exceeds Threads limit: {len(post.text)} > {_max}")

    state_out: ValidationResult = ValidationResult(
        run_id=post.run_id, story_id=post.story_id,
        state=ValidationState.PASS if not errors else ValidationState.BLOCK,
        errors=errors,
        sentence_claims=sentence_claims,
        failed_sentences=failed_sentences,
    )
    messages = [msg("validation", "publisher" if not errors else "writer",
                    "HANDOFF" if not errors else "FEEDBACK",
                    "OK" if not errors else "; ".join(errors))]
    result = _trace("validation", state, messages) | {
        "validation": state_out.model_dump(mode="json"),
        "validation_feedback": errors,
    }
    retry_target = _validation_retry_target(state, errors) if errors else None
    result = result | {"validation_retry_target": retry_target or ""}
    if errors:
        if retry_target is None:
            message = "candidate failed deterministic QA after the available retry"
            result = result | {
                "outcome": "CANDIDATE_REJECTED",
                "candidate_rejection_reason": "QA_FAILED",
                "blockers": (state.get("blockers") or []) + [message],
            }
        elif retry_target == "editorial":
            iteration = dict(state.get("iteration") or {})
            iteration["editorial_fix"] = iteration.get("editorial_fix", 0) + 1
            result = result | {"iteration": iteration}
    return result


def _supported_research_domains(
    research: dict[str, Any],
    verification: VerificationResult,
) -> set[str]:
    supported_claim_ids = {
        item.claim_id
        for item in verification.verifications
        if item.status in (
            VerificationStatus.SUPPORTED,
            VerificationStatus.SUPPORTED_AS_ATTRIBUTED,
        )
    }
    evidence_ids = {
        evidence_id
        for claim in research.get("claims") or []
        if claim.get("claim_id") in supported_claim_ids
        for evidence_id in claim.get("evidence_ids") or []
    }
    aggregator_hosts = {
        "google.com",
        "news.google.com",
        "news.yahoo.com",
        "bing.com",
        "duckduckgo.com",
        "tavily.com",
        "gdeltproject.org",
    }
    domains: set[str] = set()
    for evidence in research.get("evidence") or []:
        if evidence.get("evidence_id") not in evidence_ids:
            continue
        host = (urlsplit(evidence.get("url") or "").hostname or "")
        host = host.lower().removeprefix("www.")
        if not host or any(
            host == aggregator or host.endswith("." + aggregator)
            for aggregator in aggregator_hosts
        ):
            continue
        domains.add(host)
    return domains


def node_eligibility_gate(state: TeamState) -> TeamState:
    """Apply breaking-news eligibility checks before publication."""
    if _is_terminal(state):
        return state

    if state.get("mode") == "breaking":
        from datetime import datetime, timezone

        discovery = state.get("discovery") or {}
        candidates = discovery.get("candidates") or []
        candidate = candidates[0] if candidates else {}
        rationale = (candidate.get("discovery_rationale") or "").strip()
        timestamp = (state.get("story_record") or {}).get("first_seen_at")
        fresh = False
        if timestamp:
            try:
                first_seen = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                if first_seen.tzinfo is None:
                    first_seen = first_seen.replace(tzinfo=timezone.utc)
                age_minutes = (datetime.now(timezone.utc) - first_seen).total_seconds() / 60
                fresh = 0 <= age_minutes <= 180
            except ValueError:
                fresh = False

        from schemas.taxonomy import is_rejected_category
        story = state.get("story_record") or {}
        categories = story.get("categories") or (story.get("metadata") or {}).get("categories") or []
        eligible_category = bool(categories) and not any(
            is_rejected_category(str(category)) for category in categories
        )
        source_intel = state.get("source_intel") or {}
        source_domains = {
            (urlsplit(item.get("source_url") or "").hostname or "")
            .lower().removeprefix("www.")
            for item in source_intel.get("assessments") or []
            if item.get("source_url")
        }
        source_domains.discard("")
        independently_assessed_domains = {
            (urlsplit(item.get("source_url") or "").hostname or "")
            .lower().removeprefix("www.")
            for item in source_intel.get("assessments") or []
            if item.get("source_url")
            and str(item.get("independence") or "").strip().upper()
            in ("INDEPENDENT", "INDEPENDENTLY REPORTED")
            and str(item.get("source_type") or "").upper() != "AGGREGATOR"
        }
        independently_assessed_domains.discard("")
        research = state.get("research") or {}
        evidence = research.get("evidence") or []
        claims = research.get("claims") or []
        verified = VerificationResult.model_validate(state["verification"])
        research_domains = _supported_research_domains(research, verified)
        source_domains.update(research_domains)
        independently_assessed_domains.update(research_domains)
        independent_reporting = (
            source_intel.get("independent_reporting") is True
            or len(research_domains) >= 2
        )
        all_claims_supported = bool(claims) and all(
            item.status in (
                VerificationStatus.SUPPORTED,
                VerificationStatus.SUPPORTED_AS_ATTRIBUTED,
            )
            for item in verified.verifications
        ) and {item.claim_id for item in verified.verifications} >= {
            item.get("claim_id") for item in claims
        }
        breaking_eligible = (
            candidate.get("is_breaking") is True
            and bool(rationale)
            and fresh
            and eligible_category
            and len(source_domains) >= 2
            and len(independently_assessed_domains) >= 2
            and independent_reporting
            and source_intel.get("copying_detected") is False
            and bool(evidence)
            and all_claims_supported
        )
        if not breaking_eligible:
            reason = (
                "breaking eligibility requires a reasoned significance assessment, "
                "freshness, allowed category, two distinct publisher domains from "
                "linked sources or verified research evidence, "
                "independent corroboration, no copying signal, and verified evidence"
            )
            return _trace("eligibility_gate", state, [
                msg("eligibility_gate", "all", "BLOCKER", reason),
            ]) | {
                "outcome": "BLOCKED_BREAKING_ELIGIBILITY",
                "blockers": (state.get("blockers") or []) + [reason],
            }

    return _trace("eligibility_gate", state, [
        msg("eligibility_gate", "publisher", "HANDOFF", "publication eligibility passed"),
    ])

def node_publisher(state: TeamState) -> TeamState:
    """Publish to Threads via ThreadsAPI. Never refreshes tokens."""
    if state.get("outcome") != "RUNNING":
        return state
    import os
    post = PlatformPost.model_validate(state["post"])
    story_id = state.get("story_id", "")
    run_id = state.get("run_id", "")

    # Respect dry_run from state (set by the runner) as the primary signal.
    # Fall back to NEWSROOM_LIVE env if state doesn't contain dry_run.
    if "dry_run" in state:
        dry_run = bool(state["dry_run"])
    else:
        live = os.environ.get("NEWSROOM_LIVE", "").strip().lower() in ("1", "true", "yes")
        dry_run = not live
    live = not dry_run

    # Live publication is only allowed against the real production database.
    if live:
        try:
            from core.tools.database.client import is_production
            if not is_production():
                raise RuntimeError("live Threads publication requires Supabase")
        except Exception as exc:
            return _trace("publisher", state, [
                msg("publisher", "all", "BLOCKER", "Production database unavailable; publication blocked."),
            ]) | {
                "publication": PublishResult(
                    run_id=run_id, story_id=story_id, platform="threads",
                    status="BLOCKED_DATABASE_UNAVAILABLE", error=str(exc),
                ).model_dump(mode="json"),
                "outcome": "SYSTEM_ERROR",
            }

    # ── Duplicate check (fail-closed) ──
    if live and story_id:
        try:
            from core.tools.database.stories import find_duplicate_publication
            existing = find_duplicate_publication(story_id, platform="threads")
            if existing:
                existing_status = str(existing.get("status") or "").lower()
                if existing_status == "publishing":
                    try:
                        from core.tools.publishing import reconcile_threads_publication
                        recovered = reconcile_threads_publication(
                            str(existing.get("content") or post.text),
                            started_at=(existing.get("metadata") or {}).get("started_at"),
                        )
                        if recovered:
                            from core.tools.database import stories as _db
                            _db.update_publication_result(existing["id"], {
                                "status": "published",
                                "external_post_id": recovered["external_id"],
                                "published_at": recovered["published_at"],
                                "metadata": {
                                    **(existing.get("metadata") or {}),
                                    "recovered_by_run_id": run_id,
                                },
                            })
                            pub = PublishResult(
                                run_id=run_id, story_id=story_id, platform="threads",
                                status="PUBLISHED", external_id=recovered["external_id"],
                                url=recovered.get("url"),
                                published_at=recovered["published_at"],
                            )
                            return _trace("publisher", state, [
                                msg("publisher", "all", "DONE",
                                    "Recovered previously published Threads post; did not republish."),
                            ]) | {
                                "publication": pub.model_dump(mode="json"),
                                "outcome": "PUBLISHED",
                            }
                    except Exception as exc:
                        print(
                            "  [publisher] publication reconciliation failed: "
                            + type(exc).__name__
                        )
                        recovery_error = (
                            "Publication reconciliation failed ("
                            + type(exc).__name__
                            + "); manual recovery required."
                        )
                        try:
                            from core.tools.database import stories as _db
                            _db.update_publication_result(existing["id"], {
                                "status": "recovery_required",
                                "metadata": {
                                    **(existing.get("metadata") or {}),
                                    "recovery_state": "required",
                                    "recovery_error": recovery_error,
                                },
                            })
                        except Exception as persist_exc:
                            print(
                                "  [publisher] recovery status persistence failed: "
                                + type(persist_exc).__name__
                            )
                    else:
                        recovery_error = "No unique matching Threads post found; refusing to republish."
                        from core.tools.database import stories as _db
                        _db.update_publication_result(existing["id"], {
                            "status": "recovery_required",
                            "metadata": {
                                **(existing.get("metadata") or {}),
                                "recovery_state": "required",
                                "recovery_checked_at": _now_iso(),
                                "recovery_error": recovery_error,
                            },
                        })
                    pub = PublishResult(
                        run_id=run_id, story_id=story_id, platform="threads",
                        status="RECOVERY_REQUIRED", error=recovery_error,
                    )
                    return _trace("publisher", state, [
                        msg("publisher", "all", "BLOCKER",
                            "Prior publication is unresolved; automatic republish blocked."),
                    ]) | {
                        "publication": pub.model_dump(mode="json"),
                        "outcome": "RECOVERY_REQUIRED",
                    }
                pub = PublishResult(
                    run_id=run_id, story_id=story_id,
                    platform="threads", status="DUPLICATE_SKIPPED", url=None,
                )
                return _trace("publisher", state, [
                    msg("publisher", "all", "DONE",
                        "Duplicate publication — skipping."),
                ]) | {
                    "publication": pub.model_dump(mode="json"),
                    "candidate_rejection_reason": "DUPLICATE_STORY",
                    "outcome": "CANDIDATE_REJECTED",
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
                "outcome": "SYSTEM_ERROR",
            }

    reservation_id = None
    reservation_metadata: dict[str, Any] = {}
    if live:
        from hashlib import sha256
        try:
            from core.tools.database import stories as _db
            started_at = _now_iso()
            idempotency_key = sha256(
                f"threads\0{story_id}\0{post.text}".encode("utf-8")
            ).hexdigest()
            reservation_metadata = {
                "run_id": run_id,
                "idempotency_key": idempotency_key,
                "content_sha256": sha256(post.text.encode("utf-8")).hexdigest(),
                "started_at": started_at,
            }
            reservation_id = _db.save_publication_result(story_id, {
                "platform": "threads",
                "status": "publishing",
                "content": post.text,
                "metadata": reservation_metadata,
            })
        except Exception as exc:
            return _trace("publisher", state, [
                msg("publisher", "all", "BLOCKER",
                    "Could not reserve Supabase publication record; publishing blocked."),
            ]) | {
                "publication": PublishResult(
                    run_id=run_id, story_id=story_id, platform="threads",
                    status="BLOCKED_PERSISTENCE_UNAVAILABLE", error=str(exc),
                ).model_dump(mode="json"),
                "outcome": "SYSTEM_ERROR",
            }

    # ── Publish ──
    from core.tools.publishing import publish_threads
    result = publish_threads(post.text, dry_run=dry_run)
    status = result.get("status", "FAILED")
    external_id = result.get("external_id")
    url = result.get("url")
    error = result.get("error")
    diagnostic = result.get("diagnostic") or {}
    print(
        "  [publisher] Threads result: status=" + str(status)
        + ", external_id_present=" + str(bool(external_id))
        + ", diagnostic=" + json.dumps(diagnostic, sort_keys=True)
    )
    if error:
        print("  [publisher] Threads error: " + str(error))
    published_at = _now_iso() if status == "PUBLISHED" and external_id else None
    if status == "PUBLISHED" and not external_id:
        status = "UNKNOWN"
        error = "Threads response did not contain a publication ID; recovery required."

    pub = PublishResult(
        run_id=run_id, story_id=story_id,
        platform="threads", status=status,
        external_id=external_id, url=url, published_at=published_at, error=error,
    )

    # ── Persist publication record ──
    persist_dry_run = not (
        dry_run and state.get("mode") in ("breaking", "reporting")
    )
    if story_id and persist_dry_run:
        try:
            from core.tools.database import stories as _db
            payload = {
                "platform": "threads",
                "status": (
                    "recovery_required"
                    if live and status == "UNKNOWN"
                    else status.lower()
                ),
                "content": post.text,
                "external_post_id": external_id,
                "published_at": published_at,
                "metadata": {
                    **reservation_metadata,
                    "run_id": run_id,
                    "error": error,
                    "recovery_state": "required" if live and status == "UNKNOWN" else None,
                },
            }
            if reservation_id:
                _db.update_publication_result(reservation_id, payload)
            else:
                _db.save_publication_result(story_id, payload)
            if status == "PUBLISHED":
                _db.update_story_status(story_id, "published")
        except Exception as exc:
            print("  [publisher] persist failed: " + type(exc).__name__ + ": " + str(exc))
            if live:
                if status in ("PUBLISHED", "UNKNOWN"):
                    pub.status = (
                        "PERSISTENCE_RECOVERY_REQUIRED"
                        if status == "PUBLISHED" else "RECOVERY_REQUIRED"
                    )
                    pub.error = (
                        "Threads publication outcome and Supabase finalization require "
                        "reconciliation; automatic retry is blocked."
                    )
                else:
                    pub.status = "FAILED"
                    pub.error = (
                        "Supabase could not finalize the known failed Threads request; "
                        "system recovery is required."
                    )
                return _trace("publisher", state, [
                    msg("publisher", "all", "BLOCKER", pub.error),
                ]) | {
                    "publication": pub.model_dump(mode="json"),
                    "outcome": (
                        "RECOVERY_REQUIRED"
                        if status in ("PUBLISHED", "UNKNOWN")
                        else "SYSTEM_ERROR"
                    ),
                }

    if live and status != "PUBLISHED":
        if status == "UNKNOWN":
            pub.status = "RECOVERY_REQUIRED"
            pub.error = error or "Threads publication outcome is uncertain; recovery required."
            outcome = "RECOVERY_REQUIRED"
        else:
            pub.status = "FAILED"
            pub.error = error or "Threads publication failed; no confirmed post was returned."
            outcome = "SYSTEM_ERROR"
        return _trace("publisher", state, [
            msg("publisher", "all", "BLOCKER",
                (
                    "Threads outcome unresolved; reservation retained to prevent duplicate retry."
                    if outcome == "RECOVERY_REQUIRED"
                    else "Threads request failed; stopping the run without another candidate."
                )),
        ]) | {
            "publication": pub.model_dump(mode="json"),
            "outcome": outcome,
        }

    return _trace("publisher", state, [
        msg("publisher", "all", "DONE",
            "Publication: " + status + " (live=" + str(live) + ")"),
    ]) | {
        "publication": pub.model_dump(mode="json"),
        "outcome": (
            "PUBLISHED" if status == "PUBLISHED"
            else "DRY_RUN" if status == "SKIPPED_DRY_RUN"
            else "SYSTEM_ERROR"
        ),
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
    if state.get("outcome") == "CANDIDATE_REJECTED":
        return "__end__"
    return "verification"


def route_after_verification(
    state: TeamState,
) -> Literal["editorial_and_tone", "escalate", "__end__"]:
    if state.get("outcome") == "ESCALATE":
        return "escalate"
    if state.get("outcome") == "CANDIDATE_REJECTED":
        return "__end__"
    return "editorial_and_tone"


def route_after_validation(
    state: TeamState,
) -> Literal["publisher", "writer", "editorial", "escalate", "__end__"]:
    # Short-circuit: any upstream node crashed → escalate, never crash here.
    if state.get("outcome") == "ESCALATE":
        return "escalate"
    if state.get("outcome") == "CANDIDATE_REJECTED":
        return "__end__"
    validation = state.get("validation")
    if not validation:
        # A node failed before validation ran. Escalate cleanly.
        return "escalate"
    if validation["state"] == "PASS":
        return "publisher"

    target = state.get("validation_retry_target")
    if target == "editorial":
        return "editorial"
    if target == "writer":
        return "writer"
    return "__end__"


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
    g.add_node("eligibility_gate", _safe_node(node_eligibility_gate))
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
        "escalate": "escalate",
        "__end__": END,
    })

    # Fan-out from editorial → tone runs in parallel.
    g.add_edge("editorial", "tone")
    # Fan-in to writer — writer waits for both editorial and tone.
    g.add_edge("tone", "writer")

    g.add_edge("writer", "platform_adapter")
    g.add_edge("platform_adapter", "validation")

    g.add_conditional_edges("validation", route_after_validation, {
        "publisher": "eligibility_gate",
        "writer": "writer",
        "editorial": "editorial",
        "escalate": "escalate",
        "__end__": END,
    })

    g.add_edge("eligibility_gate", "publisher")
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
    editorial_memory: dict | None = None,
    result_out: dict[str, str] | None = None,
) -> int:
    import sys
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")

    from core.team.state import new_state
    run_id = f"run_{__import__('uuid').uuid4().hex[:12]}"
    if result_out is not None:
        result_out.update({
            "outcome": "SYSTEM_ERROR",
            "candidate_rejection_reason": "",
        })
    live_enabled = __import__("os").environ.get(
        "NEWSROOM_LIVE", ""
    ).strip().lower() in ("1", "true", "yes")
    if mode not in ("synthetic", "breaking", "reporting"):
        print(f"  [run] ERROR: unsupported execution mode: {mode!r}")
        return 2
    if live_enabled and mode == "synthetic":
        print("  [run] ERROR: live configuration cannot run synthetic stories")
        return 2
    if not dry_run and mode == "synthetic":
        print("  [run] ERROR: live publishing is prohibited for synthetic stories")
        return 2
    if mode == "synthetic":
        try:
            from core.tools.database.client import is_production
            if is_production():
                print("  [run] ERROR: synthetic stories are prohibited with a production database")
                return 2
        except Exception as exc:
            print("  [run] ERROR: database state unavailable; synthetic run blocked: " + str(exc))
            return 2
    if mode in ("breaking", "reporting") and not story_id:
        print("  [run] ERROR: PRODUCTION MODE requires a valid story_id")
        return 2
    # Production modes never synthesize a candidate or fall back to local storage.
    if mode in ("breaking", "reporting"):
        try:
            from core.tools.database import stories as _db
            if not _db.is_production():
                print("  [run] ERROR: production mode requires an initialized Supabase backend")
                return 2
            if not story_id:
                print("  [run] ERROR: production mode requires a real story_id")
                return 2
        except Exception as exc:
            print("  [run] ERROR: production database unavailable: " + str(exc))
            return 2
    if dry_run is False and mode not in ("breaking", "reporting"):
        print("  [run] ERROR: live publication is prohibited outside a production mode")
        return 2

    # ── Load the real story and linked source records for production modes. ──
    production_context = None
    if story_id and mode in ("breaking", "reporting"):
        try:
            from core.tools.database import stories as _db
            _story = _db.get_story(story_id)
            if not _story:
                reason = "production candidate no longer exists in Supabase"
                print("  [run] candidate rejected: " + reason)
                if result_out is not None:
                    result_out.update({
                        "outcome": "CANDIDATE_REJECTED",
                        "candidate_rejection_reason": "STORY_NOT_FOUND",
                    })
                return 1
            _sources = _db.get_story_sources(story_id)
            if not _sources:
                reason = "production candidate has no linked database source records"
                print("  [run] candidate rejected: " + reason)
                if result_out is not None:
                    result_out.update({
                        "outcome": "CANDIDATE_REJECTED",
                        "candidate_rejection_reason": "NO_LINKED_SOURCES",
                    })
                return 1
            production_context = {"story": _story, "sources": _sources}
            topic = _story.get("title", topic) or topic
            print("  [run] loaded real story: " + str(story_id))
            print("        title: " + str(topic)[:80])
            print("        sources: " + str(len(_sources)))
            if not editorial_memory:
                editorial_memory = _db.build_editorial_memory(story_id=story_id, query_title=topic)
        except Exception as _exc:
            print("  [run] ERROR: production context load failed: " + type(_exc).__name__ + ": " + str(_exc))
            return 2

    if not editorial_memory:
        try:
            from core.tools.database import stories as _db
            editorial_memory = _db.build_editorial_memory(story_id=story_id, query_title=topic)
        except Exception:
            pass

    state = new_state(
        run_id=run_id,
        provider=provider,
        model_id=model_id,
        story=production_context["story"] if production_context else None,
        topic=topic,
        mode=mode,
        editorial_memory=editorial_memory,
    )
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


    print("=" * 70)
    print(f"Team graph run — {provider}/{model_id} (topic={topic!r}, dry_run={dry_run})")
    print(f"  mode={mode!r}  story_id={story_id!r}  dry_run={dry_run}")
    print("=" * 70)

    graph = compile_graph()
    final_state: TeamState = graph.invoke(state)

    if dry_run:
        research_result = final_state.get("research") or {}
        verification_result = final_state.get("verification") or {}
        validation_result = final_state.get("validation") or {}
        post_result = final_state.get("post") or {}
        publication_result = final_state.get("publication") or {}
        verification_counts: dict[str, int] = {}
        for item in verification_result.get("verifications") or []:
            status = str(item.get("status") or "unknown")
            verification_counts[status] = verification_counts.get(status, 0) + 1
        post_text = str(post_result.get("text") or "")
        print("[diagnostic] dry-run pipeline:")
        print(
            f"  research evidence={len(research_result.get('evidence') or [])} "
            f"claims={len(research_result.get('claims') or [])}"
        )
        print(f"  verification={verification_counts or 'not reached'}")
        print(f"  writer={'ready' if post_text else 'not reached'} chars={len(post_text)}")
        print(
            "  validation="
            + str(validation_result.get("state") or "not reached")
        )
        print(
            "  would_publish="
            + str(publication_result.get("status") == "SKIPPED_DRY_RUN").lower()
        )

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
    if result_out is not None:
        publication = final_state.get("publication") or {}
        if outcome in (
            "CANDIDATE_REJECTED",
            "PUBLISHED",
        ):
            runner_outcome = str(outcome)
        elif outcome == "PASS":
            runner_outcome = (
                "DRY_RUN"
                if publication.get("status") == "SKIPPED_DRY_RUN"
                else "SYSTEM_ERROR"
            )
        elif outcome == "ESCALATE":
            runner_outcome = "SYSTEM_ERROR"
        elif outcome == "BLOCKED":
            runner_outcome = (
                "RECOVERY_REQUIRED"
                if str(publication.get("status") or "").endswith(
                    "RECOVERY_REQUIRED"
                )
                else "SYSTEM_ERROR"
            )
        else:
            runner_outcome = str(outcome)
        result_out.update({
            "outcome": runner_outcome,
            "candidate_rejection_reason": str(
                final_state.get("candidate_rejection_reason") or ""
            ),
            "publication_status": str(publication.get("status") or ""),
            "external_post_id": str(publication.get("external_id") or ""),
            "publication_error": str(publication.get("error") or ""),
        })
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

    return 0 if outcome in (
        "PASS",
        "PUBLISHED",
        "DRY_RUN",
    ) else 1
