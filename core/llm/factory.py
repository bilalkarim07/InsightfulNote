"""LangChain model factory."""
from __future__ import annotations

import os
from typing import Any

from core.llm.registry import ModelEntry


class ModelFactoryError(RuntimeError):
    pass


def _resolve_api_key(entry: ModelEntry) -> str:
    key = os.environ.get(entry.api_key_env, "")
    if not key:
        if entry.provider == "ollama":
            return ""
        raise ModelFactoryError(f"Missing API key: {entry.api_key_env}")
    return key


def get_chat_model(entry: ModelEntry, *, temperature: float = 0.0, timeout: int = 120) -> Any:
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ModelFactoryError(
            "langchain-openai is required. Install: pip install langchain-openai"
        ) from exc

    api_key = _resolve_api_key(entry)
    kwargs: dict[str, Any] = {
        "model": entry.model_id,
        "base_url": entry.base_url,
        "temperature": temperature,
        "timeout": timeout,
    }
    if entry.provider == "ollama":
        kwargs["api_key"] = api_key or "ollama-local"
    else:
        kwargs["api_key"] = api_key
    return ChatOpenAI(**kwargs)


def structured_method_for(entry: ModelEntry) -> str:
    cap = entry.capabilities
    if cap and cap.preferred_structured_method:
        return cap.preferred_structured_method
    if entry.provider == "ollama" and "ollama.com" in entry.base_url:
        return "function_calling"
    return "json_schema"


def supports_json_schema(entry: ModelEntry) -> bool:
    if entry.provider == "ollama" and "ollama.com" in entry.base_url:
        return False
    return True
