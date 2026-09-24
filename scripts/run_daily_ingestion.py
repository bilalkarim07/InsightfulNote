"""Production daily ingestion runner. Suitable for GitHub Actions."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from sources.rss import RSSClient
from extraction.normalizers.article import extract_article
from etl.pipeline import IngestionPipeline


def main() -> int:
    print("Starting daily ingestion...")

    rss = RSSClient()
    try:
        result = rss.fetch("https://feeds.bbci.co.uk/news/rss.xml")
    finally:
        rss.close()

    candidates = result.items[:25]
    print(f"Discovered {len(candidates)} candidate(s).")

    items = []
    for cand in candidates:
        try:
            items.append(extract_article(cand.url))
        except Exception as exc:
            print(f"  ✗ Extraction failed for {cand.url}: {exc}")

    pipeline = IngestionPipeline()
    summary = pipeline.ingest(
        items,
        source_name="BBC News",
        source_type="rss",
        source_domain="bbc.co.uk",
    )
    summary.print_summary()

    if summary.inserted == 0 and summary.updated == 0 and summary.failed > 0:
        print("Fatal: no items ingested and failures occurred.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())