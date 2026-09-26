"""Shared factory that builds a configured ThreadsAPI instance.

The factory respects the actual ThreadsAPI signature:
    ThreadsAPI(*, app_id, app_secret, token_store=None, timeout=30.0)

Redirect URIs are not a constructor argument — they are only used during
OAuth flows, which this codebase does not perform at runtime.

Token loading: if THREADS_ACCESS_TOKEN is set, we look for a matching
ThreadsTokenStore implementation exposed by sources.threads. If the
class exists and accepts a raw token, we build one and pass it in.
"""
from __future__ import annotations

import os

from sources.threads.api import ThreadsAPI


def _build_token_store():
    """Try to construct a token store from THREADS_ACCESS_TOKEN.

    Returns None if no compatible store is available.
    """
    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        return None
    try:
        from sources.threads import ThreadsTokenStore  # type: ignore
    except ImportError:
        return None
    # Try a few common constructor signatures.
    for kwargs in (
        {"access_token": token},
        {"token": token},
        {"long_lived_token": token},
    ):
        try:
            return ThreadsTokenStore(**kwargs)
        except TypeError:
            continue
        except Exception:
            continue
    # Try positional.
    try:
        return ThreadsTokenStore(token)
    except Exception:
        return None


def build_threads_api() -> ThreadsAPI:
    """Build a ThreadsAPI from environment variables.

    The returned instance performs no network calls until a method is invoked.
    """
    app_id = os.environ.get("THREADS_APP_ID", "").strip()
    app_secret = os.environ.get("THREADS_APP_SECRET", "").strip()
    timeout = float(os.environ.get("THREADS_TIMEOUT", "30"))
    token_store = _build_token_store()

    return ThreadsAPI(
        app_id=app_id,
        app_secret=app_secret,
        token_store=token_store,
        timeout=timeout,
    )
