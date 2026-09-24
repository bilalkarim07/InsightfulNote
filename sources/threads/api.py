"""Public facade for the Threads integration.

The two required authentication methods are exposed at the top level:

    * exchange_short_lived_token(...)
    * refresh_long_lived_token()

Neither is invoked automatically anywhere in this module.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .auth import ThreadsAuth
from .client import ThreadsHTTPClient, ThreadsTokenProvider
from .exceptions import ThreadsAPIError, ThreadsValidationError
from .fields import (
    POST_FIELDS,
    PROFILE_FIELDS,
    REPLY_FIELDS,
    SEARCH_FIELDS,
    fields_to_string,
)
from .models import ThreadsToken, ThreadsTokenStatus
from .pagination import Page, paginate
from .token_store import EnvironmentThreadsTokenStore, ThreadsTokenStore

logger = logging.getLogger(__name__)


class _StoreTokenProvider(ThreadsTokenProvider):
    def __init__(self, store: ThreadsTokenStore) -> None:
        self._store = store

    def __call__(self) -> ThreadsToken:
        return self._store.load()


class ThreadsAPI:
    """High-level Threads API facade."""

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        token_store: ThreadsTokenStore | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._token_store = token_store or EnvironmentThreadsTokenStore(
            dotenv_path=".env"
        )
        self._auth = ThreadsAuth(
            app_id=app_id,
            app_secret=app_secret,
            timeout=timeout,
        )
        self._client = ThreadsHTTPClient(
            token_provider=_StoreTokenProvider(self._token_store),
            timeout=timeout,
        )

    # ==================================================================
    # Authentication
    # ==================================================================
    def exchange_short_lived_token(
        self,
        *,
        short_lived_token: str | None = None,
    ) -> ThreadsToken:
        """Exchange a short-lived token for a long-lived token.

        If ``short_lived_token`` is not provided, the token currently
        held in the token store (i.e. ``THREADS_ACCESS_TOKEN``) is used.
        The resulting long-lived token is written to the store.
        """
        if short_lived_token is None:
            short_lived_token = self._token_store.load().access_token.get_secret_value()

        long_lived = self._auth.exchange_short_lived_for_long_lived(
            short_lived_token=short_lived_token
        )
        current = self._token_store.load()
        long_lived.user_id = long_lived.user_id or current.user_id
        long_lived.username = long_lived.username or current.username
        self._token_store.save(long_lived)
        return long_lived

    def refresh_long_lived_token(self) -> ThreadsToken:
        """Manually refresh the stored long-lived token.

        Not invoked automatically anywhere.
        """
        current = self._token_store.load()
        refreshed = self._auth.refresh_long_lived_token(
            access_token=current.access_token.get_secret_value()
        )
        refreshed.user_id = refreshed.user_id or current.user_id
        refreshed.username = refreshed.username or current.username
        self._token_store.save(refreshed)
        return refreshed

    def get_token_status(self) -> ThreadsTokenStatus:
        token = self._token_store.load()
        return ThreadsTokenStatus(
            authenticated=True,
            username=token.username,
            user_id=token.user_id,
            token_type=token.token_type,
            scopes=list(token.scopes),
        )

    # ==================================================================
    # Reading
    # ==================================================================
    def search(
        self,
        *,
        query: str,
        search_type: str = "RECENT",
        search_mode: str = "KEYWORD",
        limit: int = 20,
        max_pages: int = 3,
    ) -> dict[str, Any]:
        """Search public Threads posts.

        Returns a dict with ``items``, ``pages_retrieved``, and ``raw``.
        """
        if not query:
            raise ThreadsValidationError("query must not be empty.")

        pages_retrieved = 0

        def _fetch(cursor: str | None) -> Page[dict[str, Any]]:
            nonlocal pages_retrieved
            params: dict[str, Any] = {
                "q": query,
                "search_type": search_type,
                "search_mode": search_mode,
                "fields": fields_to_string(SEARCH_FIELDS),
                "limit": min(limit, 100),
            }
            if cursor:
                params["after"] = cursor
            body = self._client.get(
                "/keyword_search",
                params=params,
                operation="keyword_search",
            )
            pages_retrieved += 1
            return Page.from_threads_response(body)

        items = paginate(_fetch, limit=limit, max_pages=max_pages)
        return {
            "items": items,
            "pages_retrieved": pages_retrieved,
            "query": query,
            "search_type": search_type,
            "search_mode": search_mode,
        }

    def get_post(self, post_id: str) -> dict[str, Any]:
        if not post_id:
            raise ThreadsValidationError("post_id must not be empty.")
        return self._client.get(
            f"/{post_id}",
            params={"fields": fields_to_string(POST_FIELDS)},
            operation="get_post",
        )

    def get_profile(
        self,
        *,
        username: str,
    ) -> dict[str, Any]:
        """Discover a public Threads profile by username."""
        if not username:
            raise ThreadsValidationError("username must not be empty.")
        return self._client.get(
            "/profile",
            params={
                "username": username,
                "fields": fields_to_string(PROFILE_FIELDS),
            },
            operation="profile_discovery",
        )

    def get_profile_posts(
        self,
        *,
        username: str,
        limit: int = 20,
        max_pages: int = 3,
    ) -> dict[str, Any]:
        pages_retrieved = 0

        def _fetch(cursor: str | None) -> Page[dict[str, Any]]:
            nonlocal pages_retrieved
            params: dict[str, Any] = {
                "username": username,
                "fields": fields_to_string(POST_FIELDS),
                "limit": min(limit, 100),
            }
            if cursor:
                params["after"] = cursor
            body = self._client.get(
                "/profile_posts",
                params=params,
                operation="profile_discovery",
            )
            pages_retrieved += 1
            return Page.from_threads_response(body)

        items = paginate(_fetch, limit=limit, max_pages=max_pages)
        return {"items": items, "pages_retrieved": pages_retrieved, "username": username}

    def get_my_posts(
        self,
        *,
        limit: int = 20,
        max_pages: int = 3,
    ) -> dict[str, Any]:
        token = self._token_store.load()
        user_id = token.user_id or "me"
        pages_retrieved = 0

        def _fetch(cursor: str | None) -> Page[dict[str, Any]]:
            nonlocal pages_retrieved
            params: dict[str, Any] = {
                "fields": fields_to_string(POST_FIELDS),
                "limit": min(limit, 100),
            }
            if cursor:
                params["after"] = cursor
            body = self._client.get(
                f"/{user_id}/threads",
                params=params,
                operation="get_my_posts",
            )
            pages_retrieved += 1
            return Page.from_threads_response(body)

        items = paginate(_fetch, limit=limit, max_pages=max_pages)
        return {"items": items, "pages_retrieved": pages_retrieved}

    def get_my_replies(
        self,
        *,
        limit: int = 20,
        max_pages: int = 3,
    ) -> dict[str, Any]:
        token = self._token_store.load()
        user_id = token.user_id or "me"
        pages_retrieved = 0

        def _fetch(cursor: str | None) -> Page[dict[str, Any]]:
            nonlocal pages_retrieved
            params: dict[str, Any] = {
                "fields": fields_to_string(REPLY_FIELDS),
                "limit": min(limit, 100),
            }
            if cursor:
                params["after"] = cursor
            body = self._client.get(
                f"/{user_id}/replies",
                params=params,
                operation="get_my_replies",
            )
            pages_retrieved += 1
            return Page.from_threads_response(body)

        items = paginate(_fetch, limit=limit, max_pages=max_pages)
        return {"items": items, "pages_retrieved": pages_retrieved}

    def get_replies(
        self,
        thread_id: str,
        *,
        limit: int = 50,
        max_pages: int = 3,
    ) -> dict[str, Any]:
        if not thread_id:
            raise ThreadsValidationError("thread_id must not be empty.")
        pages_retrieved = 0

        def _fetch(cursor: str | None) -> Page[dict[str, Any]]:
            nonlocal pages_retrieved
            params: dict[str, Any] = {
                "fields": fields_to_string(REPLY_FIELDS),
                "limit": min(limit, 100),
            }
            if cursor:
                params["after"] = cursor
            body = self._client.get(
                f"/{thread_id}/replies",
                params=params,
                operation="get_replies",
            )
            pages_retrieved += 1
            return Page.from_threads_response(body)

        items = paginate(_fetch, limit=limit, max_pages=max_pages)
        return {"items": items, "pages_retrieved": pages_retrieved, "post_id": thread_id}

    def get_conversation(
        self,
        thread_id: str,
        *,
        limit: int = 50,
        max_pages: int = 3,
    ) -> dict[str, Any]:
        if not thread_id:
            raise ThreadsValidationError("thread_id must not be empty.")
        pages_retrieved = 0

        def _fetch(cursor: str | None) -> Page[dict[str, Any]]:
            nonlocal pages_retrieved
            params: dict[str, Any] = {
                "fields": fields_to_string(REPLY_FIELDS),
                "limit": min(limit, 100),
            }
            if cursor:
                params["after"] = cursor
            body = self._client.get(
                f"/{thread_id}/conversation",
                params=params,
                operation="get_conversation",
            )
            pages_retrieved += 1
            return Page.from_threads_response(body)

        items = paginate(_fetch, limit=limit, max_pages=max_pages)
        return {"items": items, "pages_retrieved": pages_retrieved, "post_id": thread_id}

    # ==================================================================
    # Publishing (implemented but not exercised by the pipeline test)
    # ==================================================================
    def create_post(self, *, text: str) -> dict[str, Any]:
        if not text or not text.strip():
            raise ThreadsValidationError("Post text must not be empty.")
        token = self._token_store.load()
        user_id = token.user_id or "me"

        container = self._client.post(
            f"/{user_id}/threads",
            data={"media_type": "TEXT", "text": text},
            operation="create_post_container",
        )
        creation_id = container.get("id")
        if not creation_id:
            raise ThreadsAPIError("Container creation did not return an ID.", raw=container)

        from .exceptions import ThreadsPublishingError

        try:
            return self._client.post(
                f"/{user_id}/threads_publish",
                data={"creation_id": creation_id},
                operation="create_post_publish",
            )
        except Exception as exc:
            raise ThreadsPublishingError(
                f"Container {creation_id} created but publish failed: {exc}",
                container_id=creation_id,
            ) from exc

    def reply_to_post(self, *, post_id: str, text: str) -> dict[str, Any]:
        if not post_id:
            raise ThreadsValidationError("post_id must not be empty.")
        if not text or not text.strip():
            raise ThreadsValidationError("Reply text must not be empty.")
        token = self._token_store.load()
        user_id = token.user_id or "me"

        container = self._client.post(
            f"/{user_id}/threads",
            data={"media_type": "TEXT", "text": text, "reply_to_id": post_id},
            operation="reply_container",
        )
        creation_id = container.get("id")
        if not creation_id:
            raise ThreadsAPIError("Reply container creation did not return an ID.", raw=container)

        from .exceptions import ThreadsPublishingError

        try:
            return self._client.post(
                f"/{user_id}/threads_publish",
                data={"creation_id": creation_id},
                operation="reply_publish",
            )
        except Exception as exc:
            raise ThreadsPublishingError(
                f"Reply container {creation_id} created but publish failed: {exc}",
                container_id=creation_id,
            ) from exc

    def delete_post(self, post_id: str) -> dict[str, Any]:
        if not post_id:
            raise ThreadsValidationError("post_id must not be empty.")
        return self._client.delete(f"/{post_id}", operation="delete_post")

    # ==================================================================
    # Lifecycle
    # ==================================================================
    def close(self) -> None:
        self._client.close()
        self._auth.close()

    def __enter__(self) -> "ThreadsAPI":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()