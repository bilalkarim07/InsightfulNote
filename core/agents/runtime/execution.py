"""Execution engine — orchestrates a single agent over the runtime.

Middleware is applied by name. Only middleware that has a reason is attached.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from core.agents.base.config import AgentConfig, DEFAULT_AGENT_CONFIGS
from core.agents.base.errors import BlockedError, EscalationError
from core.agents.runtime.state import NewsroomState


class OutcomeStatus(str, Enum):
    SUCCESS = "SUCCESS"
    BLOCKED = "BLOCKED"
    ESCALATE = "ESCALATE"
    RETRY = "RETRY"
    FAILED = "FAILED"


@dataclass
class ExecutionOutcome:
    status: OutcomeStatus
    output: Any = None
    error: Optional[str] = None
    attempts: int = 0
    middleware_applied: list[str] = field(default_factory=list)


class ExecutionEngine:
    """Wraps a callable agent function with config-driven middleware."""

    def __init__(self, config: Optional[AgentConfig] = None, name: str = "research") -> None:
        self.config = config or DEFAULT_AGENT_CONFIGS[name]

    def run(
        self,
        state: NewsroomState,
        invoke: Callable[[NewsroomState], Any],
    ) -> ExecutionOutcome:
        outcome = ExecutionOutcome(
            status=OutcomeStatus.FAILED,
            middleware_applied=list(self.config.middleware),
        )

        if self.config.is_deterministic or not self.config.uses_llm:
            try:
                result = invoke(state)
                outcome.status = OutcomeStatus.SUCCESS
                outcome.output = result
                outcome.attempts = 1
            except BlockedError as exc:
                outcome.status = OutcomeStatus.BLOCKED
                outcome.error = str(exc)
            except EscalationError as exc:
                outcome.status = OutcomeStatus.ESCALATE
                outcome.error = str(exc)
            except Exception as exc:  # noqa: BLE001
                outcome.status = OutcomeStatus.FAILED
                outcome.error = f"{type(exc).__name__}: {exc}"
            return outcome

        max_attempts = self.config.max_model_calls or 1
        for attempt in range(1, max_attempts + 1):
            outcome.attempts = attempt
            try:
                result = invoke(state)
                outcome.status = OutcomeStatus.SUCCESS
                outcome.output = result
                return outcome
            except BlockedError as exc:
                outcome.status = OutcomeStatus.BLOCKED
                outcome.error = str(exc)
                return outcome
            except EscalationError as exc:
                outcome.status = OutcomeStatus.ESCALATE
                outcome.error = str(exc)
                return outcome
            except Exception as exc:  # noqa: BLE001
                outcome.error = f"{type(exc).__name__}: {exc}"
                continue

        outcome.status = OutcomeStatus.RETRY
        return outcome
