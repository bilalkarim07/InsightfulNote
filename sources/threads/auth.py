"""Authentication for the Threads API.

Two independent operations are exposed:

    1. exchange_short_lived_for_long_lived(short_lived_token)
    2. refresh_long_lived_token(access_token)

There is NO automatic refresh, NO scheduler, and NO persistence logic
here.  The caller decides when to invoke either method.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .constants import (
    THREADS_ACCESS_TOKEN_URL,
    THREADS_REFRESH_ACCESS_TOKEN_URL,
)
from .exceptions import (
    ThreadsAPIError,
    ThreadsAuthenticationError,
    ThreadsError,
    ThreadsPermissionError,
    ThreadsRateLimitError,
    ThreadsTokenExpiredError,
    ThreadsValidationError,
)
from .models import ThreadsToken

logger = logging.getLogger(__name__)


# Scope registry – used by tools/services to check capabilities.
THREADS_SCOPE_FEATURES: dict[str, list[str]] = {
    "threads_basic": ["authentication", "profile"],
    "threads_content_publish": ["create_post", "reply"],
    "threads_read_replies": ["read_replies", "read_conversation"],
    "threads_manage_replies": ["reply_management"],
    "threads_keyword_search": ["keyword_search"],
    "threads_profile_discovery": ["profile_discovery"],
    "threads_delete": ["delete_post"],
    "threads_manage_insights": ["insights"],
    "threads_manage_mentions": ["mentions"],
    "threads_location_tagging": ["location_tagging"],
    "threads_share_to_instagram": ["instagram_sharing"],
}


class ThreadsAuth:
    """Encapsulates the two Threads token operations."""

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        timeout: float = 30.0,
    ) -> None:
        if not app_id:
            raise ThreadsValidationError("THREADS_APP_ID is required.")
        if not app_secret:
            raise ThreadsValidationError("THREADS_APP_SECRET is required.")
        self._app_id = app_id
        self._app_secret = app_secret
        self._timeout = timeout
        self._http = httpx.Client(timeout=self._timeout)

    # ------------------------------------------------------------------
    # Function 1 – Short-lived → long-lived
    # ------------------------------------------------------------------
    def exchange_short_lived_for_long_lived(
        self,
        *,
        short_lived_token: str,
    ) -> ThreadsToken:
        """Exchange a short-lived token for a long-lived token.

        Endpoint: ``GET https://graph.threads.net/access_token``
        """
        if not short_lived_token:
            raise ThreadsValidationError("Short-lived token must not be empty.")

        params = {
            "grant_type": "th_exchange_token",
            "client_id": self._app_id,  # <-- ADDED: Required by Meta to verify the app
            "client_secret": self._app_secret,
            "access_token": short_lived_token,
        }

        try:
            response = self._http.get(THREADS_ACCESS_TOKEN_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise self._map_error(exc) from exc
        except httpx.RequestError as exc:
            raise ThreadsAPIError(f"Network error during token exchange: {exc}") from exc

        data: dict[str, Any] = response.json()
        access_token = data.get("access_token")
        if not access_token:
            raise ThreadsAuthenticationError(
                "Exchange did not return an access token.", raw=data
            )

        logger.info(
            "Exchanged short-lived token for long-lived token "
            "(expires_in=%s seconds – not stored, manual refresh only).",
            data.get("expires_in"),
        )

        return ThreadsToken(
            access_token=access_token,
            token_type=data.get("token_type", "bearer"),
        )

    # ------------------------------------------------------------------
    # Function 2 – Refresh long-lived token (manual invocation only)
    # ------------------------------------------------------------------
    def refresh_long_lived_token(self, *, access_token: str) -> ThreadsToken:
        """Refresh an existing long-lived token.

        This method is **not** called automatically.  It exists so the
        developer can invoke it from a script when they decide it is
        necessary.

        Endpoint: ``GET https://graph.threads.net/refresh_access_token``
        """
        if not access_token:
            raise ThreadsValidationError("Access token must not be empty.")

        params = {
            "grant_type": "th_refresh_token",
            "access_token": access_token,
        }

        try:
            response = self._http.get(THREADS_REFRESH_ACCESS_TOKEN_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise self._map_error(exc) from exc
        except httpx.RequestError as exc:
            raise ThreadsAPIError(f"Network error during token refresh: {exc}") from exc

        data: dict[str, Any] = response.json()
        new_token = data.get("access_token")
        if not new_token:
            raise ThreadsAuthenticationError(
                "Refresh did not return an access token.", raw=data
            )

        logger.info(
            "Refreshed long-lived token (expires_in=%s seconds).",
            data.get("expires_in"),
        )

        return ThreadsToken(
            access_token=new_token,
            token_type=data.get("token_type", "bearer"),
        )

    # ------------------------------------------------------------------
    # Error mapping
    # ------------------------------------------------------------------
    @staticmethod
    def _map_error(exc: httpx.HTTPStatusError) -> ThreadsError:
        """Convert an HTTP error into a normalised Threads exception.

        Extracts every field Meta provides — message, type, code,
        error_subcode, and fbtrace_id — so the caller sees the same
        detail a Meta support engineer would need.
        """
        status = exc.response.status_code
        try:
            body = exc.response.json()
        except Exception:
            body = {}

        error = body.get("error", {}) if isinstance(body, dict) else {}
        message = error.get("message", str(exc))
        code = error.get("code")
        subcode = error.get("error_subcode")
        error_type = error.get("type")
        fbtrace_id = error.get("fbtrace_id")

        # ------------------------------------------------------------------
        # Code 0 – generic Meta error.  Most common causes during token
        # exchange: the app is in development mode without a Threads Test
        # User, or the token was generated for a different app.
        # ------------------------------------------------------------------
        if code == 0:
            return ThreadsAuthenticationError(
                "Meta returned a generic error (code 0). This usually means "
                "the app is in development mode without a Threads Test User, "
                "or the short-lived token was generated for a different app. "
                "Fix: create a Threads Test User in your App Dashboard, "
                "accept the invite from your Threads account, and retry.",
                status_code=status,
                error_code=code,
                error_subcode=subcode,
                error_type=error_type,
                fbtrace_id=fbtrace_id,
                raw=body,
            )

        # 190 / 102 / 463 / 467 – token problems
        if code in (190, 102) or subcode in (463, 467):
            return ThreadsTokenExpiredError(
                f"Threads token is invalid or expired: {message}",
                status_code=status,
                error_code=code,
                error_subcode=subcode,
                error_type=error_type,
                fbtrace_id=fbtrace_id,
                raw=body,
            )

        # 10 / 200-299 – permission problems
        if code == 10 or (code is not None and 200 <= code <= 299):
            return ThreadsPermissionError(
                f"Threads permission denied: {message}",
                status_code=status,
                error_code=code,
                error_subcode=subcode,
                error_type=error_type,
                fbtrace_id=fbtrace_id,
                raw=body,
                operation="token_exchange",
            )

        # 4 / 17 / 341 – rate limiting
        if code in (4, 17, 341):
            return ThreadsRateLimitError(
                f"Threads rate limit hit: {message}",
                status_code=status,
                error_code=code,
                error_subcode=subcode,
                error_type=error_type,
                fbtrace_id=fbtrace_id,
                raw=body,
            )

        # Everything else – generic authentication error
        return ThreadsAuthenticationError(
            f"Threads authentication error: {message}",
            status_code=status,
            error_code=code,
            error_subcode=subcode,
            error_type=error_type,
            fbtrace_id=fbtrace_id,
            raw=body,
        )

    def close(self) -> None:
        self._http.close()