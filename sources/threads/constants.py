"""Constants and URL builders for the Threads API."""

from __future__ import annotations

from urllib.parse import urlencode

# ---------------------------------------------------------------------------
# Base URLs
# ---------------------------------------------------------------------------
THREADS_GRAPH_BASE_URL = "https://graph.threads.net"
THREADS_GRAPH_API_VERSION = "v1.0"

# Authentication endpoints (no version prefix)
THREADS_OAUTH_ACCESS_TOKEN_URL = f"{THREADS_GRAPH_BASE_URL}/oauth/access_token"
THREADS_ACCESS_TOKEN_URL = f"{THREADS_GRAPH_BASE_URL}/access_token"
THREADS_REFRESH_ACCESS_TOKEN_URL = f"{THREADS_GRAPH_BASE_URL}/refresh_access_token"


def threads_graph_url(path: str) -> str:
    """Build a versioned Threads Graph API URL."""
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{THREADS_GRAPH_BASE_URL}/{THREADS_GRAPH_API_VERSION}{path}"


def threads_graph_url_with_query(path: str, params: dict) -> str:
    url = threads_graph_url(path)
    if params:
        url = f"{url}?{urlencode(params)}"
    return url


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_PAGE_LIMIT = 20
DEFAULT_MAX_PAGES = 3