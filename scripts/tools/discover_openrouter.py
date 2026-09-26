"""Discover currently valid OpenRouter model IDs.

Hits the /models endpoint, filters for free models, prints their IDs.
Per spec §25: never assume historical IDs are still valid.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

import os


def main() -> None:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        print("OPENROUTER_API_KEY not set")
        return

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    models = data.get("data", [])
    print(f"Total OpenRouter models: {len(models)}")

    # Filter: free (pricing prompt = "0")
    free = []
    for m in models:
        pricing = m.get("pricing") or {}
        prompt_price = pricing.get("prompt", "0")
        try:
            if float(prompt_price) == 0.0:
                free.append(m)
        except (ValueError, TypeError):
            continue

    print(f"Free models: {len(free)}")
    print()
    print("Free models with tool support:")
    print("-" * 70)
    for m in free:
        supported = m.get("supported_parameters") or []
        has_tools = "tools" in supported
        has_json = "response_format" in supported or "structured_outputs" in supported
        if has_tools and has_json:
            print(f"  {m['id']:60} ctx={m.get('context_length')}")

    print()
    print("All free model IDs (for reference):")
    print("-" * 70)
    for m in free:
        print(f"  {m['id']}")


if __name__ == "__main__":
    main()
