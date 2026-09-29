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

from datetime import datetime, timezone
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


def _error_details(exc: Exception) -> tuple[str, dict[str, Any]]:
    """Return useful API diagnostics without logging response bodies or tokens."""
    details: dict[str, Any] = {"error_type": type(exc).__name__}
    cause = exc.__cause__
    if cause is not None:
        details["cause_type"] = type(cause).__name__
    for prefix, source in (("", exc), ("cause_", cause)):
        if source is None:
            continue
        for attribute in (
            "status_code", "error_code", "error_subcode", "error_type", "fbtrace_id",
        ):
            value = getattr(source, attribute, None)
            if value is not None:
                details[prefix + attribute] = value
    fields = [
        f"{key}={details[key]}"
        for key in (
            "status_code", "error_code", "error_subcode", "fbtrace_id",
            "cause_type", "cause_status_code", "cause_error_code",
        )
        if key in details
    ]
    summary = type(exc).__name__
    if fields:
        summary += " (" + ", ".join(fields) + ")"
    return summary, details


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
        error, details = _error_details(exc)
        return {
            "status": "FAILED",
            "external_id": None,
            "url": None,
            "error": f"build_threads_api: {error}",
            "diagnostic": details,
        }

    try:
        result = api.create_post(text=text)
    except Exception as exc:  # noqa: BLE001
        from sources.threads.exceptions import ThreadsPublishingError

        error, details = _error_details(exc)
        uncertain = isinstance(exc, ThreadsPublishingError)
        cause_status = details.get("cause_status_code")
        if (
            uncertain
            and isinstance(cause_status, int)
            and 400 <= cause_status < 500
            and cause_status not in (408, 425)
        ):
            uncertain = False
        return {
            "status": "UNKNOWN" if uncertain else "FAILED",
            "external_id": None,
            "url": None,
            "error": (
                "Threads publish request may have succeeded; reconciliation required: "
                + error
                if uncertain
                else f"create_post: {error}"
            ),
            "diagnostic": details,
        }
    finally:
        try:
            api.close()
        except Exception:
            pass

    ext_id, url = _extract_id_and_url(result)
    if not ext_id:
        response_shape = {
            "response_type": type(result).__name__,
            "response_keys": sorted(str(key) for key in result)[:30]
            if isinstance(result, dict) else [],
        }
        return {
            "status": "UNKNOWN",
            "external_id": None,
            "url": url,
            "error": "Threads API returned no publication ID; outcome requires reconciliation.",
            "diagnostic": response_shape,
        }
    return {
        "status": "PUBLISHED",
        "external_id": ext_id,
        "url": url,
        "error": None,
        "diagnostic": {
            "response_type": type(result).__name__,
            "response_keys": sorted(str(key) for key in result)[:30]
            if isinstance(result, dict) else [],
        },
    }


def reconcile_threads_publication(
    text: str,
    *,
    started_at: str | None,
) -> dict[str, Any] | None:
    """Find one exact matching post created after a reserved publication attempt."""
    if not started_at:
        raise ValueError("publication reservation has no started_at timestamp")
    if not _AVAILABLE:
        raise RuntimeError(f"Threads API unavailable: {_IMPORT_ERROR}")

    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("publication reservation has an invalid started_at timestamp") from exc
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)

    api = build_threads_api()
    try:
        response = api.get_my_posts(limit=50, max_pages=3)
    finally:
        api.close()

    matches = []
    for post in response.get("items", []):
        if post.get("text") != text:
            continue
        created_at = post.get("timestamp")
        if not created_at:
            continue
        try:
            created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        except ValueError:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created >= started:
            external_id, url = _extract_id_and_url(post)
            if external_id:
                matches.append({
                    "external_id": external_id,
                    "url": url,
                    "published_at": created.isoformat(),
                })
    if len(matches) > 1:
        raise RuntimeError("multiple matching Threads posts found; manual reconciliation required")
    return matches[0] if matches else None
