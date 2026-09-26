"""Ollama Cloud provider.

CRITICAL: Ollama Cloud does NOT enforce json_schema. It accepts
response_format={'type':'json_schema'} without error but returns plain text.
Use function_calling or json_mode for structured output.

Reference: https://docs.ollama.com/capabilities/structured-outputs
"""
from __future__ import annotations

import os
from typing import Any

from .base import BaseProvider, ProviderConfig

OLLAMA_CLOUD_BASE_URL = "https://ollama.com/v1"
OLLAMA_LOCAL_BASE_URL = "http://localhost:11434/v1"


class OllamaProvider(BaseProvider):
    """Ollama provider supporting both cloud and local endpoints.

    Cloud access requires OLLAMA_API_KEY (Bearer token).
    Local access requires no API key and DOES enforce json_schema.
    """

    def __init__(self, *, cloud: bool = True) -> None:
        base_url = OLLAMA_CLOUD_BASE_URL if cloud else OLLAMA_LOCAL_BASE_URL
        self.cloud = cloud
        self.config = ProviderConfig(
            name="ollama",
            base_url=base_url,
            api_key_env="OLLAMA_API_KEY",
            supports_json_schema=not cloud,
        )

    def get_client_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "base_url": self.config.base_url,
            "model": "",
        }
        if self.cloud:
            kwargs["api_key"] = os.environ.get("OLLAMA_API_KEY", "") or "ollama-cloud"
        else:
            kwargs["api_key"] = "ollama-local"
        return kwargs
