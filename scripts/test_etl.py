import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

print("=" * 40)
print("NEWSROOM FULL ETL TEST")
print("=" * 40)

# --- 1. Discover real news ---
from sources.rss import RSSClient

print("\n[1/4] Discovering news from RSS...")
client = RSSClient()
try:
    result = client.fetch("https://feeds.bbci.co.uk/news/rss.xml")
finally:
    client.close()

candidates = result.items[:3]
print(f"Discovered {len(candidates)} candidate(s)")

# --- 2. Extract articles ---
from extraction.normalizers.article import extract_article

items = []
for cand in candidates:
    try:
        item = extract_article(cand.url)
        items.append(item)
        print(f"  ✓ Extracted: {item.title[:60]}...")
    except Exception as exc:
        print(f"  ✗ Extraction failed for {cand.url}: {exc}")

if not items:
    print("✗ No articles extracted.")
    sys.exit(1)

# --- 3. Transform ---
from etl.transform.news_item import transform_news_item

print("\n[2/4] Transforming news items...")
transformed = [transform_news_item(i) for i in items]
for t in transformed:
    hash_part = t.content_hash[:12] if t.content_hash else "N/A"
    print(f"  ✓ Transformed: {t.id} | hash={hash_part}...")

# --- 4. Load into Supabase ---
from etl.pipeline import IngestionPipeline

print("\n[3/4] Loading into Supabase...")
pipeline = IngestionPipeline()
summary = pipeline.ingest(
    items,
    source_name="BBC News",
    source_type="rss",
    source_domain="bbc.co.uk",
)
summary.print_summary()

# --- 5. Verify ---
print("\n[4/4] Verifying persisted records...")
from etl.persistence.supabase import get_supabase

client = get_supabase()
for t in transformed:
    resp = (
        client.table("news_items")
        .select("id, title, url, canonical_url, source_id, content_hash, canonical_hash")
        .eq("id", t.id)
        .execute()
    )
    if resp.data:
        row = resp.data[0]
        print(f"\n✓ Verified record:")
        print(f"  ID: {row['id']}")
        print(f"  Title: {row['title'][:80]}...")
        print(f"  URL: {row['url']}")
        print(f"  Canonical URL: {row['canonical_url']}")
        print(f"  Source ID: {row['source_id']}")
        print(f"  Content hash: {row['content_hash']}")
        print(f"  Canonical hash: {row['canonical_hash']}")
    else:
        print(f"\n✗ Record {t.id} not found in database!")

print("\n✓ Full ETL test completed")