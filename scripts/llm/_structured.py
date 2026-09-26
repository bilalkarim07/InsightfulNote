"""Shared helper: invoke a ChatOpenAI-compatible client with structured output.

Tries methods in order:
  1. json_schema       — if provider enforces it
  2. function_calling  — uses tools under the hood (Ollama Cloud path)
  3. json_mode         — last resort

Every method falls back to extracting JSON from the raw response.
Field-name aliases heal a whitelist of common variants.
Schema-aware pruning drops fields that don't belong on a nested object.
"""
from __future__ import annotations

from typing import Any, Type, Union, get_args, get_origin

from pydantic import BaseModel

from core.llm._json import extract_first_json


class StructuredOutputError(RuntimeError):
    """Raised when all structured-output methods fail."""


def _raw_preview(raw: Any, max_len: int = 500) -> str:
    if raw is None:
        return "<none>"
    text = getattr(raw, "content", None)
    if text is None:
        return repr(raw)[:max_len]
    if isinstance(text, list):
        text = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in text
        )
    return str(text)[:max_len]


def _raw_content(raw: Any) -> str:
    if raw is None:
        return ""
    text = getattr(raw, "content", None)
    if text is None:
        return str(raw)
    if isinstance(text, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in text
        )
    return str(text)


# ── Field-name normalization (whitelist only) ───────────────────

_FIELD_ALIASES: dict[str, str] = {
    # Verification
    "note": "notes",
    "reasoning": "notes",
    "explanation": "notes",
    "reason": "notes",
    "verification": "status",
    "verdict": "status",
    "verification_status": "status",
    "verification_result": "status",
    # Research
    "claim": "text",
    "claim_text": "text",
    "statement": "text",
    "sources": "evidence_ids",
    "source_ids": "evidence_ids",
    "evidence": "evidence_ids",
    "supporting_evidence": "evidence_ids",
    # Editorial
    "event": "central_event",
    "allowed_claims": "allowed_claim_ids",
    "blocked_claims": "blocked_claim_ids",
    "must": "must_include",
    "forbidden": "do_not_include",
    # Writing
    "title": "headline",
    "content": "body",
    "text_body": "body",
    "claims_used": "claim_ids",
    # Platform
    "post": "text",
    "post_text": "text",
    "character_count": "char_count",
    "chars": "char_count",
    # Selection
    "decision": "state",
    "priority_score": "priority",
    # Tone
    "tone_type": "tone",
}


def _normalize(data: Any) -> Any:
    if isinstance(data, dict):
        normalized: dict[str, Any] = {}
        for k, v in data.items():
            new_key = _FIELD_ALIASES.get(k, k)
            if new_key in normalized and k != new_key:
                continue
            normalized[new_key] = _normalize(v)
        return normalized
    if isinstance(data, list):
        return [_normalize(item) for item in data]
    return data


# ── Schema-aware pruning ────────────────────────────────────────

def _inner_model(annotation: Any) -> Type[BaseModel] | None:
    """If the annotation is `X` or `list[X]` or `Optional[X]`, return X if it's a BaseModel."""
    if annotation is None:
        return None
    origin = get_origin(annotation)
    if origin is Union:
        for arg in get_args(annotation):
            inner = _inner_model(arg)
            if inner is not None:
                return inner
        return None
    if origin is list or origin is tuple or origin is set:
        args = get_args(annotation)
        if args:
            return _inner_model(args[0])
        return None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _prune_to_schema(schema: Type[BaseModel], data: Any) -> Any:
    """Recursively drop keys not present in the Pydantic schema.

    LLMs often add extra fields to nested objects (created_at, is_forecast,
    confidence) that belong on other contracts. We drop them silently because
    the top-level validation already ensures the correct fields are present.
    """
    if isinstance(data, list):
        return [_prune_to_schema(schema, item) for item in data]
    if not isinstance(data, dict):
        return data

    model_fields = schema.model_fields
    out: dict[str, Any] = {}
    for k, v in data.items():
        if k not in model_fields:
            continue
        sub = _inner_model(model_fields[k].annotation)
        if sub is not None:
            out[k] = _prune_to_schema(sub, v)
        else:
            out[k] = v
    return out


def _try_parse(schema: Type[BaseModel], raw: Any) -> BaseModel | None:
    text = _raw_content(raw)
    if not text:
        return None
    data = extract_first_json(text)
    if data is None:
        return None
    data = _normalize(data)
    data = _prune_to_schema(schema, data)
    try:
        return schema.model_validate(data)
    except Exception:  # noqa: BLE001
        return None


def invoke_structured(
    client: Any,
    schema: Type[BaseModel],
    prompt: str,
    *,
    supports_json_schema: bool = True,
) -> tuple[BaseModel, str]:
    errors: dict[str, str] = {}
    raw_previews: dict[str, str] = {}

    methods: list[str] = []
    if supports_json_schema:
        methods.append("json_schema")
    methods.extend(["function_calling", "json_mode"])

    for method in methods:
        try:
            if method == "json_mode":
                out = client.with_structured_output(
                    schema, method="json_mode", include_raw=True,
                ).invoke(
                    prompt + "\n\nRespond with valid JSON only, no markdown fences."
                )
            else:
                out = client.with_structured_output(
                    schema, method=method, include_raw=True,
                ).invoke(prompt)

            raw = out.get("raw") if isinstance(out, dict) else None
            parsed = out.get("parsed") if isinstance(out, dict) else out
            raw_previews[method] = _raw_preview(raw)

            if parsed is not None and isinstance(parsed, schema):
                return parsed, method

            recovered = _try_parse(schema, raw)
            if recovered is not None:
                return recovered, f"{method}+recovered"

            errors[method] = "native parsed=None, raw recovery failed"
        except Exception as exc:  # noqa: BLE001
            errors[method] = f"{type(exc).__name__}: {str(exc)[:200]}"
            continue

    detail_lines = [f"  {m}: {errors.get(m, 'unknown')}" for m in methods]
    raw_lines = [f"  {m} raw: {raw_previews.get(m, '<no raw>')}" for m in methods]
    raise StructuredOutputError(
        "All structured-output methods failed.\n"
        + "\n".join(detail_lines)
        + "\n--- raw outputs ---\n"
        + "\n".join(raw_lines)
    )
