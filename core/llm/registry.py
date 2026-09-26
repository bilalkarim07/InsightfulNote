"""Model registry."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.llm.capabilities.models import CapabilityRegistry, ModelCapabilities


@dataclass
class ModelEntry:
    provider: str
    model_id: str
    display_name: str
    base_url: str
    api_key_env: str
    priority: int = 100
    enabled: bool = True
    context_window: Optional[int] = None
    capabilities: Optional[ModelCapabilities] = None
    notes: str = ""


class ModelRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, ModelEntry] = {}
        self.capabilities = CapabilityRegistry()

    def _key(self, provider: str, model_id: str) -> str:
        return f"{provider}/{model_id}"

    def register(self, entry: ModelEntry) -> None:
        self._entries[self._key(entry.provider, entry.model_id)] = entry
        if entry.capabilities:
            self.capabilities.register(entry.capabilities)

    def get(self, provider: str, model_id: str) -> Optional[ModelEntry]:
        return self._entries.get(self._key(provider, model_id))

    def all(self, *, enabled_only: bool = True) -> list[ModelEntry]:
        entries = list(self._entries.values())
        if enabled_only:
            entries = [e for e in entries if e.enabled]
        return sorted(entries, key=lambda e: e.priority)

    def eligible(self, *required: str) -> list[ModelEntry]:
        keys = {self._key(c.provider, c.model) for c in self.capabilities.eligible_for(*required)}
        return [e for e in self.all() if self._key(e.provider, e.model_id) in keys]


def build_default_registry() -> ModelRegistry:
    reg = ModelRegistry()

    for model_id, priority, enabled, note in [
        ("gpt-oss:120b", 1, True, "verified: function_calling"),
        ("gpt-oss:20b", 3, True, "unverified"),
        ("nemotron-3-super", 5, True, "unverified"),
        ("nemotron-3-ultra", 5, True, "unverified"),
        ("gemma4:31b", 6, True, "unverified"),
        ("nemotron-3-nano:30b", 6, True, "unverified"),
    ]:
        reg.register(ModelEntry(
            provider="ollama", model_id=model_id, display_name=f"Ollama {model_id}",
            base_url="https://ollama.com/v1", api_key_env="OLLAMA_API_KEY",
            priority=priority, enabled=enabled, notes=note,
            capabilities=ModelCapabilities(provider="ollama", model=model_id),
        ))

    for model_id, priority, note in [
        ("openai/gpt-oss-120b", 2, "verified: json_schema"),
        ("openai/gpt-oss-20b", 4, "verified: json_schema"),
    ]:
        reg.register(ModelEntry(
            provider="groq", model_id=model_id, display_name=f"Groq {model_id}",
            base_url="https://api.groq.com/openai/v1", api_key_env="GROQ_API_KEY",
            priority=priority, notes=note,
            capabilities=ModelCapabilities(provider="groq", model=model_id),
        ))

    for model_id, priority, note in [
        ("gemini-3-flash-preview", 7, "verified: json_schema (1.4s)"),
        ("gemma-4-26b-a4b-it", 8, "verified: json_schema (2.8s, emits <thought>)"),
        ("gemini-3.1-flash-lite-preview", 9, "unverified"),
        ("gemini-flash-lite-latest", 9, "unverified"),
        ("gemini-3.5-flash-lite", 15, "verified: json_schema (~24s)"),
    ]:
        reg.register(ModelEntry(
            provider="gemini", model_id=model_id, display_name=f"Gemini {model_id}",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key_env="GEMINI_API_KEY", priority=priority, notes=note,
            capabilities=ModelCapabilities(provider="gemini", model=model_id),
        ))

    for model_id, priority, enabled, note in [
        ("inclusionai/ling-3.0-flash-fin-free", 16, True, "unverified"),
        ("inclusionai/ling-3.0-flash-sante-free", 16, True, "unverified"),
        ("nex-agi/nex-n2.5-mini-free", 99, False, "DISABLED: 400 invalid ID"),
        ("nex-agi/nex-n2.5-pro-free", 99, False, "DISABLED: 400 invalid ID"),
    ]:
        reg.register(ModelEntry(
            provider="openrouter", model_id=model_id, display_name=f"OpenRouter {model_id}",
            base_url="https://openrouter.ai/api/v1", api_key_env="OPENROUTER_API_KEY",
            priority=priority, enabled=enabled, notes=note,
            capabilities=ModelCapabilities(provider="openrouter", model=model_id),
        ))

    return reg
