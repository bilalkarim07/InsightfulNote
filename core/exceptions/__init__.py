"""Core exception hierarchy for the InsightfullNote project.

Design goals:
- Every error carries structured context (source, operation, params, retry info).
- ``str(exc)`` produces a human-readable, informative message.
- ``exc.to_dict()`` produces a machine-readable dict for logging/observability.
- Secrets (API keys, tokens, auth headers) must never be included in messages.

Conventions:
- ``source``   : logical source name, e.g. "gdelt", "tavily", "rss".
- ``operation``: logical operation, e.g. "search", "fetch", "parse".
- ``context``  : arbitrary non-secret key/value metadata (query, url, status, etc).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional


# Keys that must never appear in a rendered error message or to_dict().
_REDACTED_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "password",
        "cookie",
        "set-cookie",
        "x-api-key",
    }
)


def _redact(mapping: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Return a copy of mapping with sensitive keys masked."""
    if not mapping:
        return {}
    redacted: dict[str, Any] = {}
    for key, value in mapping.items():
        if str(key).lower() in _REDACTED_KEYS:
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted


def _format_context(context: Mapping[str, Any]) -> str:
    if not context:
        return ""
    parts = [f"{k}={v!r}" for k, v in context.items()]
    return " [" + ", ".join(parts) + "]"


