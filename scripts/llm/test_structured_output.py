"""Test Pydantic structured output and persist the result."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from pydantic import BaseModel  # noqa: E402

from core.llm.providers import (  # noqa: E402
    OllamaProvider, GroqProvider, OpenRouterProvider, GeminiProvider, ProviderFactory,
)
from core.llm.registry import build_default_registry  # noqa: E402
from scripts.llm._structured import invoke_structured  # noqa: E402
from scripts.llm._record import record  # noqa: E402

ProviderFactory.register(OllamaProvider(cloud=True))
ProviderFactory.register(GroqProvider())
ProviderFactory.register(OpenRouterProvider())
ProviderFactory.register(GeminiProvider())


class TestDecision(BaseModel):
    decision: Literal["accept", "reject"]
    reason: str


def test(provider: str, model_id: str) -> str:
    prov = ProviderFactory.get(provider)
    if not prov.is_configured():
        return f"UNVERIFIED (missing {prov.config.api_key_env})"
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        return "UNVERIFIED (langchain-openai not installed)"

    kwargs = prov.get_client_kwargs()
    kwargs["model"] = model_id
    kwargs["timeout"] = 60
    try:
        client = ChatOpenAI(**kwargs)
        result, method = invoke_structured(
            client, TestDecision,
            "A user reports a story with no independent sources. Return your decision.",
            supports_json_schema=prov.config.supports_json_schema,
        )
        assert isinstance(result, TestDecision)
        record(provider, model_id, pydantic_output=True)
        return f"PASS (method={method}, decision={result.decision})"
    except Exception as exc:  # noqa: BLE001
        return f"FAIL ({type(exc).__name__}: {exc})"


def main() -> None:
    registry = build_default_registry()
    entries = registry.all() if len(sys.argv) < 3 else [registry.get(sys.argv[1], sys.argv[2])]
    print("Structured output test")
    print("=" * 70)
    for entry in entries:
        if entry is None:
            continue
        print(f"[{entry.provider}] {entry.model_id}")
        print(f"  structured_output: {test(entry.provider, entry.model_id)}")
        print()


if __name__ == "__main__":
    main()
