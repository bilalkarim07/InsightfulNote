"""URL canonicalization utilities."""

from __future__ import annotations

from typing import Iterable, Optional
from urllib.parse import (
    parse_qsl,
    quote,
    unquote,
    urlencode,
    urlsplit,
    urlunsplit,
)

_TRACKING_PREFIXES = ("utm_", "ga_", "mc_", "pk_")
_TRACKING_EXACT = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "yclid",
    "_openstat",
    "igshid",
    "ref",
    "ref_src",
    "ref_url",
    "spm",
    "cmpid",
    "ncid",
}


def _strip_tracking(query: str) -> str:
    if not query:
        return ""
    pairs = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        lk = key.lower()
        if lk in _TRACKING_EXACT:
            continue
        if any(lk.startswith(p) for p in _TRACKING_PREFIXES):
            continue
        pairs.append((key, value))
    pairs.sort()
    return urlencode(pairs, doseq=True)


def canonicalize_url(url: str) -> Optional[str]:
    """Return a canonical form of ``url`` or ``None`` if it can't be parsed."""
    if not url:
        return None
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return None

    if not parts.scheme or not parts.netloc:
        return None

    scheme = parts.scheme.lower()
    if scheme in ("http", "https"):
        # Prefer https for canonical form only if scheme is already https.
        pass
    else:
        return None

    netloc = parts.netloc.lower()
    # Strip default ports.
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    elif netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]

    path = parts.path or "/"
    # Collapse duplicate slashes.
    while "//" in path:
        path = path.replace("//", "/")
    # Strip trailing slash except for root.
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    # Re-quote path safely.
    path = quote(unquote(path), safe="/:@!$&'()*+,;=")

    query = _strip_tracking(parts.query)
    fragment = ""  # drop fragments

    return urlunsplit((scheme, netloc, path, query, fragment))


def dedupe_urls(urls: Iterable[str]) -> list[str]:
    """Return canonical URLs, preserving first-seen order, dropping duplicates."""
    seen = set()
    out: list[str] = []
    for raw in urls:
        c = canonicalize_url(raw)
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out