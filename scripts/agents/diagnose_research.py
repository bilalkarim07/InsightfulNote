"""Show exactly what Research sees when it runs.

Runs the same search queries the graph would, prints the raw results,
then asks the model to produce a ResearchResult and shows the raw output
if it fails to produce claims.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from core.tools.search import search_web, real_tools_status  # noqa: E402
from core.llm.factory import get_chat_model  # noqa: E402
from core.llm.persistence import load_capabilities  # noqa: E402
from core.llm.providers import (  # noqa: E402
    OllamaProvider, GroqProvider, OpenRouterProvider, GeminiProvider, ProviderFactory,
)
from core.llm.registry import build_default_registry  # noqa: E402
from scripts.llm._structured import invoke_structured  # noqa: E402
from schemas.research import ResearchResult  # noqa: E402

ProviderFactory.register(OllamaProvider(cloud=True))
ProviderFactory.register(GroqProvider())
ProviderFactory.register(OpenRouterProvider())
ProviderFactory.register(GeminiProvider())


def main() -> None:
    topic = sys.argv[1] if len(sys.argv) > 1 else "Tesla Model Y"
    provider = sys.argv[2] if len(sys.argv) > 2 else "ollama"
    model_id = sys.argv[3] if len(sys.argv) > 3 else "gpt-oss:120b"

    print("=" * 70)
    print(f"Research diagnostic — topic={topic!r}")
    print(f"  search status: {real_tools_status()}")
    print("=" * 70)

    # 1. Run the search
    print(f"\n[1] Running search_web({topic!r})")
    try:
        raw = search_web.invoke({"query": topic})
    except Exception as exc:  # noqa: BLE001
        print(f"  search raised: {type(exc).__name__}: {exc}")
        return

    print(f"  raw type:   {type(raw).__name__}")
    print(f"  raw length: {len(str(raw))}")
    print(f"\n  first 800 chars:")
    print("  " + str(raw)[:800].replace("\n", "\n  "))

    # 2. Try the model call directly
    print(f"\n[2] Asking {provider}/{model_id} to produce ResearchResult")
    registry = build_default_registry()
    load_capabilities(registry)
    entry = registry.get(provider, model_id)
    if entry is None:
        print("  model not in registry")
        return
    client = get_chat_model(entry, timeout=180)

    run_id, story_id = "run_diag", "story_diag"
    prompt = f"""
You are the Research Agent. Produce a ResearchResult with
run_id="{run_id}", story_id="{story_id}".

Topic: {topic}

Evidence collected by search:
- source_id="s1", quote={str(raw)!r}

Rules:
- ONLY create claims directly supported by the evidence above.
- If the evidence does NOT support any factual claim about the topic,
  produce ZERO claims and fill missing_information.

Return JSON matching ResearchResult exactly:
{{
  "run_id": "{run_id}",
  "story_id": "{story_id}",
  "claims": [],
  "evidence": [],
  "missing_information": [],
  "conflicting_claims": [],
  "notes": ""
}}
""".strip()

    try:
        parsed, method = invoke_structured(
            client, ResearchResult, prompt,
            supports_json_schema=(provider != "ollama"),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  structured call raised: {type(exc).__name__}: {str(exc)[:500]}")
        return

    print(f"  method:  {method}")
    print(f"  claims:  {len(parsed.claims)}")
    for c in parsed.claims:
        print(f"    • {c.claim_id}: {c.text}")
    print(f"  evidence: {len(parsed.evidence)}")
    for e in parsed.evidence:
        print(f"    • {e.evidence_id}: {e.quote[:100]}")
    print(f"  missing_information: {parsed.missing_information}")
    print(f"  notes: {parsed.notes}")

    # Snapshot
    out = Path("data/diagnostics")
    out.mkdir(parents=True, exist_ok=True)
    (out / "research_diag.json").write_text(
        json.dumps({
            "topic": topic,
            "raw_search": str(raw),
            "model_output": parsed.model_dump(mode="json"),
        }, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\n  snapshot: data/diagnostics/research_diag.json")


if __name__ == "__main__":
    main()
