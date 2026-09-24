"""Environment-backed token storage.

Per the current milestone we only need to read/write a single access
token from ``.env``.  No timestamps, no Supabase, no refresh metadata.
"""

from __future__ import annotations

import os
from typing import Optional, Protocol, runtime_checkable

from .exceptions import ThreadsAuthenticationError
from .models import ThreadsToken


@runtime_checkable
class ThreadsTokenStore(Protocol):
    def load(self) -> ThreadsToken: ...
    def save(self, token: ThreadsToken) -> None: ...


class EnvironmentThreadsTokenStore:
    """Reads/writes ``THREADS_ACCESS_TOKEN`` and friends from the environment."""

    ENV_ACCESS_TOKEN = "THREADS_ACCESS_TOKEN"
    ENV_USER_ID = "THREADS_USER_ID"
    ENV_USERNAME = "THREADS_USERNAME"

    def __init__(self, *, dotenv_path: Optional[str] = None) -> None:
        if dotenv_path:
            self._load_dotenv(dotenv_path)

    @staticmethod
    def _load_dotenv(path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    os.environ.setdefault(key, value)
        except FileNotFoundError:
            pass

    def load(self) -> ThreadsToken:
        access_token = os.environ.get(self.ENV_ACCESS_TOKEN, "").strip()
        if not access_token:
            raise ThreadsAuthenticationError(
                "No THREADS_ACCESS_TOKEN found. Run "
                "`python scripts/setup_threads_auth.py` first."
            )
        return ThreadsToken(
            access_token=access_token,
            user_id=os.environ.get(self.ENV_USER_ID) or None,
            username=os.environ.get(self.ENV_USERNAME) or None,
        )

    def save(self, token: ThreadsToken) -> None:
        os.environ[self.ENV_ACCESS_TOKEN] = token.access_token.get_secret_value()
        if token.user_id:
            os.environ[self.ENV_USER_ID] = token.user_id
        if token.username:
            os.environ[self.ENV_USERNAME] = token.username


def write_env_file(path: str, updates: dict[str, str]) -> None:
    """Update ``key=value`` pairs in a ``.env`` file in place.

    Preserves comments, blank lines, and unrelated keys.  If a key does
    not exist, it is appended.
    """
    lines: list[str] = []
    remaining = dict(updates)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        lines = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, _ = stripped.partition("=")
        key = key.strip()
        if key in remaining:
            lines[i] = f"{key}={remaining.pop(key)}\n"

    for key, value in remaining.items():
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.append(f"{key}={value}\n")

    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(lines)