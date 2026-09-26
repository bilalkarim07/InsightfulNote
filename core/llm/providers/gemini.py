"""Gemini provider — OpenAI-compatible endpoint."""
from __future__ import annotations

from typing import Any

from .base import BaseProvider, ProviderConfig

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class GeminiProvider(BaseProvider):
    def __init__(self) -> None:
        self.config = ProviderConfig(
            name="gemini",
            base_url=GEMINI_BASE_URL,
            api_key_env="GEMINI_API_KEY",
        )

    def get_client_kwargs(self) -> dict[str, Any]:
        import os

        return {
            "base_url": self.config.base_url,
            "api_key": os.environ.get("GEMINI_API_KEY", ""),
            "model": "",
        }
