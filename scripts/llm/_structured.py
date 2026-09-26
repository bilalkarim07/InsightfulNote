"""Shared helper: invoke a ChatOpenAI-compatible client with structured output.

Cascade order:
  1. preferred_method (verified)    - if provided
  2. json_schema                    - if provider enforces it
  3. function_calling               - tools under the hood
  4. json_mode                      - last resort

Handles:
  - wrapped objects
  - bare lists (auto-wrapped into the schema's single list field)
  - missing run_id/story_id (auto-filled from context)
  - common field aliases (verdict -> status, note -> notes, ...)
  - extra fields on nested models (pruned)
"""
from __future__ import annotations

import json
from typing import Any, Type, Union, get_args, get_origin

from pydantic import BaseModel

from core.llm._json import (
    extract_first_json,
    strip_markdown_fences,
    strip_thinking_blocks,
)


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


_FIELD_ALIASES: dict[str, str] = {
    "note": "notes", "reasoning": "notes", "explanation": "notes", "reason": "notes",
    "verification": "status", "verdict": "status",
    "verification_status": "status", "verification_result": "status",
    "claim": "text", "claim_text": "text", "statement": "text",
    "sources": "evidence_ids", "source_ids": "evidence_ids",
    "evidence": "evidence_ids", "supporting_evidence": "evidence_ids",
    "event": "central_event",
    "allowed_claims": "allowed_claim_ids", "blocked_claims": "blocked_claim_ids",
    "must": "must_include", "forbidden": "do_not_include",
    "title": "headline", "content": "body", "text_body": "body", "article": "body", "summary": "body", "text": "body",
    "claims_used": "claim_ids",
    "post": "text", "post_text": "text",
    "character_count": "char_count", "chars": "char_count",
    "decision": "state", "priority_score": "priority",
    "tone_type": "tone",
}


def _normalize(data: Any, schema: Any = None) -> Any:
    """Rename common LLM field-name variants.

    Schema-aware: if the target schema has a field with the original name,
    do NOT alias it. This lets us alias `text -> body` globally without
    breaking PlatformPost (which uses `text` as a real field).
    """
    if isinstance(data, dict):
        normalized: dict[str, Any] = {}
        schema_fields = set(schema.model_fields.keys()) if schema is not None else set()
        for k, v in data.items():
            if schema is not None and k in schema_fields:
                new_key = k
            else:
                new_key = _FIELD_ALIASES.get(k, k)
            if new_key in normalized and k != new_key:
                continue
            normalized[new_key] = _normalize(v)
        return normalized
    if isinstance(data, list):
        return [_normalize(item) for item in data]
    return data


def _inner_model(annotation: Any) -> Type[BaseModel] | None:
    if annotation is None:
        return None
    origin = get_origin(annotation)
    if origin is Union:
        for arg in get_args(annotation):
            inner = _inner_model(arg)
            if inner is not None:
                return inner
        return None
    if origin in (list, tuple, set):
        args = get_args(annotation)
        return _inner_model(args[0]) if args else None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _prune_to_schema(schema: Type[BaseModel], data: Any) -> Any:
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
        out[k] = _prune_to_schema(sub, v) if sub is not None else v
    return out


def _list_field_names(schema: Type[BaseModel]) -> list[str]:
    return [
        name for name, info in schema.model_fields.items()
        if get_origin(info.annotation) in (list, tuple, set)
    ]


def _try_parse(
    schema: Type[BaseModel],
    raw: Any,
    context: dict | None = None,
) -> BaseModel | None:
    """Parse an LLM response into the schema."""
    text = _raw_content(raw)
    if not text:
        return None

    stripped = strip_markdown_fences(strip_thinking_blocks(text))

    data = None
    try:
        data = json.loads(stripped)
    except Exception:
        pass
    if data is None:
        data = extract_first_json(stripped)
    if data is None:
        return None

    if isinstance(data, list):
        list_fields = _list_field_names(schema)
        if len(list_fields) == 1:
            wrapped: dict[str, Any] = {list_fields[0]: data}
            if context:
                for k, v in context.items():
                    if k in schema.model_fields:
                        wrapped.setdefault(k, v)
            data = wrapped
        else:
            return None

    data = _normalize(data, schema=schema)
    data = _prune_to_schema(schema, data)

    if context and isinstance(data, dict):
        for key in ("run_id", "story_id"):
            if key in schema.model_fields and not data.get(key):
                if key in context and context[key]:
                    data[key] = context[key]

    try:
        return schema.model_validate(data)
    except Exception:
        return None


def invoke_structured(
    client: Any,
    schema: Type[BaseModel],
    prompt: str,
    *,
    supports_json_schema: bool = True,
    preferred_method: str | None = None,
    context: dict | None = None,
) -> tuple[BaseModel, str]:
    """Return (parsed_model, method_used)."""
    errors: dict[str, str] = {}
    raw_previews: dict[str, str] = {}

    methods: list[str] = []
    if preferred_method:
        methods.append(preferred_method)
    if supports_json_schema and "json_schema" not in methods:
        methods.append("json_schema")
    for m in ("function_calling", "json_mode"):
        if m not in methods:
            methods.append(m)

    suffix = chr(10) + chr(10) + "Respond with valid JSON only, no markdown fences."

    for method in methods:
        try:
            if method == "json_mode":
                out = client.with_structured_output(
                    schema, method="json_mode", include_raw=True,
                ).invoke(prompt + suffix)
            else:
                out = client.with_structured_output(
                    schema, method=method, include_raw=True,
                ).invoke(prompt)

            raw = out.get("raw") if isinstance(out, dict) else None
            parsed = out.get("parsed") if isinstance(out, dict) else out
            raw_previews[method] = _raw_preview(raw)

            if parsed is not None and isinstance(parsed, schema):
                return parsed, method

            recovered = _try_parse(schema, raw, context=context)
            if recovered is not None:
                return recovered, f"{method}+recovered"

            errors[method] = "native parsed=None, raw recovery failed"
        except Exception as exc:
            errors[method] = f"{type(exc).__name__}: {str(exc)[:200]}"
            continue

    detail_lines = [f"  {m}: {errors.get(m, 'unknown')}" for m in methods]
    raw_lines = [f"  {m} raw: {raw_previews.get(m, '<no raw>')}" for m in methods]
    raise StructuredOutputError(
        "All structured-output methods failed." + chr(10)
        + chr(10).join(detail_lines)
        + chr(10) + "--- raw outputs ---" + chr(10)
        + chr(10).join(raw_lines)
    )
