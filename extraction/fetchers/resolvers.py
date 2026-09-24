"""Best-effort resolvers for redirect-wrapper URLs returned by some sources.

Currently handles Google News RSS article URLs of the form
``https://news.google.com/rss/articles/<opaque>``.

Order of attempts (fast → slow):
  1. ``googlenewsdecoder`` package (handles Google's current encoding).
  2. Offline base64/protobuf decode (legacy formats).
  3. HTTP redirect (follow_redirects=True).
  4. <meta http-equiv="refresh" content="0; url=...">.

If all four fail, the original URL is returned unchanged. Callers must
tolerate that — extraction will simply yield no content.

Note: an earlier version included a fifth attempt that returned the first
non-Google anchor found in the response HTML. That fallback has been
removed because it could not distinguish the article link from
advertisements, navigation, social widgets, or unrelated articles. Failing
closed is preferable to producing a wrong evidence URL.
"""

from __future__ import annotations

import base64
import re
from urllib.parse import urlparse

import httpx

from core.exceptions import SourceConnectionError

GOOGLE_NEWS_HOST = "news.google.com"
_GNEWS_RSS_PREFIX = "/rss/articles/"

_META_REFRESH_RE = re.compile(
    r"""<meta[^>]+http-equiv\s*=\s*["']?refresh["']?[^>]+content\s*=\s*["']?\s*\d+\s*;\s*url=([^"'>\s]+)""",
    re.IGNORECASE,
)

# URL-ish byte sequence inside decoded protobuf payloads.
_HTTP_IN_BYTES_RE = re.compile(rb"https?://[^\x00-\x1f\"'\\<> ]")

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


def is_google_news_redirect(url: str) -> bool:
    """Return True if ``url`` is a Google News RSS article wrapper."""
    try:
        p = urlparse(url)
    except Exception:
        return False
    return p.netloc == GOOGLE_NEWS_HOST and p.path.startswith(_GNEWS_RSS_PREFIX)


# ---------------------------------------------------------------------------
# attempt 1: googlenewsdecoder package
# ---------------------------------------------------------------------------


def _decode_with_package(url: str) -> str | None:
    """Use the googlenewsdecoder package if it is installed.

    The package internally calls Google's batchexecute endpoint, which is
    what currently powers the *real* redirect. Returns ``None`` if the
    package is missing or the decode fails.
    """
    try:
        from googlenewsdecoder import gnewsdecoder  # type: ignore
    except Exception:
        return None

    try:
        result = gnewsdecoder(url)
    except Exception:
        return None

    # The package has returned different shapes across versions.
    if isinstance(result, str):
        return result or None
    if isinstance(result, dict):
        decoded = result.get("decoded_url")
        if isinstance(decoded, str) and decoded:
            return decoded
    return None


# ---------------------------------------------------------------------------
# attempt 2: offline base64 decode (legacy formats)
# ---------------------------------------------------------------------------


def _extract_id(url: str) -> str | None:
    try:
        path = urlparse(url).path
    except Exception:
        return None
    if not path.startswith(_GNEWS_RSS_PREFIX):
        return None
    tail = path[len(_GNEWS_RSS_PREFIX):]
    # Strip any trailing path segments (rare) and query.
    tail = tail.split("/")[0].split("?")[0]
    return tail or None


def _decode_google_news_id(url: str) -> str | None:
    """Try to decode the article id into a publisher URL without HTTP.

    Google News has used several encodings over the years. We try a couple
    of common variants and return the first plausible http(s) URL that is
    not on a Google domain.
    """
    article_id = _extract_id(url)
    if not article_id:
        return None

    candidates = [article_id]
    # Some ids embed a leading marker we can strip to make the payload decodable.
    for marker in (
        "CBMiW0FVX3",
        "CBMiW0FV",
        "CBMiW0",
        "CBMiugFB",
        "CBMiqwFB",
        "CBMiqAFB",
        "CBMi",
    ):
        if article_id.startswith(marker):
            candidates.append(article_id[len(marker):])
            break

    # Try to decode progressively; base64 padding is often wrong on purpose.
    for candidate in candidates:
        for pad in ("", "=", "==", "==="):
            padded = candidate + pad
            try:
                raw = base64.urlsafe_b64decode(padded)
            except Exception:
                continue
            match = _HTTP_IN_BYTES_RE.search(raw)
            if not match:
                continue
            decoded = match.group(0).decode("utf-8", errors="ignore")
            host = urlparse(decoded).netloc.lower()
            if host and host != GOOGLE_NEWS_HOST and not host.endswith(".google.com"):
                return decoded

    # Last resort: try decoding the entire suffix directly.
    try:
        padded = article_id + "=" * (-len(article_id) % 4)
        raw = base64.urlsafe_b64decode(padded)
        for match in _HTTP_IN_BYTES_RE.finditer(raw):
            decoded = match.group(0).decode("utf-8", errors="ignore")
            host = urlparse(decoded).netloc.lower()
            if host and host != GOOGLE_NEWS_HOST and not host.endswith(".google.com"):
                return decoded
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# attempts 3-4: HTTP-based fallbacks
# ---------------------------------------------------------------------------


def _resolve_via_http(url: str, timeout: float) -> str | None:
    headers = {
        "User-Agent": _BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        with httpx.Client(
            timeout=timeout, follow_redirects=True, headers=headers
        ) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SourceConnectionError(
            f"Failed to resolve Google News URL: {exc}",
            source="google_news",
            operation="resolve",
            url=url,
            cause=exc,
        ) from exc

    # Attempt 3: redirect already landed off-google.
    final_host = urlparse(str(response.url)).netloc.lower()
    if (
        final_host
        and final_host != GOOGLE_NEWS_HOST
        and not final_host.endswith(".google.com")
    ):
        return str(response.url)

    # Attempt 4: <meta http-equiv="refresh">
    match = _META_REFRESH_RE.search(response.text or "")
    if match:
        candidate = match.group(1)
        host = urlparse(candidate).netloc.lower()
        if host and host != GOOGLE_NEWS_HOST:
            return candidate

    # No confident answer. Fail closed — the caller handles this as
    # "unresolved wrapper" and continues without fabricating a URL.
    return None


def resolve_google_news_url(url: str, timeout: float = 20.0) -> str:
    """Return the publisher URL behind a Google News wrapper, or ``url`` unchanged."""
    if not is_google_news_redirect(url):
        return url

    # Attempt 1: googlenewsdecoder (handles current Google encoding).
    decoded = _decode_with_package(url)
    if decoded:
        return decoded

    # Attempt 2: offline base64 (legacy formats).
    decoded = _decode_google_news_id(url)
    if decoded:
        return decoded

    # Attempts 3-4: HTTP fallbacks.
    resolved = _resolve_via_http(url, timeout)
    if resolved:
        return resolved

    return url