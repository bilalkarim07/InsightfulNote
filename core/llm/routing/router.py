"""Capability-aware router.

The router genuinely evaluates task requirements against VERIFIED capabilities,
then ranks eligible models by priority and reliability.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from core.llm.registry import ModelEntry, ModelRegistry


class AgentTask(str, Enum):
    DISCOVERY = "discovery"
    SOURCE_INTELLIGENCE = "source_intelligence"
    RESEARCH = "research"
    SELECTION = "selection"
    VERIFICATION = "verification"
    EDITORIAL = "editorial"
    TONE = "tone"
    WRITER = "writer"
    PLATFORM_ADAPTER = "platform_adapter"
    VALIDATION = "validation"
    PUBLISHER = "publisher"


class TaskRequirements(BaseModel):
    """Capability requirements for a specific agent task."""

    task: AgentTask
    required: list[str] = Field(default_factory=list)
    preferred_models: list[str] = Field(default_factory=list)
    forbidden_providers: list[str] = Field(default_factory=list)


# Default requirements per task (configurable, not immutable).
DEFAULT_TASK_REQUIREMENTS: dict[AgentTask, TaskRequirements] = {
    AgentTask.RESEARCH: TaskRequirements(
        task=AgentTask.RESEARCH,
        required=["basic_invocation", "structured_output",
                  "tool_calling", "tool_plus_structure"],
    ),
    AgentTask.VERIFICATION: TaskRequirements(
        task=AgentTask.VERIFICATION,
        required=["basic_invocation", "structured_output",
                  "tool_calling", "tool_plus_structure"],
    ),
    AgentTask.EDITORIAL: TaskRequirements(
        task=AgentTask.EDITORIAL,
        required=["basic_invocation", "structured_output"],
    ),
    AgentTask.TONE: TaskRequirements(
        task=AgentTask.TONE,
        required=["basic_invocation", "structured_output"],
    ),
    AgentTask.WRITER: TaskRequirements(
        task=AgentTask.WRITER,
        required=["basic_invocation", "structured_output"],
    ),
    AgentTask.PLATFORM_ADAPTER: TaskRequirements(
        task=AgentTask.PLATFORM_ADAPTER,
        required=["basic_invocation", "structured_output"],
    ),
}


class ModelRouter:
    """Routes agent tasks to the best available model.

    Routing logic:
      1. Look up task requirements.
      2. Filter registry to models with ALL required VERIFIED capabilities.
      3. Remove forbidden providers.
      4. Sort by (priority, -reliability).
      5. Return the primary model + fallback chain.
    """

    def __init__(self, registry: ModelRegistry) -> None:
        self.registry = registry

    def get_task_requirements(self, task: AgentTask) -> TaskRequirements:
        if task in DEFAULT_TASK_REQUIREMENTS:
            return DEFAULT_TASK_REQUIREMENTS[task]
        return TaskRequirements(task=task, required=["basic_invocation"])

    def eligible_models(self, req: TaskRequirements) -> list[ModelEntry]:
        eligible = self.registry.eligible(*req.required)
        eligible = [
            e for e in eligible
            if e.provider not in req.forbidden_providers
        ]
        # Rank by priority (ascending), then reliability (descending)
        def rank(e: ModelEntry):
            rel = 0.0
            if e.capabilities and e.capabilities.reliability_score is not None:
                rel = e.capabilities.reliability_score
            return (e.priority, -rel)

        return sorted(eligible, key=rank)

    def route(self, task: AgentTask) -> Optional[ModelEntry]:
        """Return the primary model for a task, or None if none are eligible."""
        req = self.get_task_requirements(task)
        eligible = self.eligible_models(req)
        return eligible[0] if eligible else None

    def fallback_chain(self, task: AgentTask, max_size: int = 4) -> list[ModelEntry]:
        """Return the ordered fallback chain for a task."""
        req = self.get_task_requirements(task)
        return self.eligible_models(req)[:max_size]