class SourceError(Exception):
    """Base exception for all source-related errors.

    Parameters
    ----------
    message:
        Human-readable description of what went wrong.
    source:
        Logical source name, e.g. "gdelt", "tavily", "rss".
    operation:
        Logical operation being performed, e.g. "search", "fetch", "parse".
    context:
        Arbitrary non-secret metadata. Sensitive keys are auto-redacted.
    cause:
        Optional underlying exception. Also picked up from ``__cause__``.
    """

    #: Short, stable code used for programmatic handling.
    code: str = "source_error"

    def __init__(
        self,
        message: str,
        *,
        source: Optional[str] = None,
        operation: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.message = message
        self.source = source
        self.operation = operation
        self.context: dict[str, Any] = _redact(context)
        self.cause = cause or self.__cause__
        super().__init__(self._render())

    # --- rendering -----------------------------------------------------

    def _render(self) -> str:
        prefix_parts = []
        if self.source:
            prefix_parts.append(f"source={self.source}")
        if self.operation:
            prefix_parts.append(f"operation={self.operation}")
        prefix = f"[{self.code}]"
        if prefix_parts:
            prefix += " " + " ".join(prefix_parts)

        rendered = f"{prefix}: {self.message}"
        rendered += _format_context(self.context)

        if self.cause is not None:
            rendered += f" (caused by {type(self.cause).__name__}: {self.cause})"
        return rendered

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.args[0] if self.args else self._render()

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{type(self).__name__}({self.args[0]!r})"

    # --- structured output --------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict suitable for structured logging."""
        data: dict[str, Any] = {
            "error": type(self).__name__,
            "code": self.code,
            "message": self.message,
        }
        if self.source:
            data["source"] = self.source
        if self.operation:
            data["operation"] = self.operation
        if self.context:
            data["context"] = dict(self.context)
        if self.cause is not None:
            data["cause"] = {
                "type": type(self.cause).__name__,
                "message": str(self.cause),
            }
        return data


# ---------------------------------------------------------------------------
# Connectivity / transport
# ---------------------------------------------------------------------------


class SourceConnectionError(SourceError):
    """Raised when a source cannot be reached, times out, or the transport fails.

    Extra context typically includes: url, timeout, status_code, method.
    """

    code = "source_connection_error"

    def __init__(
        self,
        message: str,
        *,
        url: Optional[str] = None,
        timeout: Optional[float] = None,
        status_code: Optional[int] = None,
        method: Optional[str] = None,
        source: Optional[str] = None,
        operation: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        merged = dict(context or {})
        if url is not None:
            merged.setdefault("url", url)
        if timeout is not None:
            merged.setdefault("timeout", timeout)
        if status_code is not None:
            merged.setdefault("status_code", status_code)
        if method is not None:
            merged.setdefault("method", method)
        super().__init__(
            message,
            source=source,
            operation=operation,
            context=merged,
            cause=cause,
        )
        self.url = url
        self.timeout = timeout
        self.status_code = status_code
        self.method = method


class SourceTimeoutError(SourceConnectionError):
    """Raised specifically when a source request times out."""

    code = "source_timeout_error"


# ---------------------------------------------------------------------------
# Authentication / authorization / quota
# ---------------------------------------------------------------------------

class SourceAuthenticationError(SourceError):
    """Raised when authentication or authorization with a source fails.

    Never includes the credential itself. Only indicates which credential
    identifier (env var name, credential type) was involved.
    """

    code = "source_authentication_error"

    def __init__(
        self,
        message: str,
        *,
        credential_name: Optional[str] = None,
        status_code: Optional[int] = None,
        url: Optional[str] = None,
        source: Optional[str] = None,
        operation: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        merged = dict(context or {})
        if credential_name is not None:
            merged.setdefault("credential_name", credential_name)
        if status_code is not None:
            merged.setdefault("status_code", status_code)
        if url is not None:
            merged.setdefault("url", url)
        super().__init__(
            message,
            source=source,
            operation=operation,
            context=merged,
            cause=cause,
        )
        self.credential_name = credential_name
        self.status_code = status_code
        self.url = url


class SourceRateLimitError(SourceError):
    """Raised when a source rate limit or quota is exceeded.

    Extra context typically includes retry_after (seconds), url, status_code.
    """

    code = "source_rate_limit_error"

    def __init__(
        self,
        message: str,
        *,
        retry_after: Optional[float] = None,
        status_code: Optional[int] = None,
        url: Optional[str] = None,
        source: Optional[str] = None,
        operation: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        merged = dict(context or {})
        if retry_after is not None:
            merged.setdefault("retry_after", retry_after)
        if status_code is not None:
            merged.setdefault("status_code", status_code)
        if url is not None:
            merged.setdefault("url", url)
        super().__init__(
            message,
            source=source,
            operation=operation,
            context=merged,
            cause=cause,
        )
        self.retry_after = retry_after
        self.status_code = status_code
        self.url = url


# ---------------------------------------------------------------------------
# Parsing / validation
# ---------------------------------------------------------------------------


class SourceParseError(SourceError):
    """Raised when a source response cannot be parsed.

    Extra context typically includes the content-type, feed URL, or a
    short, non-secret excerpt indicator (length, not contents).
    """

    code = "source_parse_error"

    def __init__(
        self,
        message: str,
        *,
        url: Optional[str] = None,
        content_type: Optional[str] = None,
        payload_size: Optional[int] = None,
        source: Optional[str] = None,
        operation: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        merged = dict(context or {})
        if url is not None:
            merged.setdefault("url", url)
        if content_type is not None:
            merged.setdefault("content_type", content_type)
        if payload_size is not None:
            merged.setdefault("payload_size", payload_size)
        super().__init__(
            message,
            source=source,
            operation=operation,
            context=merged,
            cause=cause,
        )
        self.url = url
        self.content_type = content_type
        self.payload_size = payload_size


class SourceValidationError(SourceError):
    """Raised when source parameters or response shape fail validation.

    Extra context typically includes the offending parameter name/value and
    the accepted range or set.
    """

    code = "source_validation_error"

    def __init__(
        self,
        message: str,
        *,
        parameter: Optional[str] = None,
        value: Any = None,
        expected: Optional[str] = None,
        source: Optional[str] = None,
        operation: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        merged = dict(context or {})
        if parameter is not None:
            merged.setdefault("parameter", parameter)
        if value is not None:
            merged.setdefault("value", value)
        if expected is not None:
            merged.setdefault("expected", expected)
        super().__init__(
            message,
            source=source,
            operation=operation,
            context=merged,
            cause=cause,
        )
        self.parameter = parameter
        self.value = value
        self.expected = expected


__all__ = [
    "SourceError",
    "SourceConnectionError",
    "SourceTimeoutError",
    "SourceAuthenticationError",
    "SourceRateLimitError",
    "SourceParseError",
    "SourceValidationError",
]