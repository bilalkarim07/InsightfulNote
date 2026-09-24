"""Internal Pydantic models for the Threads integration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, SecretStr


class ThreadsToken(BaseModel):
    """Normalised representation of a Threads access token.

    The ``access_token`` field uses :class:`SecretStr` so that the token
    is never accidentally logged or serialised into agent output.
    """

    access_token: SecretStr
    token_type: str = "bearer"
    user_id: Optional[str] = None
    username: Optional[str] = None
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    scopes: list[str] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------
    @property
    def is_expired(self) -> bool:
        """Return ``True`` if the token has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at

    @property
    def days_remaining(self) -> Optional[int]:
        """Return the number of whole days until expiration."""
        if self.expires_at is None:
            return None
        delta = self.expires_at - datetime.now(timezone.utc)
        return max(0, delta.days)

    def masked_token(self) -> str:
        """Return a safe, partially masked representation of the token."""
        raw = self.access_token.get_secret_value()
        if len(raw) <= 8:
            return "****"
        return f"{raw[:4]}...{raw[-4:]}"


class ThreadsTokenStatus(BaseModel):
    """Safe token-status model returned by :meth:`ThreadsAPI.get_token_status`."""

    authenticated: bool
    username: Optional[str] = None
    user_id: Optional[str] = None
    token_type: Optional[str] = None
    expires_at: Optional[datetime] = None
    days_remaining: Optional[int] = None
    expired: bool = False
    scopes: list[str] = Field(default_factory=list)


class TokenState:
    """Deterministic authentication states."""

    ACTIVE = "ACTIVE"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    INVALID = "INVALID"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"