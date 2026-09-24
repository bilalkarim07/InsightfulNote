"""NewsRoom ETL Integration Test — executable, no test framework.

Flow:
    [1/7] Load environment
    [2/7] Fetch real source (BBC RSS)
    [3/7] Extract article
    [4/7] Transform NewsItem
    [5/7] Verify transformation determinism
    [6/7] Persist to Supabase
    [7/7] Verify persisted record (assertions)

Exits 0 on success, 1 on failure.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def _banner() -> None:
    print("=" * 60)
    print("NewsRoom ETL Integration Test")
    print("=" * 60)


def _fail(msg: str) -> None:
    print()
    print("=" * 60)
    print(f"ETL TEST FAILED: {msg}")
    print("=" * 60)
    raise SystemExit(1)


def main() -> int:
    _banner()

    # ---------------------------------------------------------------
    # [1/7] Environment
    # ---------------------------------------------------------------
    print("\n[1/7] Loading environment...")
    import os
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_SECRET_KEY"):
        _fail("SUPABASE_URL or SUPABASE_SECRET_KEY not set")
    print("OK")

    # ---------------------------------------------------------------
    # [2/7] Real source
    # ---------------------------------------------------------------
    print("\n[2/7] Fetching real source...")
    from sources.rss import RSSClient
    rss = RSSClient()
    try:
        result = rss.fetch("https://feeds.bbci.co.uk/news/rss.xml")
    finally:
        rss.close()

    if not result.items:
        _fail("no RSS items returned")
    candidates = result.items[:3]
    print(f"OK — BBC RSS ({len(candidates)} candidate(s))")

    # ---------------------------------------------------------------
    # [3/7] Extraction
    # ---------------------------------------------------------------
    print("\n[3/7] Extracting article...")
    from extraction.normalizers.article import extract_article
    news_items = []
    for cand in candidates:
        try:
            news_items.append(extract_article(cand.url))
        except Exception as exc:
            print(f"  SKIP {cand.url}: {exc}")
    if not news_items:
        _fail("no articles extracted")
    print(f"OK — {len(news_items)} article(s) extracted")

    # ---------------------------------------------------------------
    # [4/7] Transformation
    # ---------------------------------------------------------------
    print("\n[4/7] Transforming NewsItem...")
    from etl.transform.news_item import transform_news_item
    transformed = [transform_news_item(ni) for ni in news_items]
    print("OK")

    # ---------------------------------------------------------------
    # [5/7] Determinism check
    # ---------------------------------------------------------------
    print("\n[5/7] Verifying transformation determinism...")
    for original in news_items:
        t1 = transform_news_item(original)
        t2 = transform_news_item(original)
        if t1.id != t2.id:
            _fail(f"id not deterministic: {t1.id} vs {t2.id}")
        if t1.canonical_url != t2.canonical_url:
            _fail(f"canonical_url not deterministic for id={t1.id}")
        if t1.content_hash != t2.content_hash:
            _fail(f"content_hash not deterministic for id={t1.id}")
        if t1.canonical_hash != t2.canonical_hash:
            _fail(f"canonical_hash not deterministic for id={t1.id}")
    print("OK — id, canonical_url, content_hash, canonical_hash all stable")

    # ---------------------------------------------------------------
    # Print one transformed item for visual inspection
    # ---------------------------------------------------------------
    sample = transformed[0]
    print("\n--- TRANSFORMED NEWS ITEM (sample) ---")
    print(f"ID             : {sample.id}")
    print(f"Title          : {sample.title[:80]}")
    print(f"URL            : {sample.url}")
    print(f"Canonical URL  : {sample.canonical_url}")
    print(f"Content Hash   : {sample.content_hash}")
    print(f"Canonical Hash : {sample.canonical_hash}")
    print(f"Source Name    : {sample.source_name}")
    print(f"Source Domain  : {sample.source_domain}")
    print(f"Published At   : {sample.published_at}")
    print("--------------------------------------")

    # ---------------------------------------------------------------
    # [6/7] Persist (first run)
    # ---------------------------------------------------------------
    print("\n[6/7] Persisting to Supabase (run 1)...")
    from etl.pipeline import IngestionPipeline
    from etl.persistence.supabase import get_supabase

    client = get_supabase()
    pipeline = IngestionPipeline(client=client)

    summary_1 = pipeline.ingest(
        news_items,
        source_name="BBC News",
        source_type="rss",
        source_domain="bbc.co.uk",
    )
    summary_1.print_summary()
    if summary_1.failed:
        _fail(f"{summary_1.failed} item(s) failed during run 1")

    # ---------------------------------------------------------------
    # [7/7] Verify + idempotency re-run
    # ---------------------------------------------------------------
    print("\n[7/7] Verifying persisted record(s) against transformed object(s)...")
    for t in transformed:
        resp = (
            client.table("news_items")
            .select("id,title,url,canonical_url,source_id,content_hash,canonical_hash")
            .eq("id", t.id)
            .execute()
        )
        if not resp.data:
            _fail(f"record {t.id} not found in database")
        row = resp.data[0]

        # Hard assertions — the record must correspond to the transformed object
        assert row["id"] == t.id, f"id mismatch: {row['id']} != {t.id}"
        assert row["url"] == t.url, f"url mismatch for id={t.id}"
        assert row["canonical_url"] == t.canonical_url, f"canonical_url mismatch for id={t.id}"
        assert row["content_hash"] == t.content_hash, f"content_hash mismatch for id={t.id}"
        assert row["canonical_hash"] == t.canonical_hash, f"canonical_hash mismatch for id={t.id}"
        assert row["source_id"], f"source_id missing for id={t.id}"

        print(f"  ✓ {t.id}  verified (source_id={row['source_id']})")

    # --- Idempotency re-run: same items, must not create new rows ---
    print("\n[7b] Re-running ingestion to confirm idempotency...")
    summary_2 = pipeline.ingest(
        news_items,
        source_name="BBC News",
        source_type="rss",
        source_domain="bbc.co.uk",
    )
    summary_2.print_summary()

    if summary_2.inserted != 0:
        _fail(f"idempotency broken: run 2 inserted {summary_2.inserted} new row(s)")
    if summary_2.updated != len(transformed):
        _fail(
            f"idempotency broken: run 2 updated {summary_2.updated}, "
            f"expected {len(transformed)}"
        )

    # --- Final DB row count check for these ids ---
    for t in transformed:
        count_resp = (
            client.table("news_items")
            .select("id", count="exact")
            .eq("id", t.id)
            .execute()
        )
        if count_resp.count != 1:
            _fail(f"expected 1 row for id={t.id}, found {count_resp.count}")

    print()
    print("=" * 60)
    print("ETL TEST PASSED")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print()
        print("=" * 60)
        print(f"ETL TEST FAILED (unhandled): {exc}")
        print("=" * 60)
        raise SystemExit(1)