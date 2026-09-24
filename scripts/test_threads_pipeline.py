"""Interactive CLI for live-testing the Threads read/discovery pipeline.

Usage
-----
    python scripts/test_threads_pipeline.py
    python scripts/test_threads_pipeline.py --verbose

This script deliberately bypasses the LLM/agent layer so the underlying
client, pagination, error handling, and normalisation can be verified
independently.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # type: ignore  # noqa: E402

from sources.threads.api import ThreadsAPI  # noqa: E402
from sources.threads.exceptions import (  # noqa: E402
    ThreadsError,
)
from schemas.threads.posts import SocialPost, ThreadsPost  # noqa: E402
from schemas.threads.profiles import ThreadsProfile  # noqa: E402
from schemas.threads.replies import SocialReply, ThreadsReply  # noqa: E402


ENV_PATH = ROOT / ".env"


# ===========================================================================
# Helpers
# ===========================================================================
def _print_header(title: str) -> None:
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def _print_subheader(title: str) -> None:
    print()
    print("-" * 60)
    print(f"  {title}")
    print("-" * 60)


def _build_api() -> ThreadsAPI:
    return ThreadsAPI(
        app_id=os.environ.get("THREADS_APP_ID", ""),
        app_secret=os.environ.get("THREADS_APP_SECRET", ""),
    )


def _handle_error(exc: Exception) -> None:
    print()
    print("=" * 60)
    print("  THREADS API ERROR")
    print("=" * 60)
    if isinstance(exc, ThreadsError):
        # Rich, structured output with Meta code labels and suggested action.
        print(exc.pretty())
    else:
        print(f"Type:    {exc.__class__.__name__}")
        print(f"Message: {exc}")
    print("=" * 60)


def _verbose_dump(label: str, data: Any, verbose: bool) -> None:
    if not verbose:
        return
    print()
    print(f"[VERBOSE] {label}:")
    print(json.dumps(data, indent=2, default=str)[:4000])


def _print_post(post: ThreadsPost, index: int | None = None) -> None:
    prefix = f"POST {index}" if index is not None else "POST"
    print(f"\n## {prefix}")
    print(f"  ID:        {post.id}")
    print(f"  Author:    @{post.username or '?'}")
    print(f"  Timestamp: {post.timestamp.isoformat() if post.timestamp else '?'}")
    text = (post.text or "").strip().replace("\n", " ")
    print(f"  Text:      {text[:300]}{'…' if len(text) > 300 else ''}")
    print(f"  Media:     {post.media_type or '-'}")
    print(f"  URL:       {post.permalink or '-'}")


def _print_reply(reply: ThreadsReply, index: int) -> None:
    print(f"\n  Reply #{index}")
    print(f"    ID:        {reply.id}")
    print(f"    Author:    @{reply.username or '?'}")
    print(f"    Timestamp: {reply.timestamp.isoformat() if reply.timestamp else '?'}")
    text = (reply.text or "").strip().replace("\n", " ")
    print(f"    Text:      {text[:250]}{'…' if len(text) > 250 else ''}")
    print(f"    URL:       {reply.permalink or '-'}")


# ===========================================================================
# Individual tests
# ===========================================================================
def test_keyword_search(api: ThreadsAPI, verbose: bool) -> None:
    _print_header("KEYWORD SEARCH")
    query = input("Enter keyword: ").strip()
    if not query:
        print("[SKIP] Empty keyword.")
        return
    stype = input("Search type [RECENT/TOP, default RECENT]: ").strip().upper() or "RECENT"
    try:
        limit = int(input("Limit [default 25]: ").strip() or "25")
    except ValueError:
        limit = 25
    try:
        pages = int(input("Max pages [default 2]: ").strip() or "2")
    except ValueError:
        pages = 2

    result = api.search(
        query=query,
        search_type=stype,
        limit=limit,
        max_pages=pages,
    )
    _print_subheader("RESULTS")
    print(f"Query:              {result['query']}")
    print(f"Search type:        {result['search_type']}")
    print(f"Pages retrieved:    {result['pages_retrieved']}")
    print(f"Results:            {len(result['items'])}")

    for i, item in enumerate(result["items"], 1):
        _print_post(ThreadsPost.from_api(item), i)
        _verbose_dump(f"raw post {i}", item, verbose)


def test_profile_discovery(api: ThreadsAPI, verbose: bool) -> None:
    _print_header("PROFILE DISCOVERY")
    username = input("Enter username (without @): ").strip().lstrip("@")
    if not username:
        print("[SKIP] Empty username.")
        return
    raw = api.get_profile(username=username)
    profile = ThreadsProfile.from_api(raw)
    _print_subheader("PROFILE")
    print(f"Username:     @{profile.username}")
    print(f"ID:           {profile.id}")
    print(f"Name:         {profile.name or '-'}")
    print(f"Bio:          {(profile.biography or '-')[:200]}")
    print(f"Followers:    {profile.follower_count if profile.follower_count is not None else '-'}")
    print(f"Verified:     {profile.is_verified}")
    _verbose_dump("raw profile", raw, verbose)


def test_profile_posts(api: ThreadsAPI, verbose: bool) -> None:
    _print_header("PROFILE POSTS")
    username = input("Enter username (without @): ").strip().lstrip("@")
    if not username:
        print("[SKIP] Empty username.")
        return
    try:
        limit = int(input("Number of posts [default 10]: ").strip() or "10")
    except ValueError:
        limit = 10
    result = api.get_profile_posts(username=username, limit=limit, max_pages=2)
    _print_subheader(f"@{username} – {len(result['items'])} POSTS")
    for i, item in enumerate(result["items"], 1):
        _print_post(ThreadsPost.from_api(item), i)
        _verbose_dump(f"raw post {i}", item, verbose)


def test_read_post(api: ThreadsAPI, verbose: bool) -> None:
    _print_header("READ INDIVIDUAL POST")
    post_id = input("Post ID: ").strip()
    if not post_id:
        print("[SKIP] Empty post ID.")
        return
    raw = api.get_post(post_id)
    post = ThreadsPost.from_api(raw)
    _print_subheader("POST")
    _print_post(post)
    _verbose_dump("raw post", raw, verbose)


def test_read_replies(api: ThreadsAPI, verbose: bool) -> None:
    _print_header("READ REPLIES (top-level)")
    post_id = input("Post ID: ").strip()
    if not post_id:
        print("[SKIP] Empty post ID.")
        return
    try:
        limit = int(input("Limit [default 25]: ").strip() or "25")
    except ValueError:
        limit = 25
    result = api.get_replies(post_id, limit=limit, max_pages=2)
    _print_subheader(f"REPLIES – {len(result['items'])}")
    for i, item in enumerate(result["items"], 1):
        _print_reply(ThreadsReply.from_api(item), i)
        _verbose_dump(f"raw reply {i}", item, verbose)


def test_read_conversation(api: ThreadsAPI, verbose: bool) -> None:
    _print_header("READ CONVERSATION")
    post_id = input("Post ID: ").strip()
    if not post_id:
        print("[SKIP] Empty post ID.")
        return
    try:
        limit = int(input("Limit [default 50]: ").strip() or "50")
    except ValueError:
        limit = 50
    result = api.get_conversation(post_id, limit=limit, max_pages=2)
    _print_subheader(f"CONVERSATION – {len(result['items'])} entries")
    for i, item in enumerate(result["items"], 1):
        reply = ThreadsReply.from_api(item)
        _print_reply(reply, i)
        _verbose_dump(f"raw conversation item {i}", item, verbose)


def test_my_posts(api: ThreadsAPI, verbose: bool) -> None:
    _print_header("MY POSTS")
    try:
        limit = int(input("Limit [default 10]: ").strip() or "10")
    except ValueError:
        limit = 10
    result = api.get_my_posts(limit=limit, max_pages=2)
    _print_subheader(f"AUTHENTICATED USER POSTS – {len(result['items'])}")
    for i, item in enumerate(result["items"], 1):
        _print_post(ThreadsPost.from_api(item), i)
        _verbose_dump(f"raw post {i}", item, verbose)


# ===========================================================================
# Composite tests
# ===========================================================================
def _normalise_posts(raw_items: list[dict]) -> list[SocialPost]:
    return [SocialPost.from_threads_post(ThreadsPost.from_api(x)) for x in raw_items]


def test_full_evidence(api: ThreadsAPI, verbose: bool) -> None:
    """Full evidence pipeline: search + profiles + posts + replies + conversations."""
    _print_header("FULL EVIDENCE TEST")

    keyword = input("Keyword [default OpenAI]: ").strip() or "OpenAI"
    profiles_input = input(
        "Profiles (comma-separated) [default openai,cnn,abc]: "
    ).strip()
    profiles = [p.strip().lstrip("@") for p in profiles_input.split(",") if p.strip()]
    if not profiles:
        profiles = ["openai", "cnn", "abc"]

    # 1. Search -----------------------------------------------------------
    _print_subheader(f"SEARCH – {keyword}")
    search = api.search(query=keyword, search_type="RECENT", limit=25, max_pages=2)
    search_socials = _normalise_posts(search["items"])
    print(f"Search results:     {len(search_socials)}")
    print(f"Pages retrieved:    {search['pages_retrieved']}")

    # 2. Profiles + their posts ------------------------------------------
    all_profile_posts: dict[str, list[SocialPost]] = {}
    for username in profiles:
        _print_subheader(f"PROFILE @{username}")
        try:
            api.get_profile(username=username)
        except ThreadsError as exc:
            print(f"  [SKIP] Could not load profile: {exc}")
            continue
        try:
            result = api.get_profile_posts(username=username, limit=10, max_pages=1)
        except ThreadsError as exc:
            print(f"  [SKIP] Could not load posts: {exc}")
            continue
        posts = _normalise_posts(result["items"])
        all_profile_posts[username] = posts
        print(f"  Recent posts:     {len(posts)}")
        for i, p in enumerate(posts, 1):
            text = (p.text or "").replace("\n", " ")
            print(f"    [{i}] {p.id} | {p.created_at} | {text[:80]}")
            _verbose_dump(f"@{username} post {i}", p.model_dump(), verbose)

    # 3. Read replies on a few selected posts -----------------------------
    _print_subheader("REPLIES / CONVERSATION SAMPLING")
    selected_ids: list[str] = []
    for username, posts in all_profile_posts.items():
        for p in posts[:2]:  # first 2 per profile
            selected_ids.append(p.id)
    # also add a couple from search results
    for p in search_socials[:2]:
        selected_ids.append(p.id)

    total_replies = 0
    total_conversations = 0
    for post_id in selected_ids:
        try:
            replies = api.get_replies(post_id, limit=15, max_pages=1)
            total_replies += len(replies["items"])
        except ThreadsError:
            pass
        try:
            convo = api.get_conversation(post_id, limit=15, max_pages=1)
            total_conversations += len(convo["items"])
        except ThreadsError:
            pass

    # 4. Report -----------------------------------------------------------
    _print_header("THREADS EVIDENCE REPORT")
    print(f"QUERY:                 {keyword}")
    print(f"SEARCH RESULTS:        {len(search_socials)}")
    print(f"OFFICIAL PROFILES:     {len(all_profile_posts)}")
    print(f"OFFICIAL PROFILE POSTS:{sum(len(v) for v in all_profile_posts.values())}")
    print(f"REPLIES RETRIEVED:     {total_replies}")
    print(f"CONVERSATION ENTRIES:  {total_conversations}")
    print(f"TOTAL POSTS:           {len(search_socials) + sum(len(v) for v in all_profile_posts.values())}")
    print("=" * 60)


def test_global_news_discovery(api: ThreadsAPI, verbose: bool) -> None:
    """Placeholder for the multi-source global news discovery experiment.

    Currently only demonstrates the Threads enrichment portion.  The
    GDELT / RSS / DDGS discovery steps will be added in a later
    milestone.
    """
    _print_header("GLOBAL NEWS DISCOVERY (Threads enrichment)")
    print("NOTE: Global discovery is intended to combine GDELT, Google News,")
    print("      RSS feeds and DDGS first, then enrich with Threads evidence.")
    print("      This test currently exercises only the Threads enrichment step.")
    print()

    topic = input("Topic [default OpenAI]: ").strip() or "OpenAI"

    _print_subheader(f"Threads enrichment for topic '{topic}'")
    try:
        result = api.search(query=topic, search_type="TOP", limit=20, max_pages=2)
        posts = _normalise_posts(result["items"])
        print(f"Top posts:           {len(posts)}")
        for i, p in enumerate(posts[:5], 1):
            text = (p.text or "").replace("\n", " ")
            print(f"  [{i}] @{p.author_username} – {text[:100]}")
    except ThreadsError as exc:
        _handle_error(exc)

    print()
    print("Threads API does NOT provide a global trending discovery endpoint.")
    print("Global discovery must come from GDELT / Google News / RSS / DDGS.")


# ===========================================================================
# Menu
# ===========================================================================
MENU = """
==================================================
  NEWSROOM THREADS PIPELINE TEST
