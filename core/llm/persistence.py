"""Persist and reload verified model capabilities.

Two files:
  - data/model_capabilities.json            (local, gitignored)
  - data/model_capabilities_manifest.json   (committed)

On GitHub Actions, the local JSON is absent. The manifest is used instead
so that a fresh runner can route to verified models without re-benchmarking.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from core.llm.capabilities.models import CapabilityStatus, ModelCapabilities
from core.llm.registry import ModelRegistry

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
LOCAL_FILE = DATA_DIR / "model_capabilities.json"
MANIFEST_FILE = DATA_DIR / "model_capabilities_manifest.json"


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def save_capabilities(registry: ModelRegistry) -> Path:
    """Write locally benchmarked state. This file is gitignored."""
    _ensure_dir()
    payload: dict[str, Any] = {
        "version": 2,
        "models": [cap.model_dump(mode="json") for cap in registry.capabilities.all()],
    }
    LOCAL_FILE.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return LOCAL_FILE


def _manifest_to_capability(item: dict) -> ModelCapabilities:
    """Convert a manifest row into a ModelCapabilities object."""
    def st(v: str) -> CapabilityStatus:
        try:
            return CapabilityStatus(v)
        except ValueError:
            return CapabilityStatus.UNVERIFIED
    return ModelCapabilities(
        provider=item["provider"],
        model=item["model"],
        verified_basic_invocation=st(item.get("basic_invocation", "UNVERIFIED")),
        verified_pydantic_output=st(item.get("structured_output", "UNVERIFIED")),
        verified_tool_calling=st(item.get("tool_calling", "UNVERIFIED")),
        verified_tool_plus_structure=st(item.get("tool_plus_structure", "UNVERIFIED")),
        verified_newsroom_contracts=st(item.get("newsroom_contracts", "UNVERIFIED")),
        preferred_structured_method=item.get("preferred_structured_method"),
        reliability_score=item.get("reliability_score"),
        notes=f"from manifest, tested_at={item.get('tested_at', '?')}",
    )


def load_capabilities(registry: ModelRegistry) -> int:
    """Load local benchmarks first, fall back to the committed manifest."""
    count = 0
    if LOCAL_FILE.exists():
        try:
            raw = json.loads(LOCAL_FILE.read_text(encoding="utf-8"))
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
        except Exception:
            pass
    if count > 0:
        return count
    # Fall back to committed manifest (GitHub Actions path).
    if MANIFEST_FILE.exists():
        try:
            raw = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
            for item in raw.get("models", []):
                try:
                    cap = _manifest_to_capability(item)
                except Exception:
                    continue
                entry = registry.get(cap.provider, cap.model)
                if entry is not None:
                    entry.capabilities = cap
                    registry.capabilities.register(cap)
                    count += 1
        except Exception:
            pass
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