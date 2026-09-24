import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

print("=" * 40)
print("NEWSROOM TRANSFORMATION TEST")
print("=" * 40)

from sources.rss import RSSClient

client = RSSClient()
try:
    result = client.fetch("https://feeds.bbci.co.uk/news/rss.xml")
finally:
    client.close()

if not result.items:
    print("✗ No items discovered from RSS feed.")
    sys.exit(1)

raw = result.items[0]
print(f"\nSource: {raw.source_name or 'BBC'}")
print(f"Original URL: {raw.url}")
print(f"Title: {raw.title}")

from extraction.normalizers.article import extract_article

extracted = extract_article(raw.url)

from etl.transform.news_item import transform_news_item

persisted = transform_news_item(extracted)

print(f"\nCanonical URL: {persisted.canonical_url}")
print(f"Content length: {len(persisted.content or '')}")
print(f"Content hash: {persisted.content_hash}")
print(f"Canonical hash: {persisted.canonical_hash}")

print("\nTransformed object:")
print(persisted.model_dump_json(indent=2))
print("\n✓ Transformation completed successfully")