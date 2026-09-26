"""Audit: what is the actual state of the repo right now?"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path.cwd()

CHECKS = [
    # Supabase wiring
    ("core/tools/database/client.py", "Supabase client module"),
    ("core/tools/database/stories.py", "Semantic DB tools"),
    ("core/tools/database/schema.py", "Schema constants"),
    ("data/local_store.json", "LocalStore file (fallback evidence)"),
    (".env", ".env file"),

    # Runners
    ("scripts/run_news_ingestion.py", "Ingestion orchestrator"),
    ("scripts/agents/run_breaking_news.py", "Breaking runner"),
    ("scripts/agents/run_evening_reporting.py", "Evening runner"),

    # Old topic-queue system (must be retired per Step 4)
    ("scripts/agents/run_next_topic.py", "OLD: topic queue runner"),
    ("data/topic_queue.json", "OLD: topic queue state"),
    ("data/quota.json", "OLD: quota state (local JSON)"),
    (".github/workflows/newsroom.yml", "OLD: hourly newsroom workflow"),

    # Required new workflows
    (".github/workflows/news-ingestion.yml", "NEW: ingestion workflow"),
    (".github/workflows/hourly-breaking-news.yml", "NEW: breaking workflow"),
    (".github/workflows/evening-reporting.yml", "NEW: evening workflow"),

    # Threads
    ("tools/threads/_api_factory.py", "Threads API factory"),

    # Capability
    ("data/model_capabilities_manifest.json", "Capability manifest"),
]


def env_status():
    print("[environment]")
    for key in ("SUPABASE_URL", "SUPABASE_KEY", "TAVILY_API_KEY",
                "OLLAMA_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY",
                "THREADS_ACCESS_TOKEN"):
        v = os.environ.get(key, "")
        status = "SET" if v else "missing"
        print(f"  {key:24} {status}")
    print()


def file_status():
    print("[files]")
    for path, desc in CHECKS:
        p = ROOT / path
        mark = "EXISTS" if p.exists() else "missing"
        print(f"  [{mark:7}] {path:60} {desc}")
    print()


def local_store_summary():
    import json
    p = ROOT / "data" / "local_store.json"
    if not p.exists():
        print("[local_store] not present")
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[local_store] unreadable: {exc}")
        return
    print("[local_store]")
    for table, rows in data.items():
        print(f"  {table:16} {len(rows)} row(s)")
    print()


def main():
    print("=" * 74)
    print("NewsRoom — State Audit")
    print("=" * 74)
    print()
    env_status()
    file_status()
    local_store_summary()


if __name__ == "__main__":
    main()
