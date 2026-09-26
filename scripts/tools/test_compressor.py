"""Test the deterministic compressor."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.tools.compress import compress_to_limit  # noqa: E402


CASES = [
    ("short enough", "Tesla announced the Model Y today."),
    (
        "long tech news",
        "Tesla announced the Model Y today. The company said it will be "
        "available in Q2 2026. Analysts at Piper Sandler expect the vehicle "
        "to boost revenue by 5 percent in FY27. The announcement came after "
        "months of speculation about the automaker's product roadmap. "
        "Additional details will be shared at the next earnings call. "
        "Separately, the company confirmed that existing orders will be honored.",
    ),
]


def main() -> None:
    failures = 0
    for name, text in CASES:
        out = compress_to_limit(text, limit=200)
        ok = len(out) <= 200
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {len(text)} -> {len(out)} chars")
        print(f"    {out}")
        if not ok:
            failures += 1
    if failures:
        sys.exit(1)
    print("\nALL COMPRESSOR TESTS PASS")


if __name__ == "__main__":
    main()
