"""Table and column names — single source of truth for all DB tools."""
from __future__ import annotations

STORIES = "stories"
SOURCES = "sources"
CLAIMS = "claims"
EVIDENCE = "evidence"
PUBLICATIONS = "publications"
PIPELINE_RUNS = "pipeline_runs"

# Primary keys
PK_STORY = "story_id"
PK_SOURCE = "source_id"
PK_CLAIM = "claim_id"
PK_EVIDENCE = "evidence_id"
PK_PUBLICATION = "publication_id"

# Publication constraints
PLATFORM_THREADS = "threads"