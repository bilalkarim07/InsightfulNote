"""Test tool + structured output and persist the result."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from langchain_core.tools import tool  # noqa: E402
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


@tool
def get_test_story() -> str:
    """Return a deterministic test story title."""
    return "Test Story: company announces product X on 2026-01-01"


class StoryDecision(BaseModel):
    has_title: Literal["yes", "no"]
    title: str


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
    kwargs["timeout"] = 90
    try:
        client = ChatOpenAI(**kwargs)

        # Step 1: model calls the tool
        bound = client.bind_tools([get_test_story])
        resp = bound.invoke("Call get_test_story and tell me the title.")
        tool_calls = getattr(resp, "tool_calls", None) or []
        if not tool_calls:
            return "FAIL (no tool call emitted in step 1)"

        # Step 2: execute the tool
        tool_result = get_test_story.invoke({})

        # Step 3: structured output from the tool result
        prompt = (
            f"Here is the tool result:\n\n{tool_result}\n\n"
            "Return a StoryDecision with has_title='yes' and the title."
        )
        parsed, method = invoke_structured(
            client, StoryDecision, prompt,
            supports_json_schema=prov.config.supports_json_schema,
        )
        if isinstance(parsed, StoryDecision) and parsed.title:
            record(provider, model_id, tool_plus_structure=True)
            return f"PASS (method={method}, title={parsed.title!r})"
        return "FAIL (unexpected structured output)"
    except Exception as exc:  # noqa: BLE001
        return f"FAIL ({type(exc).__name__}: {exc})"


def main() -> None:
    registry = build_default_registry()
    entries = registry.all() if len(sys.argv) < 3 else [registry.get(sys.argv[1], sys.argv[2])]
    print("Tool + structured output test")
    print("=" * 70)
    for entry in entries:
        if entry is None:
            continue
        print(f"[{entry.provider}] {entry.model_id}")
        print(f"  tool_plus_structure: {test(entry.provider, entry.model_id)}")
        print()


if __name__ == "__main__":
    main()
