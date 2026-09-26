"""NewsRoom contract test and persist the result."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from schemas.research import ResearchResult  # noqa: E402
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


PROMPT = """
Produce a ResearchResult that EXACTLY matches this JSON shape:

{
  "run_id": "run_test",
  "story_id": "story_test",
  "claims": [
    {
      "claim_id": "claim_1",
      "text": "Company X announced product Y",
      "evidence_ids": ["ev_1"],
      "attribution": "",
      "uncertainty": "",
      "is_forecast": false,
      "is_allegation": false,
      "is_opinion": false
    }
  ],
  "evidence": [
    {
      "evidence_id": "ev_1",
      "source_id": "s1",
      "quote": "Company X announced product Y",
      "url": null,
      "retrieved_at": null,
      "context": ""
    }
  ],
  "missing_information": [],
  "conflicting_claims": [],
  "notes": ""
}

Rules:
- run_id is "run_test"
- story_id is "story_test"
- claims and evidence are SIBLING arrays, not nested
- Claim.evidence_ids references Evidence.evidence_id (a string ID, not an object)
- Do NOT nest evidence inside claims
- Return the object directly, not as a string
""".strip()


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
    kwargs["timeout"] = 120
    try:
        client = ChatOpenAI(**kwargs)
        parsed, method = invoke_structured(
            client, ResearchResult, PROMPT,
            supports_json_schema=prov.config.supports_json_schema,
        )
        assert isinstance(parsed, ResearchResult)
        assert len(parsed.claims) >= 1
        assert len(parsed.evidence) >= 1
        record(provider, model_id, newsroom_contracts=True)
        return f"PASS (method={method})"
    except Exception as exc:  # noqa: BLE001
        return f"FAIL ({type(exc).__name__}: {exc})"


def main() -> None:
    registry = build_default_registry()
    entries = registry.all() if len(sys.argv) < 3 else [registry.get(sys.argv[1], sys.argv[2])]
    print("NewsRoom contract test (ResearchResult)")
    print("=" * 70)
    for entry in entries:
        if entry is None:
            continue
        print(f"[{entry.provider}] {entry.model_id}")
        print(f"  newsroom_contracts: {test(entry.provider, entry.model_id)}")
        print()


if __name__ == "__main__":
    main()
