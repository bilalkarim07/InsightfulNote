"""Router report - actual routing decisions per task with reasons."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.llm.persistence import load_capabilities  # noqa: E402
from core.llm.registry import build_default_registry  # noqa: E402
from core.llm.routing.router import AgentTask, ModelRouter  # noqa: E402


def reason_for(entry, requirements):
    cap = entry.capabilities
    rel = cap.reliability_score if cap else None
    parts = [f"priority={entry.priority}"]
    if rel is not None:
        parts.append(f"reliability={rel:.2f}")
    parts.append("verified=" + ",".join(requirements))
    return "; ".join(parts)


def main() -> None:
    registry = build_default_registry()
    loaded = load_capabilities(registry)
    router = ModelRouter(registry)

    print("=" * 70)
    print(f"Router report - loaded verified capabilities for {loaded} model(s)")
    print("=" * 70)

    tasks = [
        AgentTask.RESEARCH, AgentTask.VERIFICATION, AgentTask.EDITORIAL,
        AgentTask.TONE, AgentTask.WRITER, AgentTask.PLATFORM_ADAPTER,
    ]
    for task in tasks:
        req = router.get_task_requirements(task)
        eligible = router.eligible_models(req)
        primary = eligible[0] if eligible else None
        chain = eligible[1:4]

        print(f"\n[{task.value}]")
        print(f"  required:  {req.required}")
        if primary:
            print(f"  primary:   {primary.provider}/{primary.model_id}")
            print(f"             {reason_for(primary, req.required)}")
        else:
            print("  primary:   <none eligible>")
        if chain:
            print("  fallback:")
            for e in chain:
                print(f"    -> {e.provider}/{e.model_id}  ({reason_for(e, req.required)})")
        else:
            print("  fallback:  <empty>")

    print()


if __name__ == "__main__":
    main()
