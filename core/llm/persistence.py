"""Persist and reload verified model capabilities."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.llm.capabilities.models import CapabilityStatus, ModelCapabilities
from core.llm.registry import ModelRegistry

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CAPABILITIES_FILE = DATA_DIR / "model_capabilities.json"


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def save_capabilities(registry: ModelRegistry) -> Path:
    _ensure_dir()
    payload: dict[str, Any] = {
        "version": 2,
        "models": [cap.model_dump(mode="json") for cap in registry.capabilities.all()],
    }
    CAPABILITIES_FILE.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return CAPABILITIES_FILE


def load_capabilities(registry: ModelRegistry) -> int:
    if not CAPABILITIES_FILE.exists():
        return 0
    raw = json.loads(CAPABILITIES_FILE.read_text(encoding="utf-8"))
    count = 0
    for item in raw.get("models", []):
        try:
            cap = ModelCapabilities.model_validate(item)
        except Exception:
            continue
        entry = registry.get(cap.provider, cap.model)
        if entry is not None:
            entry.capabilities = cap
            registry.capabilities.register(cap)
            count += 1
    return count


def mark_verified(
    registry: ModelRegistry,
    provider: str,
    model_id: str,
    *,
    basic_invocation: bool = False,
    pydantic_output: bool = False,
    tool_calling: bool = False,
    tool_plus_structure: bool = False,
    newsroom_contracts: bool = False,
    reliability_score: float | None = None,
    preferred_structured_method: str | None = None,
) -> None:
    entry = registry.get(provider, model_id)
    if entry is None:
        raise KeyError(f"Unknown model: {provider}/{model_id}")
    if entry.capabilities is None:
        entry.capabilities = ModelCapabilities(provider=provider, model=model_id)

    cap = entry.capabilities
    if basic_invocation:
        cap.verified_basic_invocation = CapabilityStatus.PASS
    if pydantic_output:
        cap.verified_pydantic_output = CapabilityStatus.PASS
    if tool_calling:
        cap.verified_tool_calling = CapabilityStatus.PASS
    if tool_plus_structure:
        cap.verified_tool_plus_structure = CapabilityStatus.PASS
    if newsroom_contracts:
        cap.verified_newsroom_contracts = CapabilityStatus.PASS
    if reliability_score is not None:
        cap.reliability_score = reliability_score
    if preferred_structured_method:
        cap.preferred_structured_method = preferred_structured_method
    registry.capabilities.register(cap)
