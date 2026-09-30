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
    (
        "oversized first sentence",
        "The policy was approved by the White House Office of Science and Technology Policy after months of review.",
    ),
    (
        "multiple complete sentences",
        "A ceasefire agreement was announced after negotiations. Officials said it takes effect tonight. Analysts expect further talks.",
    ),
]


def main() -> None:
    failures = 0
    for name, text in CASES:
        out = compress_to_limit(text, limit=200)
        ok = len(out) <= 200 and not out.endswith(("…", "..."))
        if len(text) > 200:
            ok = ok and out.endswith((".", "!", "?"))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {len(text)} -> {len(out)} chars")
        print(f"    {out}")
        if not ok:
            failures += 1
    oversized = compress_to_limit(
        "The policy was approved by the White House Office of Science and Technology Policy.",
        limit=28,
    )
    if oversized != "The policy was approved.":
        print(f"[FAIL] small limit produced an incomplete ending: {oversized!r}")
        failures += 1
    no_ellipsis = compress_to_limit("The policy was approved…", limit=50)
    if no_ellipsis != "The policy was approved.":
        print(f"[FAIL] short post retained an ellipsis or bad ending: {no_ellipsis!r}")
        failures += 1
    oversized_post = compress_to_limit(
        "Unauthorized access exposed sensitive personnel data, according to a "
        "defense official, while officials continue investigating the incident.",
        limit=70,
    )
    if (
        len(oversized_post) > 70
        or not oversized_post.endswith((".", "!", "?"))
        or oversized_post.endswith(("…", "..."))
    ):
        print(f"[FAIL] oversized post is not a complete natural ending: {oversized_post!r}")
        failures += 1
    if failures:
        sys.exit(1)
    print("\nALL COMPRESSOR TESTS PASS")


if __name__ == "__main__":
    main()
