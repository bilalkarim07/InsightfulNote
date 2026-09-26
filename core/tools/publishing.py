"""Publisher facade — direct ThreadsAPI, not LangChain tool wrapper.

Uses tools.threads._api_factory.build_threads_api() for auth.
Exposes one function: publish_threads(text, dry_run) -> dict.

Returned dict keys:
  status:        PUBLISHED | SKIPPED_DRY_RUN | FAILED
  external_id:   Threads post ID (only when PUBLISHED)
  url:           permalink (only when PUBLISHED)
  error:         failure detail (only when FAILED)
"""
from __future__ import annotations

from typing import Any

_IMPORT_ERROR = ""
_AVAILABLE = False

try:
    from tools.threads._api_factory import build_threads_api  # type: ignore
    _AVAILABLE = True
except Exception as _exc:
    build_threads_api = None
    _IMPORT_ERROR = str(_exc)


def threads_status() -> str:
    if _AVAILABLE:
        return "WIRED"
    return f"UNAVAILABLE ({_IMPORT_ERROR})"


def _extract_id_and_url(result: Any) -> tuple[str | None, str | None]:
    """Best-effort extraction of Threads post ID and permalink from any shape."""
    if not isinstance(result, dict):
        return (None, None)

    ext_id = (
        result.get("id")
        or result.get("post_id")
        or result.get("threads_id")
        or result.get("external_post_id")
    )
    # Some wrappers nest under 'data' or 'response'
    for key in ("data", "response", "result"):
        nested = result.get(key)
        if isinstance(nested, dict):
            ext_id = ext_id or nested.get("id")
            # Prefer the deepest ID.
            if nested.get("id"):
                ext_id = nested.get("id")

    url = (
        result.get("permalink")
        or result.get("url")
        or result.get("link")
    )
    for key in ("data", "response", "result"):
        nested = result.get(key)
        if isinstance(nested, dict):
            url = url or nested.get("permalink") or nested.get("url")

    return (
        str(ext_id) if ext_id is not None else None,
        str(url) if url else None,
    )


def publish_threads(text: str, dry_run: bool = True) -> dict[str, Any]:
    """Publish or simulate publishing to Threads.

    Never raises — the publisher must not crash the pipeline.
    """
    if dry_run:
        return {
            "status": "SKIPPED_DRY_RUN",
            "external_id": None,
            "url": None,
            "error": None,
        }

    if not _AVAILABLE:
        return {
            "status": "FAILED",
            "external_id": None,
            "url": None,
            "error": f"threads api unavailable: {_IMPORT_ERROR}",
        }

    if not text or not text.strip():
        return {
            "status": "FAILED",
            "external_id": None,
            "url": None,
            "error": "empty text",
        }

    try:
        api = build_threads_api()
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "FAILED",
            "external_id": None,
            "url": None,
            "error": f"build_threads_api: {type(exc).__name__}: {exc}",
        }

    try:
        result = api.create_post(text=text)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "FAILED",
            "external_id": None,
            "url": None,
            "error": f"create_post: {type(exc).__name__}: {exc}",
        }
    finally:
        try:
            api.close()
        except Exception:
            pass

    ext_id, url = _extract_id_and_url(result)
    return {
        "status": "PUBLISHED",
        "external_id": ext_id,
        "url": url,
        "error": None,
    }