==================================================

  1. Keyword Search
  2. Profile Discovery
  3. Profile Posts
  4. Read Individual Post
  5. Read Replies
  6. Read Conversation
  7. My Posts
  8. Full Evidence Test
  9. Global News Discovery Test
 10. Exit
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Threads pipeline live test")
    parser.add_argument("--verbose", action="store_true", help="Show raw API metadata")
    args = parser.parse_args()

    load_dotenv(ENV_PATH)

    if not os.environ.get("THREADS_ACCESS_TOKEN"):
        print("[ERROR] THREADS_ACCESS_TOKEN is not set. Run scripts/setup_threads_auth.py first.")
        return 1

    api = _build_api()

    try:
        status = api.get_token_status()
        print("=" * 60)
        print("  THREADS TOKEN STATUS")
        print("=" * 60)
        print(f"Authenticated:  {status.authenticated}")
        print(f"User ID:        {status.user_id or '(unknown)'}")
        print(f"Username:       {status.username or '(unknown)'}")
    except ThreadsError as exc:
        _handle_error(exc)
        return 1

    try:
        while True:
            print(MENU)
            choice = input("Choose an option: ").strip()
            try:
                if choice == "1":
                    test_keyword_search(api, args.verbose)
                elif choice == "2":
                    test_profile_discovery(api, args.verbose)
                elif choice == "3":
                    test_profile_posts(api, args.verbose)
                elif choice == "4":
                    test_read_post(api, args.verbose)
                elif choice == "5":
                    test_read_replies(api, args.verbose)
                elif choice == "6":
                    test_read_conversation(api, args.verbose)
                elif choice == "7":
                    test_my_posts(api, args.verbose)
                elif choice == "8":
                    test_full_evidence(api, args.verbose)
                elif choice == "9":
                    test_global_news_discovery(api, args.verbose)
                elif choice == "10":
                    print("Exiting.")
                    return 0
                else:
                    print("Invalid option.")
            except ThreadsError as exc:
                _handle_error(exc)
            except KeyboardInterrupt:
                print("\nInterrupted.")
                return 0
    finally:
        api.close()


if __name__ == "__main__":
    raise SystemExit(main())