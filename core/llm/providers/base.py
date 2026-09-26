"""Base provider abstraction — every provider returns OpenAI-compatible kwargs."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    """Configuration for a single LLM provider."""

    name: str
    base_url: str
    api_key_env: str
    default_headers: dict[str, str] = Field(default_factory=dict)

    supports_json_schema: bool = True
    """Whether the provider actually ENFORCES response_format={'type':'json_schema'}.

    Ollama Cloud accepts the parameter but does not apply grammar-constrained
    decoding, so schemas are silently ignored. Set to False for Ollama Cloud.
    """


class BaseProvider(ABC):
    config: ProviderConfig

    @abstractmethod
    def get_client_kwargs(self) -> dict[str, Any]:
        """Return kwargs for LangChain ChatOpenAI instantiation."""
        ...

    def is_configured(self) -> bool:
        key = os.environ.get(self.config.api_key_env, "")
        return bool(key and key.strip())


class ProviderFactory:
    """Registry that maps provider names to provider instances."""

    _registry: dict[str, BaseProvider] = {}

    @classmethod
    def register(cls, provider: BaseProvider) -> None:
        cls._registry[provider.config.name] = provider

    @classmethod
    def get(cls, name: str) -> BaseProvider:
        if name not in cls._registry:
            raise KeyError(
                f"Provider '{name}' not registered. Have: {list(cls._registry)}"
            )
        return cls._registry[name]

    @classmethod
    def all(cls) -> dict[str, BaseProvider]:
        return dict(cls._registry)
