"""Normalized exception hierarchy for the Threads API integration.

Error handling follows Meta's official Graph API error documentation:
https://developers.facebook.com/docs/graph-api/guides/error-handling

Every exception carries:
    * status_code   – HTTP status
    * error_code    – Meta's numeric code (0, 1, 2, 4, 10, 190, ...)
    * error_subcode – Meta's subcode when present (458, 460, 463, ...)
    * fbtrace_id    – Meta's internal trace ID (quote this in bug reports)
    * raw           – the full error payload from Meta
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Meta error code → (human label, suggested action)
# Source: https://developers.facebook.com/docs/graph-api/guides/error-handling
# ---------------------------------------------------------------------------
_META_ERROR_CODES: dict[int, tuple[str, str]] = {
    0: (
        "Unknown error",
        "Meta returned a generic error. Common causes: the app is in "
        "development mode, no Threads Test User is configured, or the "
        "token was generated for a different app. Create a Threads Test "
        "User in your App Dashboard and accept the invite from your "
        "Threads account, then retry the exchange.",
    ),
    1: (
        "API unknown error",
        "Possibly a temporary outage or the request targets a deprecated "
        "API version. Wait and retry; if the problem persists, verify "
        "you are calling an existing endpoint.",
    ),
    2: (
        "API service error",
        "Temporary service disruption on Meta's side. Wait and retry.",
    ),
    3: (
        "API method error",
        "The feature or permission required is missing. Confirm your app "
        "has the required capability or permission enabled.",
    ),
    4: (
        "API too many calls",
        "Application-level rate limit hit. Back off exponentially with "
        "jitter and retry.",
    ),
    10: (
        "API permission denied",
        "The required permission was not granted or has been removed. "
        "Re-authorize the user with the correct scopes.",
    ),
    17: (
        "API user too many calls",
        "User-level rate limit hit. Back off exponentially and retry.",
    ),
    190: (
        "Access token expired or invalid",
        "The access token has expired, been revoked, or is otherwise "
        "invalid. Re-authenticate to obtain a new token, or refresh the "
        "long-lived token if it is still within the 60-day window.",
    ),
    341: (
        "Application limit reached",
        "Temporary throttle or outage. Wait and retry; check your API "
        "request volume.",
    ),
    368: (
        "Temporarily blocked for policy violations",
        "The app or account has been temporarily blocked. Review Meta's "
        "platform policies and wait before retrying.",
    ),
    506: (
        "Duplicate post",
        "The same content was posted consecutively. Change the post "
        "content and retry.",
    ),
    1609005: (
        "Error scraping link",
        "Meta failed to scrape data from the provided link. Verify the "
        "URL is publicly accessible and retry.",
    ),
}

# ---------------------------------------------------------------------------
# Meta authentication subcodes
# ---------------------------------------------------------------------------
_META_AUTH_SUBCODES: dict[int, tuple[str, str]] = {
    458: (
        "App not installed",
        "The user has not logged into the app. Re-authenticate the user.",
    ),
    459: (
        "User checkpoint",
        "The user must log into facebook.com or m.facebook.com to resolve "
        "a checkpoint.",
    ),
    460: (
        "Password changed",
        "The password was changed; the user must log in again.",
    ),
    463: (
        "Expired",
        "The login status or access token has expired, been revoked, or is "
        "otherwise invalid. Obtain a new access token.",
    ),
    464: (
        "User not confirmed",
        "The user must confirm their account on facebook.com.",
    ),
    467: (
        "Invalid OAuth access token",
        "The access token is invalid or has been revoked. Reconnect the "
        "account.",
    ),
}


def _lookup_code(code: Optional[int]) -> tuple[str, str]:
    if code is None:
        return ("Unknown error", "No error code was provided by Meta.")
    return _META_ERROR_CODES.get(
        code,
        ("Unrecognized Meta error code", f"Meta returned code {code}."),
    )


def _lookup_subcode(subcode: Optional[int]) -> Optional[tuple[str, str]]:
    if subcode is None:
        return None
    return _META_AUTH_SUBCODES.get(subcode)


# ---------------------------------------------------------------------------
# Base exception
# ---------------------------------------------------------------------------
class ThreadsError(Exception):
    """Base exception for all Threads API errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        error_code: Optional[int] = None,
        error_subcode: Optional[int] = None,
        error_type: Optional[str] = None,
        fbtrace_id: Optional[str] = None,
        raw: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.error_subcode = error_subcode
        self.error_type = error_type
        self.fbtrace_id = fbtrace_id
        self.raw = raw or {}

        code_label, code_action = _lookup_code(error_code)
        self.code_label = code_label
        self.suggested_action = code_action

        self.subcode_label: Optional[str] = None
        self.subcode_action: Optional[str] = None
        sub = _lookup_subcode(error_subcode)
        if sub:
            self.subcode_label, self.subcode_action = sub

    def to_dict(self) -> dict[str, Any]:
        """Return a safe, serialisable representation for agent consumption."""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "status_code": self.status_code,
            "error_code": self.error_code,
            "error_subcode": self.error_subcode,
            "error_type": self.error_type,
            "fbtrace_id": self.fbtrace_id,
            "code_label": self.code_label,
            "subcode_label": self.subcode_label,
            "suggested_action": self.suggested_action,
        }

    def pretty(self) -> str:
        """Human-readable multi-line description for CLI output."""
        lines = [
            f"{self.__class__.__name__}",
            f"  Message:           {self.message}",
            f"  HTTP status:       {self.status_code}",
            f"  Meta code:         {self.error_code} ({self.code_label})",
        ]
        if self.error_subcode is not None:
            sub_label = self.subcode_label or "unknown subcode"
            lines.append(
                f"  Meta subcode:      {self.error_subcode} ({sub_label})"
            )
        if self.error_type:
            lines.append(f"  Error type:        {self.error_type}")
        if self.fbtrace_id:
            lines.append(f"  fbtrace_id:        {self.fbtrace_id}")
        lines.append(f"  Suggested action:  {self.suggested_action}")
        if self.subcode_action:
            lines.append(f"  Subcode action:    {self.subcode_action}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Specialised exceptions
# ---------------------------------------------------------------------------
class ThreadsAuthenticationError(ThreadsError):
    """Raised when authentication fails (invalid/expired token, bad credentials)."""


class ThreadsTokenExpiredError(ThreadsAuthenticationError):
    """Raised when the configured access token has expired."""


class ThreadsPermissionError(ThreadsError):
    """Raised when the token lacks a required scope/permission."""

    def __init__(
        self,
        message: str,
        *,
        required_scope: Optional[str] = None,
        operation: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.required_scope = required_scope
        self.operation = operation

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "error": "permission_required",
                "operation": self.operation,
                "required_scope": self.required_scope,
            }
        )
        return base

    def pretty(self) -> str:
        base = super().pretty()
        extra = []
        if self.required_scope:
            extra.append(f"  Required scope:    {self.required_scope}")
        if self.operation:
            extra.append(f"  Operation:         {self.operation}")
        return base + "\n" + "\n".join(extra) if extra else base


class ThreadsRateLimitError(ThreadsError):
    """Raised when the API rate limit is exceeded."""


class ThreadsAPIError(ThreadsError):
    """Raised for generic API-level errors."""


class ThreadsValidationError(ThreadsError):
    """Raised when input validation fails."""


class ThreadsPublishingError(ThreadsError):
    """Raised when a publish operation fails.

    Publishing is a two-step process (create container → publish).  This
    exception carries the ``container_id`` so that callers can recover
    without creating a duplicate container.
    """

    def __init__(
        self,
        message: str,
        *,
        container_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.container_id = container_id

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base["container_id"] = self.container_id
        return base