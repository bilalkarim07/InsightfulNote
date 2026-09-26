"""Search tools for the agent layer.

Per spec §50, we DO NOT rebuild search tools. The existing repository
already exposes LangChain StructuredTools in `tools.search`. We re-export
them and provide a single `search_web` facade for agent convenience.

Fallback order for the facade: tavily -> ddgs_news -> google_news -> gdelt.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

# ── Import existing tools — DO NOT REBUILD ──
_IMPORT_ERROR = ""
try:
    from tools.search import (  # type: ignore
        tavily_search,
        tavily_extract,
        ddgs_news_search,
        ddgs_text_search,
        google_news_search,
        gdelt_search,
    )
    _REAL_TOOLS_AVAILABLE = True
except ImportError as exc:
    tavily_search = None
    tavily_extract = None
    ddgs_news_search = None
    ddgs_text_search = None
    google_news_search = None
    gdelt_search = None
    _REAL_TOOLS_AVAILABLE = False
    _IMPORT_ERROR = str(exc)


def real_tools_status() -> str:
    if _REAL_TOOLS_AVAILABLE:
        return "WIRED"
    return f"UNAVAILABLE ({_IMPORT_ERROR})"


def _invoke_tool(tool_obj: Any, query: str) -> str:
    """Invoke a StructuredTool with a query, trying common argument names."""
    if tool_obj is None:
        raise RuntimeError("tool is None")
    for arg in ("query", "q", "text", "search_query"):
        try:
            return str(tool_obj.invoke({arg: query}))
        except Exception:  # noqa: BLE001
            continue
    raise RuntimeError(f"could not invoke {getattr(tool_obj, 'name', '?')}")


@tool
def search_web(query: str) -> str:
    """Search the web for a query.

    Routes through the existing repo tools in fallback order:
    tavily -> ddgs_news -> google_news -> gdelt.
    """
    if not _REAL_TOOLS_AVAILABLE:
        return f"[search unavailable: {_IMPORT_ERROR}]"

    candidates = [
        ("tavily", tavily_search),
        ("ddgs_news", ddgs_news_search),
        ("google_news", google_news_search),
        ("gdelt", gdelt_search),
    ]
    errors: list[str] = []
    for name, t in candidates:
        if t is None:
            continue
        try:
            return _invoke_tool(t, query)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
    return "Search failed: " + "; ".join(errors)


@tool
def search_primary_source(query: str) -> str:
    """Search specifically for primary / official sources."""
    return search_web.invoke({"query": f"official {query}"})


ALL_SEARCH_TOOLS = [
    t for t in (
        tavily_search, tavily_extract,
        ddgs_news_search, ddgs_text_search,
        google_news_search, gdelt_search,
        search_web, search_primary_source,
    ) if t is not None
]
