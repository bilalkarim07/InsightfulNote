"""Team state and agent-to-agent messages.

Every node in the graph reads from TeamState and writes back to it.
Messages are append-only so the full conversation is preserved.
"""
from __future__ import annotations

import operator
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


MessageKind = Literal["HANDOFF", "REQUEST", "FEEDBACK", "BLOCKER", "INFO", "DONE"]


class Message(BaseModel):
    """A single message between agents."""

    from_agent: str
    to_agent: str  # "all" for broadcasts
    kind: MessageKind
    content: str
    iteration: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TeamState(TypedDict, total=False):
    """State passed between graph nodes.

    Every field is optional so nodes can write only what they produce.
    """

    # Identity
    run_id: str
    story_id: str
    topic: str
    seed: dict[str, Any]
    story_record: Optional[dict[str, Any]]
    sources: Optional[list[dict[str, Any]]]
    editorial_memory: Optional[dict[str, Any]]

    # Provider / model
    provider: str
    model_id: str

    # Stage outputs (dicts because they're serializable + Optional)
    discovery: Optional[dict[str, Any]]
    source_intel: Optional[dict[str, Any]]
    research: Optional[dict[str, Any]]
    verification: Optional[dict[str, Any]]
    editorial: Optional[dict[str, Any]]
    tone: Optional[dict[str, Any]]
    draft: Optional[dict[str, Any]]
    post: Optional[dict[str, Any]]
    validation: Optional[dict[str, Any]]
    publication: Optional[dict[str, Any]]

    # Collaboration
    messages: Annotated[list[dict[str, Any]], operator.add]
    iteration: dict[str, int]
    research_questions: list[str]   # questions verification asked research
    editorial_fixes: list[str]      # issues writer flagged to editorial

    # Outcome
    current_node: str
    outcome: str        # RUNNING | PASS | BLOCK | ESCALATE | INSUFFICIENT_EVIDENCE
    blockers: list[str]
    errors: list[str]


MAX_RESEARCH_LOOPS = 2
MAX_WRITER_RETRIES = 2
MAX_EDITORIAL_FIXES = 1


def new_state(
    *,
    run_id: str,
    provider: str,
    model_id: str,
    story: dict | None = None,
    topic: str | None = None,
    editorial_memory: dict | None = None,
) -> TeamState:
    if story:
        sid = story.get("id") or f"story_{run_id[4:]}"
        seed = {
            "story_id": sid,
            "title": story.get("title", ""),
            "summary": story.get("summary") or story.get("title", ""),
            "topic": topic or "news",
            "categories": story.get("categories") or story.get("metadata", {}).get("categories") or [],
        }
    elif topic:
        sid = f"story_{run_id[4:]}"
        seed = {
            "story_id": sid,
            "title": topic,
            "summary": f"Latest developments regarding: {topic}",
            "topic": "news",
        }
    else:
        sid = f"story_{run_id[4:]}"
        seed = {
            "story_id": sid,
            "title": "Company X announces product Y",
            "summary": "Company X today announced product Y, available Q2 2026.",
            "topic": "technology",
        }

    return TeamState(
        run_id=run_id,
        story_id=sid,
        topic=seed["topic"],
        seed=seed,
        story_record=story,
        sources=story.get("sources") if story else None,
        editorial_memory=editorial_memory,
        provider=provider,
        model_id=model_id,
        messages=[],
        iteration={},
        research_questions=[],
        editorial_fixes=[],
        current_node="start",
        outcome="RUNNING",
        blockers=[],
        errors=[],
    )


def msg(
    from_agent: str, to_agent: str, kind: MessageKind, content: str,
    iteration: int = 0,
) -> dict[str, Any]:
    return Message(
        from_agent=from_agent, to_agent=to_agent,
        kind=kind, content=content, iteration=iteration,
    ).model_dump(mode="json")

