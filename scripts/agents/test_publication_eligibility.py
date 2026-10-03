"""Checks that publication has no quota gate while breaking eligibility remains."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.team.graph import compile_graph, node_eligibility_gate  # noqa: E402


def main() -> int:
    graph = compile_graph()
    nodes = graph.get_graph().nodes
    assert "eligibility_gate" in nodes
    assert "quota_gate" not in nodes

    quota_settings = {
        "NEWSROOM_MAX_PER_DAY": "0",
        "NEWSROOM_MIN_HOURS_BETWEEN": "999",
        "NEWSROOM_ACTIVE_START": "23",
        "NEWSROOM_ACTIVE_END": "23",
    }
    original = {key: os.environ.get(key) for key in quota_settings}
    try:
        os.environ.update(quota_settings)
        result = node_eligibility_gate({
            "outcome": "RUNNING",
            "mode": "reporting",
            "messages": [],
        })
        assert result.get("outcome") == "RUNNING"
        assert any(
            message.get("to_agent") == "publisher"
            for message in result.get("messages", [])
        )
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    print("Publication eligibility checks — ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
