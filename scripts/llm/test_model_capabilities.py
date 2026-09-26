"""Test basic model invocation and persist the result."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from core.llm.providers import (  # noqa: E402
    OllamaProvider, GroqProvider, OpenRouterProvider, GeminiProvider, ProviderFactory,
)
from core.llm.registry import build_default_registry  # noqa: E402
from scripts.llm._record import record  # noqa: E402

ProviderFactory.register(OllamaProvider(cloud=True))
ProviderFactory.register(GroqProvider())
ProviderFactory.register(OpenRouterProvider())
ProviderFactory.register(GeminiProvider())


def test_model(provider: str, model_id: str) -> str:
    prov = ProviderFactory.get(provider)
    if not prov.is_configured():
        return f"UNVERIFIED (missing {prov.config.api_key_env})"
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        return "UNVERIFIED (langchain-openai not installed)"

    kwargs = prov.get_client_kwargs()
    kwargs["model"] = model_id
    kwargs["timeout"] = 30
    try:
        client = ChatOpenAI(**kwargs)
        t0 = time.time()
        resp = client.invoke("Reply with the single word: pong")
        dt = (time.time() - t0) * 1000
        text = getattr(resp, "content", str(resp))
        print(f"  -> {text!r}  ({dt:.0f} ms)")
        record(provider, model_id, basic_invocation=True)
        return "PASS"
    except Exception as exc:  # noqa: BLE001
        return f"FAIL ({type(exc).__name__}: {exc})"


def main() -> None:
    registry = build_default_registry()
    if len(sys.argv) == 3:
        entries = [registry.get(sys.argv[1], sys.argv[2])]
    else:
        entries = registry.all()

    print("=" * 70)
    print("Basic model invocation test")
    print("=" * 70)
    for entry in entries:
        if entry is None:
            print("[skip] unknown model")
            continue
        print(f"[{entry.provider}] {entry.model_id}")
        status = test_model(entry.provider, entry.model_id)
        print(f"  basic_invocation: {status}")
        print()


if __name__ == "__main__":
    main()
