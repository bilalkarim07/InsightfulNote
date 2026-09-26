"""Fallback manager.

Fallback preserves task capability requirements. It NEVER falls back from a
reasoning+tool+structured model to a text-only model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core.llm.registry import ModelEntry
from core.llm.routing.router import AgentTask, ModelRouter


@dataclass
class FallbackAttempt:
    model: ModelEntry
    success: bool
    error: Optional[str] = None
    elapsed_ms: float = 0.0


@dataclass
class FallbackResult:
    task: AgentTask
    attempts: list[FallbackAttempt] = field(default_factory=list)
    final_success: bool = False
    final_result: Any = None

    @property
    def used_model(self) -> Optional[ModelEntry]:
        for a in self.attempts:
            if a.success:
                return a.model
        return None

    @property
    def fallback_reason(self) -> str:
        if not self.attempts:
            return "no eligible models"
        failed = [a.model.display_name for a in self.attempts if not a.success]
        return "failed: " + ", ".join(failed) if failed else "primary succeeded"


class FallbackManager:
    """Executes a callable across a capability-preserving fallback chain."""

    def __init__(self, router: ModelRouter, max_fallbacks: int = 3) -> None:
        self.router = router
        self.max_fallbacks = max_fallbacks

    def execute(
        self,
        task: AgentTask,
        invoke: Callable[[ModelEntry], Any],
    ) -> FallbackResult:
        """Try each eligible model in order until one succeeds.

        `invoke` receives a ModelEntry and returns the result.
        Raises on failure so the next model can be tried.
        """
        chain = self.router.fallback_chain(task, max_size=self.max_fallbacks + 1)
        result = FallbackResult(task=task)

        if not chain:
            result.fallback_reason
            return result

        for model in chain:
            attempt = FallbackAttempt(model=model, success=False)
            try:
                out = invoke(model)
                attempt.success = True
                result.final_result = out
                result.final_success = True
                result.attempts.append(attempt)
                return result
            except Exception as exc:  # noqa: BLE001
                attempt.error = f"{type(exc).__name__}: {exc}"
                result.attempts.append(attempt)

        return result
