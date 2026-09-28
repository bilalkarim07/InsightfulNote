# Operational Guide

## Daily funnel
The desired funnel is approximately 25–50 candidates → 10–20 clusters → 5–10 shortlisted stories → ~5 verified stories → publishing. These are planning targets, not enforced counts.

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

## Emergency automation
Automated scheduling shutdown, forced dry-run, and critical-issue creation after a publication-error threshold are future operational work. Operators must monitor runs and disable live scheduling manually if publication safety is uncertain.

## Maintenance
The current production run selects one verified provider/model for the whole agent graph. Per-agent capability routing is future work.
