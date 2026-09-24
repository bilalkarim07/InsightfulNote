"""Real live end-to-end check for every source + extraction pipeline.

Usage:
    python -m scripts.live_pipeline_check
    python -m scripts.live_pipeline_check "OpenAI GPT-5"
    python -m scripts.live_pipeline_check "climate policy" --max 5
"""

from __future__ import annotations

# Load .env before anything else reads os.environ.
from core import env  # noqa: F401  (side-effect import)

import argparse
import json
import os
import sys
import time
import traceback
from typing import Any, Dict, List, Optional

from core.exceptions import SourceError
from extraction.canonicalization.url import canonicalize_url, dedupe_urls
from extraction.fetchers.resolvers import (
    is_google_news_redirect,
    resolve_google_news_url,
)
from extraction.normalizers.article import extract_article

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

SEP = "=" * 78
SUB = "-" * 78


def header(title: str) -> None:
    print(f"\n{SEP}\n{title}\n{SEP}")


def sub(title: str) -> None:
    print(f"\n{SUB}\n{title}\n{SUB}")


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def info(msg: str) -> None:
    print(f"         {msg}")


def shorten(s: Optional[str], n: int = 110) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def show_items(items, limit: int = 5) -> None:
    if not items:
        info("(no items)")
        return
    for i, it in enumerate(items[:limit], 1):
        info(f"{i}. {shorten(it.title, 90)}")
        info(f"    url:       {it.url}")
        info(f"    canonical: {it.canonical_url}")
        if it.source_name:
            info(f"    source:    {it.source_name}")
        if it.published_at:
            info(f"    published: {it.published_at.isoformat()}")
    if len(items) > limit:
        info(f"    ... and {len(items) - limit} more")


def _looks_extractable(url: str) -> bool:
    if not url:
        return False
    low = url.lower()
    bad_ext = (
        ".pdf", ".zip", ".jpg", ".jpeg", ".png", ".gif",
        ".mp4", ".mp3", ".svg", ".webp",
    )
    if any(low.endswith(ext) for ext in bad_ext):
        return False
    if any(seg in low for seg in ("/video/", "/videos/", "/gallery/", "/live/")):
        return False
    return True


# ---------------------------------------------------------------------------
# individual pipelines
# ---------------------------------------------------------------------------

def run_gdelt(query: str, max_results: int) -> List[str]:
    sub(f"GDELT — search({query!r}, max_results={max_results}, timespan='7d')")
    from sources.gdelt import GDELTClient

    with GDELTClient() as client:
        t0 = time.perf_counter()
        result = client.search(query, max_results=max_results, timespan="7d")
        dt = time.perf_counter() - t0

    ok(f"{len(result.items)} items in {dt:.2f}s")
    show_items(result.items)
    return [i.url for i in result.items]


def run_google_news(query: str, max_results: int) -> List[str]:
    sub(f"Google News RSS — search({query!r}, max_results={max_results})")
    from sources.google_news import GoogleNewsClient

    with GoogleNewsClient() as client:
        t0 = time.perf_counter()
        result = client.search(query, max_results=max_results)
        dt = time.perf_counter() - t0

    ok(f"{len(result.items)} items in {dt:.2f}s")
    show_items(result.items)
    return [i.url for i in result.items]


def run_ddgs_text(query: str, max_results: int) -> List[str]:
    sub(f"DDGS text_search({query!r}, max_results={max_results}, timelimit='w')")
    from sources.ddgs import DDGSClient

    with DDGSClient() as client:
        t0 = time.perf_counter()
        result = client.text_search(query, max_results=max_results, timelimit="w")
        dt = time.perf_counter() - t0

    ok(f"{len(result.items)} items in {dt:.2f}s")
    show_items(result.items)
    return [i.url for i in result.items]


def run_ddgs_news(query: str, max_results: int) -> List[str]:
    sub(f"DDGS news_search({query!r}, max_results={max_results}, timelimit='w')")
    from sources.ddgs import DDGSClient

    with DDGSClient() as client:
        t0 = time.perf_counter()
        result = client.news_search(query, max_results=max_results, timelimit="w")
        dt = time.perf_counter() - t0

    ok(f"{len(result.items)} items in {dt:.2f}s")
    show_items(result.items)
    return [i.url for i in result.items]


