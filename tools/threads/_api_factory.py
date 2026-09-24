"""Shared factory that builds a configured :class:`ThreadsAPI` instance.

Tools import this instead of instantiating the API themselves, which
keeps configuration in one place and makes testing easier.
"""

from __future__ import annotations

import os

from sources.threads.api import ThreadsAPI


def build_threads_api() -> ThreadsAPI:
    """Build a :class:`ThreadsAPI` from environment variables.

    The returned instance is lightweight – it does not perform any
    network calls until a method is invoked.
    """
    return ThreadsAPI(
        app_id=os.environ.get("THREADS_APP_ID", ""),
        app_secret=os.environ.get("THREADS_APP_SECRET", ""),
        redirect_uri=os.environ.get("THREADS_REDIRECT_URI", ""),
    )