"""Agent error hierarchy — supports BLOCKED, ESCALATE, RETRY, FAILED."""
from __future__ import annotations


class AgentError(Exception):
    """Base class for all agent errors."""


class ModelError(AgentError):
    """Raised when an LLM call fails."""


class ToolError(AgentError):
    """Raised when a tool call fails."""


class SchemaError(AgentError):
    """Raised when structured output fails Pydantic validation."""


class BlockedError(AgentError):
    """Raised when an agent must block publication due to insufficient evidence."""


class EscalationError(AgentError):
    """Raised when a human decision is required."""


class RetryableError(AgentError):
    """Raised when a transient failure should trigger retry/fallback."""
