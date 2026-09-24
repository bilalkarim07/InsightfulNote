"""Pagination helpers for the Threads API."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """A single page of results from a paginated Threads endpoint."""

    items: list[T] = Field(default_factory=list)
    next_cursor: str | None = None
    has_next: bool = False

    @classmethod
    def from_threads_response(
        cls,
        body: dict[str, Any],
        *,
        item_key: str = "data",
        cursor_path: tuple[str, ...] = ("paging", "cursors", "after"),
    ) -> "Page[dict[str, Any]]":
        """Build a :class:`Page` from a raw Threads API response.

        The Threads API returns pagination metadata under
        ``paging.cursors.after``.  This helper normalises that into
        ``next_cursor`` / ``has_next``.
        """
        items = body.get(item_key, []) or []
        cursor: str | None = None

        current: Any = body
        for key in cursor_path:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                current = None
                break

        if isinstance(current, str) and current:
            cursor = current

        return cls(
            items=list(items),
            next_cursor=cursor,
            has_next=cursor is not None,
        )


def paginate(
    fetch_page: "Callable[[str | None], Page[T]]",
    *,
    limit: int = 20,
    max_pages: int = 3,
) -> list[T]:
    """Iterate pages until *limit* items or *max_pages* is reached.

    This is a safety mechanism – it prevents an LLM from requesting
    unlimited results and guards against infinite loops.
    """
    from typing import Callable  # noqa: F401 – used in annotation

    collected: list[T] = []
    cursor: str | None = None
    page_count = 0

    while page_count < max_pages and len(collected) < limit:
        page = fetch_page(cursor)
        collected.extend(page.items)
        page_count += 1

        if not page.has_next:
            break

        cursor = page.next_cursor

    return collected[:limit]