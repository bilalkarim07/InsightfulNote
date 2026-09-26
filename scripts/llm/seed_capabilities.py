"""Seed model_capabilities.json from benchmark output."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.llm.persistence import load_capabilities, mark_verified, save_capabilities
from core.llm.registry import build_default_registry


VERIFIED = [
    ("ollama", "gpt-oss:120b", "function_calling", 0.95),
    ("groq", "openai/gpt-oss-120b", "json_schema", 0.98),
    ("groq", "openai/gpt-oss-20b", "json_schema", 0.95),
    ("gemini", "gemini-3-flash-preview", "json_schema", 0.97),
    ("gemini", "gemma-4-26b-a4b-it", "json_schema", 0.90),
    ("gemini", "gemini-3.5-flash-lite", "json_schema", 0.85),
]


def main() -> None:
    reg = build_default_registry()
    load_capabilities(reg)
    for provider, model_id, method, rel in VERIFIED:
        mark_verified(
            reg, provider, model_id,
            basic_invocation=True, pydantic_output=True,
            tool_calling=True, tool_plus_structure=True,
            newsroom_contracts=True,
            reliability_score=rel,
            preferred_structured_method=method,
        )
        print(f"  seeded {provider}/{model_id} -> {method}")
    path = save_capabilities(reg)
    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()
