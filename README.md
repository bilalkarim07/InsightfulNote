# InsightfulNote

InsightfulNote is an evidence-led newsroom pipeline that ingests news sources,
selects story candidates, verifies claims, and can publish approved posts to
Threads. The current production platform is **Threads**; other platform adapters
are deferred.

## Architecture

```text
Curated direct RSS feeds (primary) / Google News / DDGS / GDELT
  -> deterministic extraction, normalization, canonicalization, deduplication,
     time-aware cross-source clustering, and Supabase persistence
  -> story selection and editorial memory
  -> candidate interpretation -> source intelligence -> research
  -> verification -> editorial -> tone -> writer -> Threads adapter
  -> deterministic QA -> duplicate protection -> Threads
  -> Supabase publication record
```

External news discovery is performed by the deterministic ETL. The graph's
Discovery stage interprets and validates a candidate already loaded from the
database; it does not perform discovery searches. Tavily remains available as
an opt-in provider only when `NEWSROOM_ENABLE_TAVILY=true`.
Supabase is the source of truth for ingested stories, source links, editorial
memory inputs, and publication records. Per-run research, verification, and
editorial outputs are captured in run snapshots. A production runner fails
closed if Supabase is not available; local storage is for development only.
Direct feed definitions live in `sources/rss/feeds.json`; feeds run once per
ingestion, in configured priority order, and direct-RSS items are deduplicated
before persistence.

Each production run selects one verified LLM model for the newsroom graph.
Capability-aware per-agent model routing is a future improvement.

## GitHub Actions

- `news-ingestion.yml` runs daily deterministic ingestion.
- `hourly-breaking-news.yml` evaluates breaking candidates every 30 minutes.
- `evening-reporting.yml` runs hourly from 8–11 PM America/New_York.

Scheduled and manually dispatched breaking and evening runs use the same
production behavior: qualified, validated posts are sent to Threads without
daily caps, spacing limits, or active-hour restrictions. Duplicate protection
and publication safeguards remain in place. Shared local/development runs may
still use `dry_run=True`; the two production runners always publish.

Breaking posts retain evidence and independent-source eligibility checks. A
single linked source can enter research; verification still determines whether
claims are publishable.

## Local setup

Use Python 3.12 or newer. Install dependencies and create a private `.env`:

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set only the credentials needed for the services in use. The example file
contains names and placeholders only; never commit `.env`.
Useful executable checks and tasks:

```powershell
python scripts/run_news_ingestion.py
python scripts/test_category_classification.py
python scripts/test_supabase_pipeline.py
python scripts/test_editorial_memory.py
python scripts/test_selection_pipeline.py
python scripts/test_llm_routing.py
python scripts/agents/test_agent_contracts.py
python scripts/agents/test_router.py
```

The executable checks are scripts; this project does not use pytest or
unittest as its test framework. Some scripts call real external services or
modify database state; inspect the script and service configuration before
running them. Never run synthetic/demo data against the production database.

## Production configuration

See `.env.example` for supported variable names. Production execution requires
Supabase URL/key, a verified configured LLM, non-Tavily search providers needed
by the research path, and a valid `THREADS_ACCESS_TOKEN`. Threads account/application
settings are also listed there. Production workflows require these credentials
and publish automatically when a post passes the existing safeguards. If
credentials or database connectivity are absent, the production workflow must
stop rather than use local or synthetic data.

## Editorial and publication safeguards

Every factual claim must be evidence-backed; source references and uncertainty
must be preserved. Allegations and forecasts remain attributed, political
content is descriptive rather than persuasive, and the Writer may use only
approved claims. Deterministic QA and duplicate checks run before the
Threads API call. The publication record is reserved before sending; uncertain
outcomes block automatic republishing and require reconciliation with the
Threads account.

Operational automation that disables scheduling after an error threshold and
opens an incident is **future work**, not an implemented safeguard.