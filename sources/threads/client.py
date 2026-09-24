"""Low-level HTTP client for the Threads Graph API."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

from .constants import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    threads_graph_url,
    threads_graph_url_with_query,
)
from .exceptions import (
    ThreadsAPIError,
    ThreadsAuthenticationError,
    ThreadsPermissionError,
    ThreadsRateLimitError,
    ThreadsTokenExpiredError,
)
from .models import ThreadsToken

logger = logging.getLogger(__name__)

# Status codes that are safe to retry
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ThreadsHTTPClient:
    """Thin wrapper around ``httpx`` for the Threads Graph API.

    Responsibilities
    ----------------
    * Attach the ``Authorization: Bearer <token>`` header.
    * Timeouts and basic retry/backoff for transient failures.
    * JSON parsing.
    * Meta API error normalisation.
    * Safe logging – **never** logs the authorization header or raw token.
    """

    def __init__(
        self,
        *,
        token_provider: "ThreadsTokenProvider",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self._token_provider = token_provider
        self._timeout = timeout
        self._max_retries = max_retries
        self._http = httpx.Client(timeout=self._timeout)

    # ------------------------------------------------------------------
    # Public request helpers
    # ------------------------------------------------------------------
    def get(
        self,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        operation: str = "get",
        token: Optional[ThreadsToken] = None,
    ) -> dict[str, Any]:
        """Perform an authenticated GET request."""
        return self._request(
            "GET",
            path,
            params=params,
            operation=operation,
            token=token,
        )

    def post(
        self,
        path: str,
        *,
        data: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        operation: str = "post",
        token: Optional[ThreadsToken] = None,
    ) -> dict[str, Any]:
        """Perform an authenticated POST request."""
        return self._request(
            "POST",
            path,
            data=data,
            params=params,
            operation=operation,
            token=token,
        )

    def delete(
        self,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        operation: str = "delete",
        token: Optional[ThreadsToken] = None,
    ) -> dict[str, Any]:
        """Perform an authenticated DELETE request."""
        return self._request(
            "DELETE",
            path,
            params=params,
            operation=operation,
            token=token,
        )

    # ------------------------------------------------------------------
    # Internal machinery
    # ------------------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        operation: str = "",
        token: Optional[ThreadsToken] = None,
    ) -> dict[str, Any]:
        if token is None:
            token = self._token_provider()

        url = threads_graph_url(path)
        headers = {
            "Authorization": f"Bearer {token.access_token.get_secret_value()}",
            "Content-Type": "application/json",
        }

        start = time.monotonic()
        last_exc: Optional[Exception] = None

        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._http.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=data if method in ("POST", "PUT", "PATCH") else None,
                )
            except httpx.RequestError as exc:
                last_exc = exc
                logger.warning(
                    "Threads %s %s network error (attempt %d/%d): %s",
                    method,
                    path,
                    attempt,
                    self._max_retries,
                    exc,
                )
                if attempt < self._max_retries:
                    time.sleep(min(2 ** attempt, 10))
                continue

            duration_ms = int((time.monotonic() - start) * 1000)

            # ------------------------------------------------------------------
            # Success
            # ------------------------------------------------------------------
            if response.is_success:
                body = response.json() if response.content else {}
                logger.info(
                    "Threads %s %s success status=%d duration_ms=%d",
                    method,
                    path,
                    response.status_code,
                    duration_ms,
                )
                return body

            # ------------------------------------------------------------------
            # Error – attempt to parse Meta error payload
            # ------------------------------------------------------------------
            try:
                error_body = response.json()
            except Exception:
                error_body = {}

            error = error_body.get("error", {}) if isinstance(error_body, dict) else {}
            message = error.get("message", response.text[:500])
            code = error.get("code")
            subcode = error.get("error_subcode")
            error_type = error.get("type")
            fbtrace_id = error.get("fbtrace_id")

            # Retry transient errors
            if (
                response.status_code in _RETRYABLE_STATUS_CODES
                and attempt < self._max_retries
            ):
                logger.warning(
                    "Threads %s %s transient error %d (attempt %d/%d): %s",
                    method,
                    path,
                    response.status_code,
                    attempt,
                    self._max_retries,
                    message,
                )
                time.sleep(min(2 ** attempt, 10))
                continue

            # Map to normalised exceptions
            raise self._map_error(
                status_code=response.status_code,
                message=message,
                error_code=code,
                error_subcode=subcode,
                error_type=error_type,
                fbtrace_id=fbtrace_id,
                raw=error_body,
                operation=operation,
            )

        # All retries exhausted
        raise ThreadsAPIError(
            f"Threads {method} {path} failed after {self._max_retries} attempts: {last_exc}"
        )

    @staticmethod
    def _map_error(
        *,
        status_code: int,
        message: str,
        error_code: Optional[int],
        error_subcode: Optional[int],
        error_type: Optional[str],
        fbtrace_id: Optional[str],
        raw: dict[str, Any],
        operation: str,
    ) -> Exception:
        """Map a Meta error payload to the correct Threads exception."""

        # Token problems (190 / 102 / subcodes 463 / 467)
        if error_code in (190, 102) or error_subcode in (463, 467):
            return ThreadsTokenExpiredError(
                message,
                status_code=status_code,
                error_code=error_code,
                error_subcode=error_subcode,
                error_type=error_type,
                fbtrace_id=fbtrace_id,
                raw=raw,
            )

        # Rate limits (HTTP 429 or code 4 / 17 / 341)
        if status_code == 429 or error_code in (4, 17, 341):
            return ThreadsRateLimitError(
                message,
                status_code=status_code,
                error_code=error_code,
                error_subcode=error_subcode,
                error_type=error_type,
                fbtrace_id=fbtrace_id,
                raw=raw,
            )

        # Permission problems (HTTP 401/403 or code 10 or 200-299)
        if (
            status_code in (401, 403)
            or error_code == 10
            or (error_code is not None and 200 <= error_code <= 299)
        ):
            return ThreadsPermissionError(
                message,
                status_code=status_code,
                error_code=error_code,
                error_subcode=error_subcode,
                error_type=error_type,
                fbtrace_id=fbtrace_id,
                raw=raw,
                operation=operation,
            )

        # Authentication problems on 401/403 without a specific code
        if status_code in (401, 403):
            return ThreadsAuthenticationError(
                message,
                status_code=status_code,
                error_code=error_code,
                error_subcode=error_subcode,
                error_type=error_type,
                fbtrace_id=fbtrace_id,
                raw=raw,
            )

        # Generic API error
        return ThreadsAPIError(
            message,
            status_code=status_code,
            error_code=error_code,
            error_subcode=error_subcode,
            error_type=error_type,
            fbtrace_id=fbtrace_id,
            raw=raw,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ThreadsHTTPClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Token provider protocol
# ---------------------------------------------------------------------------


class ThreadsTokenProvider:
    """Callable that returns the current :class:`ThreadsToken`."""

    def __call__(self) -> ThreadsToken:
        raise NotImplementedError