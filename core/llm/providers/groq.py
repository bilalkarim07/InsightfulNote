"""Groq provider — OpenAI-compatible endpoint."""
from __future__ import annotations

from typing import Any

from .base import BaseProvider, ProviderConfig

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqProvider(BaseProvider):
    def __init__(self) -> None:
        self.config = ProviderConfig(
            name="groq",
            base_url=GROQ_BASE_URL,
            api_key_env="GROQ_API_KEY",
        )

    def get_client_kwargs(self) -> dict[str, Any]:
        import os

        return {
            "base_url": self.config.base_url,
            "api_key": os.environ.get("GROQ_API_KEY", ""),
            "model": "",
        }
