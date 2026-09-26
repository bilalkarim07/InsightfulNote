"""OpenRouter provider — OpenAI-compatible endpoint."""
from __future__ import annotations

from typing import Any

from .base import BaseProvider, ProviderConfig

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(BaseProvider):
    def __init__(self) -> None:
        self.config = ProviderConfig(
            name="openrouter",
            base_url=OPENROUTER_BASE_URL,
            api_key_env="OPENROUTER_API_KEY",
        )

    def get_client_kwargs(self) -> dict[str, Any]:
        import os

        return {
            "base_url": self.config.base_url,
            "api_key": os.environ.get("OPENROUTER_API_KEY", ""),
            "model": "",
            "default_headers": {
                "HTTP-Referer": "https://github.com/bilalkarim07/InsightfulNote",
                "X-Title": "NewsRoom",
            },
        }
