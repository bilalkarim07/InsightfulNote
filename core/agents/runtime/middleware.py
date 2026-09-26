"""Middleware implementations.

Each middleware is a callable that wraps an invoke function. Middleware
is applied ONLY where a reason exists — no decorative middleware.

Categories:
    ModelFallback   — swap to next eligible model on failure
    ToolRetry       — retry transient tool failures (bounded)
    ToolCallLimit   — cap tool calls per agent run
    ModelCallLimit  — cap LLM calls per agent run
    Todo            — record plan steps for complex tasks
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ── ToolCallLimit ─────────────────────────────────────────────

@dataclass
class ToolCallBudget:
    """Shared per-run counter for tool call limits."""

    limit: int
    used: int = 0
    calls: list[str] = field(default_factory=list)

    def consume(self, name: str) -> None:
        if self.used >= self.limit:
            raise RuntimeError(
                f"ToolCallLimit exceeded: {self.used}/{self.limit} (trying {name!r})"
            )
        self.used += 1
        self.calls.append(name)


# ── ModelCallLimit ────────────────────────────────────────────

@dataclass
class ModelCallBudget:
    limit: int
    used: int = 0

    def consume(self) -> None:
        if self.used >= self.limit:
            raise RuntimeError(
                f"ModelCallLimit exceeded: {self.used}/{self.limit}"
            )
        self.used += 1


# ── ToolRetry ─────────────────────────────────────────────────

def with_tool_retry(
    fn: Callable[..., Any],
    *,
    max_retries: int = 2,
    backoff_seconds: float = 0.5,
) -> Callable[..., Any]:
    """Wrap a tool call so transient failures are retried with backoff."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        last_exc: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < max_retries:
                    time.sleep(backoff_seconds * (2 ** attempt))
                    continue
                raise
        raise last_exc  # pragma: no cover

    return wrapper


# ── ModelFallback ─────────────────────────────────────────────

@dataclass
class FallbackTrace:
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def record(self, model: str, success: bool, error: Optional[str] = None) -> None:
        self.attempts.append({
            "model": model,
            "success": success,
            "error": error,
        })

    @property
    def used_fallback(self) -> bool:
        return len(self.attempts) > 1


def with_model_fallback(
    chain: list[Any],
    invoke_with: Callable[[Any], Any],
    *,
    trace: Optional[FallbackTrace] = None,
) -> tuple[Any, FallbackTrace]:
    """Try each model in the chain until one succeeds.

    Args:
        chain: Ordered list of models (each with a .model_name or display).
        invoke_with: Callable that receives a model and returns the result.
        trace: Optional trace object to record attempts.

    Returns:
        (result, trace)
    """
    trace = trace or FallbackTrace()
    last_exc: Optional[Exception] = None
    for model in chain:
        name = getattr(model, "model_name", None) or getattr(model, "model", "unknown")
        try:
            result = invoke_with(model)
            trace.record(str(name), success=True)
            return result, trace
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            trace.record(str(name), success=False, error=f"{type(exc).__name__}: {exc}")
    raise RuntimeError(
        f"All fallback models failed. Last error: {last_exc}"
    )


# ── Todo (planning) ───────────────────────────────────────────

@dataclass
class TodoList:
    """Explicit plan for multi-step Research / Verification work."""

    items: list[dict[str, Any]] = field(default_factory=list)

    def add(self, description: str) -> None:
        self.items.append({"description": description, "done": False})

    def complete(self, index: int) -> None:
        if 0 <= index < len(self.items):
            self.items[index]["done"] = True

    def pending(self) -> list[str]:
        return [i["description"] for i in self.items if not i["done"]]

    def render(self) -> str:
        lines = []
        for i, item in enumerate(self.items):
            mark = "x" if item["done"] else " "
            lines.append(f"  [{mark}] {i + 1}. {item['description']}")
        return "\n".join(lines) if lines else "  (empty)"
