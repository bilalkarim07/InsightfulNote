"""Test tool calling and persist the result."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from langchain_core.tools import tool  # noqa: E402

from core.llm.providers import (  # noqa: E402
    OllamaProvider, GroqProvider, OpenRouterProvider, GeminiProvider, ProviderFactory,
)
from core.llm.registry import build_default_registry  # noqa: E402
from scripts.llm._record import record  # noqa: E402

ProviderFactory.register(OllamaProvider(cloud=True))
ProviderFactory.register(GroqProvider())
ProviderFactory.register(OpenRouterProvider())
ProviderFactory.register(GeminiProvider())


@tool
def get_test_story() -> str:
    """Return a deterministic test story title."""
    return "Test Story: company announces product X on 2026-01-01"


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
        bound = client.bind_tools([get_test_story])
        resp = bound.invoke("Call get_test_story and tell me the title.")
        tool_calls = getattr(resp, "tool_calls", None) or []
        if not tool_calls:
            return "FAIL (no tool call emitted)"
        name = tool_calls[0].get("name") if isinstance(tool_calls[0], dict) else tool_calls[0].name
        if name != "get_test_story":
            return f"FAIL (wrong tool: {name})"
        record(provider, model_id, tool_calling=True)
        return "PASS"
    except Exception as exc:  # noqa: BLE001
        return f"FAIL ({type(exc).__name__}: {exc})"


def main() -> None:
    registry = build_default_registry()
    entries = registry.all() if len(sys.argv) < 3 else [registry.get(sys.argv[1], sys.argv[2])]
    print("Tool calling test")
    print("=" * 70)
    for entry in entries:
        if entry is None:
            continue
        print(f"[{entry.provider}] {entry.model_id}")
        print(f"  tool_calling: {test(entry.provider, entry.model_id)}")
        print()


if __name__ == "__main__":
    main()