def run_tavily_search(query: str, max_results: int) -> List[str]:
    sub(f"Tavily — search({query!r}, max_results={max_results}, topic='news')")
    from sources.tavily import TavilyClient

    with TavilyClient() as client:
        t0 = time.perf_counter()
        result = client.search(query, max_results=max_results, topic="news")
        dt = time.perf_counter() - t0

    ok(f"{len(result.items)} items in {dt:.2f}s")
    show_items(result.items)
    return [i.url for i in result.items]


def run_tavily_extract(url: str) -> Optional[str]:
    sub(f"Tavily — extract([{url!r}])")
    from sources.tavily import TavilyClient

    with TavilyClient() as client:
        t0 = time.perf_counter()
        result = client.extract([url])
        dt = time.perf_counter() - t0

    if not result.items:
        fail("no items returned")
        return None

    item = result.items[0]
    ok(f"extracted in {dt:.2f}s")
    info(f"title:   {shorten(item.title, 100)}")
    info(f"content: {len(item.content or '')} chars")
    info(f"preview: {shorten(item.content or '', 200)}")
    return item.content


def run_publisher_restricted(
    query: str, domain: str, max_results: int, source: str = "google_news"
) -> None:
    sub(f"Publisher-restricted search — source={source}, domain={domain}")
    if source == "google_news":
        from sources.google_news import GoogleNewsClient
        with GoogleNewsClient() as client:
            result = client.search(query, max_results=max_results, domains=[domain])
    elif source == "ddgs":
        from sources.ddgs import DDGSClient
        with DDGSClient() as client:
            result = client.news_search(query, max_results=max_results, domains=[domain])
    else:
        fail(f"unknown source {source}")
        return

    if not result.items:
        info(f"no results restricted to {domain} (this is a valid outcome)")
        return

    # Note: Google News always returns news.google.com wrapper URLs, so a
    # direct substring check on `domain` will miss. We inspect the titles /
    # source names as a best-effort indicator of coverage.
    hits = [i for i in result.items if domain in i.url]
    titled = [
        i for i in result.items
        if domain.split(".")[0].lower() in (i.title or "").lower()
    ]
    ok(
        f"{len(result.items)} items  "
        f"(direct-URL match: {len(hits)}, title mentions domain: {len(titled)})"
    )
    show_items(result.items)


def run_gnews_resolution(urls: List[str]) -> Optional[str]:
    """Demonstrate gnews wrapper resolution and return the first resolved URL."""
    sub("Google News wrapper resolution")
    gnews_urls = [u for u in urls if is_google_news_redirect(u)]
    if not gnews_urls:
        info("(no google-news wrappers in this run)")
        return None

    target = gnews_urls[0]
    info(f"resolving: {target}")
    try:
        t0 = time.perf_counter()
        resolved = resolve_google_news_url(target)
        dt = time.perf_counter() - t0
    except Exception as exc:
        fail(f"{type(exc).__name__}: {exc}")
        return None

    if resolved != target and not is_google_news_redirect(resolved):
        ok(f"resolved in {dt:.2f}s → {resolved}")
        return resolved

    fail("resolver returned the wrapper unchanged")
    return None


