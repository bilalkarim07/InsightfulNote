"""Publisher facade — reuses tools.threads (spec §51).

Only the create_post path is exposed here. Search / read / reply stay
available to other agents via `tools.threads` directly.
"""
from __future__ import annotations

from typing import Any

_IMPORT_ERROR = ""
try:
    from tools.threads import threads_create_post  # type: ignore
    _THREADS_AVAILABLE = True
except ImportError as exc:
    threads_create_post = None
    _THREADS_AVAILABLE = False
    _IMPORT_ERROR = str(exc)


def threads_status() -> str:
    if _THREADS_AVAILABLE:
        return "WIRED"
    return f"UNAVAILABLE ({_IMPORT_ERROR})"


def _invoke_create(text: str) -> Any:
    if threads_create_post is None:
        raise RuntimeError("threads_create_post not available")
    # Try common argument names for the post text.
    for arg in ("text", "content", "message", "body", "post"):
        try:
            return threads_create_post.invoke({arg: text})
        except Exception:  # noqa: BLE001
            continue
    raise RuntimeError("could not invoke threads_create_post")


def publish_threads(text: str, dry_run: bool = True) -> dict[str, Any]:
    """Publish or simulate publishing to Threads.

    Returns a dict with keys: status, url, error.
    Never raises — the publisher must not crash the pipeline.
    """
    if dry_run:
        return {"status": "SKIPPED_DRY_RUN", "url": None, "error": None}

    if not _THREADS_AVAILABLE:
        return {
            "status": "FAILED",
            "url": None,
            "error": f"threads tool unavailable: {_IMPORT_ERROR}",
        }

    try:
        result = _invoke_create(text)
    except Exception as exc:  # noqa: BLE001
        return {"status": "FAILED", "url": None, "error": str(exc)}

    url = None
    if isinstance(result, dict):
        url = result.get("url") or result.get("permalink") or result.get("id")
    elif isinstance(result, str):
        url = result
    else:
        url = getattr(result, "url", None) or getattr(result, "id", None)
        url = str(url) if url is not None else None

    return {"status": "PUBLISHED", "url": url, "error": None}
