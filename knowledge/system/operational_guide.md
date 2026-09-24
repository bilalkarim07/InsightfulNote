# Operational Guide

## Daily funnel
25–50 candidates → 10–20 clusters → 5–10 shortlisted stories → ~5 verified stories → publishing.

## Daily publishing window
The execution plan specifies five daily posts between 7:00 PM and 11:00 PM in the configured US timezone.

## Storage
Supabase tables:
- stories
- sources
- claims
- evidence
- publications

Ephemeral candidates use a 30-day sliding retention window; published content is preserved.

## Modes
DRY_RUN: generate, validate, log intended publication; no live posts.
PRODUCTION: publish only after all gates pass.

## Emergency
If the configured 24-hour publication error threshold is exceeded, disable scheduling, move to dry-run, and create a critical operational issue.

## Maintenance
Prompts are versioned. Every workflow run records prompt version and provider/model. Provider fallback changes must remain observable.
