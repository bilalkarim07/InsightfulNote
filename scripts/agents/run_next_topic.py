"""SYNTHETIC TESTING ONLY — DO NOT USE FOR PRODUCTION.

This runner drives the team graph from data/topic_queue.json.
Retained for local development, contract testing, and model
benchmarking only.

Production publishing goes through:
  scripts/run_news_ingestion.py         (ingestion)
  scripts/agents/run_breaking_news.py   (24/7 breaking)
  scripts/agents/run_evening_reporting.py (evening)

No GitHub Actions workflow calls this file.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._bootstrap import *  # noqa: F401,F403,E402

from core.team.graph import run_team  # noqa: E402

QUEUE = ROOT / "data" / "topic_queue.json"


def pop_topic() -> str | None:
    if not QUEUE.exists():
        return None
    data = json.loads(QUEUE.read_text(encoding="utf-8"))
    pending = data.get("pending") or []
    if not pending:
        return None
    topic = pending.pop(0)
    consumed = data.get("consumed") or []
    consumed.append(topic)
    data["pending"] = pending
    data["consumed"] = consumed[-50:]
    QUEUE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return topic


def main() -> None:
    provider = sys.argv[1] if len(sys.argv) > 1 else "ollama"
    model_id = sys.argv[2] if len(sys.argv) > 2 else "gpt-oss:120b"
    topic = pop_topic()
    if not topic:
        print("No pending topics in data/topic_queue.json")
        sys.exit(0)
    print(f"Running team graph on: {topic!r}")
    rc = run_team(provider, model_id, topic=topic)
    # If quota deferred the run, put the topic back at the front of the queue.
    if rc == 1:  # non-PASS exit; check last snapshot for DEFERRED_QUOTA
        try:
            import glob, os
            snaps = sorted(glob.glob(str(ROOT / "data" / "runs" / "*.json")),
                           key=os.path.getmtime, reverse=True)
            if snaps:
                last = json.loads(Path(snaps[0]).read_text(encoding="utf-8"))
                if last.get("outcome") == "DEFERRED_QUOTA":
                    data = json.loads(QUEUE.read_text(encoding="utf-8"))
                    data["pending"].insert(0, topic)
                    if data["consumed"] and data["consumed"][-1] == topic:
                        data["consumed"].pop()
                    QUEUE.write_text(json.dumps(data, indent=2), encoding="utf-8")
                    print(f"Requeued {topic!r} (quota deferred)")
        except Exception as exc:
            print(f"Requeue check failed: {exc}")
    sys.exit(rc)


if __name__ == "__main__":
    main()