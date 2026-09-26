"""Shared benchmark helper - persists verified capabilities."""
from __future__ import annotations

from core.llm.persistence import mark_verified, save_capabilities, load_capabilities
from core.llm.registry import build_default_registry


def record(
    provider: str,
    model_id: str,
    *,
    basic_invocation: bool | None = None,
    pydantic_output: bool | None = None,
    tool_calling: bool | None = None,
    tool_plus_structure: bool | None = None,
    newsroom_contracts: bool | None = None,
    reliability_score: float | None = None,
    preferred_structured_method: str | None = None,
) -> None:
    registry = build_default_registry()
    load_capabilities(registry)

    kwargs = {}
    if basic_invocation:    kwargs["basic_invocation"] = True
    if pydantic_output:     kwargs["pydantic_output"] = True
    if tool_calling:        kwargs["tool_calling"] = True
    if tool_plus_structure: kwargs["tool_plus_structure"] = True
    if newsroom_contracts:  kwargs["newsroom_contracts"] = True
    if reliability_score is not None:
        kwargs["reliability_score"] = reliability_score
    if preferred_structured_method:
        kwargs["preferred_structured_method"] = preferred_structured_method
    if not kwargs:
        return

    mark_verified(registry, provider, model_id, **kwargs)
    path = save_capabilities(registry)
    print(f"  [persisted] {provider}/{model_id} -> {path}")
