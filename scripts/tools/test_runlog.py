"""Test the run log."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.observability.runlog import stage, summarize, read_log  # noqa: E402


def main() -> None:
    with stage(run_id="run_test", agent="research", provider="ollama",
               model_id="gpt-oss:120b") as s:
        s["metadata"]["evidence_chars"] = 1384

    with stage(run_id="run_test", agent="verification", provider="ollama",
               model_id="gpt-oss:120b") as s:
        s["status"] = "PASS"
        s["metadata"]["claims_verified"] = 3

    with stage(run_id="run_test", agent="writer", provider="ollama",
               model_id="gpt-oss:120b") as s:
        s["status"] = "FAILED"
        s["error"] = "simulated failure"

    rows = read_log(limit=5)
    print(f"Wrote {len(rows)} recent rows")
    summary = summarize()
    print(f"Summary: {summary}")
    assert summary["total_rows"] >= 3
    print("\nRUN LOG OK")


if __name__ == "__main__":
    main()