def run_extraction(urls: List[str], attempts: int = 5) -> None:
    sub(f"Generic extraction — trying up to {attempts} candidate URLs")

    extractable = [u for u in urls if _looks_extractable(u)]
    non_gnews = [u for u in extractable if not is_google_news_redirect(u)]
    gnews = [u for u in extractable if is_google_news_redirect(u)]
    # Always try at least one gnews wrapper at the end so the resolver is exercised.
    candidates = non_gnews[: attempts * 2] + gnews[:1]

    if not candidates:
        fail("no extractable candidates discovered")
        return

    info(
        f"candidate pool: {len(non_gnews)} direct + {len(gnews)} google-news wrappers "
        f"(trying {len(candidates)})"
    )

    tried = 0
    for url in candidates:
        tried += 1
        info(f"[{tried}] {url}")
        try:
            t0 = time.perf_counter()
            item = extract_article(url)
            dt = time.perf_counter() - t0

            if not item.content or len(item.content) < 200:
                fail(
                    f"content too short ({len(item.content or '')} chars) "
                    f"in {dt:.2f}s — trying next"
                )
                continue

            ok(f"extracted {len(item.content)} chars in {dt:.2f}s")
            info(f"title:     {shorten(item.title, 100)}")
            info(f"author:    {item.author}")
            info(f"published: {item.published_at.isoformat() if item.published_at else None}")
            info(f"canonical: {item.canonical_url}")
            if item.metadata.get("original_url") != item.url:
                info(f"original:  {item.metadata.get('original_url')}")
                info(f"resolved:  {item.metadata.get('resolved_url')}")
                if item.metadata.get("resolver_error"):
                    info(f"resolver:  {item.metadata.get('resolver_error')}")
            info(f"preview:   {shorten(item.content, 240)}")
            return
        except SourceError as exc:
            fail(f"{type(exc).__name__}: {shorten(str(exc), 160)}")
            continue
        except Exception as exc:
            fail(f"unexpected {type(exc).__name__}: {shorten(str(exc), 160)}")
            continue

    fail(f"all {tried} candidates failed extraction")


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", default="OpenAI")
    ap.add_argument("--max", type=int, default=8, help="max results per source")
    ap.add_argument(
        "--publisher",
        default="reuters.com",
        help="domain for the publisher-restricted search test",
    )
    args = ap.parse_args()

    query = args.query
    max_results = args.max

    header(f"LIVE PIPELINE CHECK — query={query!r}, max={max_results}")
    info(f"Tavily key present: {bool(os.getenv('TAVILY_API_KEY'))}")

    all_urls: List[str] = []
    failures: List[str] = []

    for name, fn in [
        ("GDELT", run_gdelt),
        ("Google News", run_google_news),
        ("DDGS text", run_ddgs_text),
        ("DDGS news", run_ddgs_news),
    ]:
        try:
            all_urls.extend(fn(query, max_results))
        except SourceError as exc:
            fail(f"{name}: {type(exc).__name__}: {exc}")
            failures.append(name)
        except Exception as exc:
            fail(f"{name}: unexpected {type(exc).__name__}: {exc}")
            traceback.print_exc()
            failures.append(name)

    if os.getenv("TAVILY_API_KEY"):
        try:
            all_urls.extend(run_tavily_search(query, max_results))
        except SourceError as exc:
            fail(f"Tavily: {type(exc).__name__}: {exc}")
            failures.append("Tavily")
        except Exception as exc:
            fail(f"Tavily: unexpected {type(exc).__name__}: {exc}")
            failures.append("Tavily")
    else:
        sub("Tavily — skipped (TAVILY_API_KEY not set)")

    # ------------------------------------------------------------------
    header("URL canonicalization + dedupe")
    unique = dedupe_urls(all_urls)
    gn_count = sum(1 for u in unique if is_google_news_redirect(u))
    info(
        f"raw URLs: {len(all_urls)}  →  unique: {len(unique)}  "
        f"(google-news wrappers: {gn_count})"
    )
    for u in unique[:15]:
        tag = "  [gnews]" if is_google_news_redirect(u) else ""
        info(f"  {u}{tag}")
    if len(unique) > 15:
        info(f"  ... and {len(unique) - 15} more")

    # ------------------------------------------------------------------
    header("Publisher-restricted discovery")
    for dom in [args.publisher, "cnn.com", "bbc.com"]:
        try:
            run_publisher_restricted(query, dom, max_results=5, source="google_news")
        except Exception as exc:
            fail(f"{dom}: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    header("Google News wrapper resolution")
    resolved_for_tavily = run_gnews_resolution(unique)

    # ------------------------------------------------------------------
    header("Generic article extraction")
    run_extraction(unique)

    # ------------------------------------------------------------------
    if os.getenv("TAVILY_API_KEY"):
        header("Tavily extract (native extract endpoint)")
        # Prefer the resolved gnews URL so Tavily gets a real publisher page.
        target = resolved_for_tavily or next(
            (u for u in unique if not is_google_news_redirect(u)), None
        )
        if target:
            try:
                run_tavily_extract(target)
            except Exception as exc:
                fail(f"Tavily extract: {type(exc).__name__}: {exc}")
        else:
            info("(no URL to extract)")

    # ------------------------------------------------------------------
    header("SUMMARY")
    if failures:
        print("Pipelines with failures:")
        for f in failures:
            print(f"  - {f}")
        print("\nPaste this full output back and I'll patch the failing clients.")
        return 1

    print("All pipelines completed without source-level errors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())