# Deterministic End-to-End Pipeline

0. Bootstrap: validate configuration, source registry, provider registry, DB connectivity, scheduler mode, and dry-run flag.
1. Discovery: GDELT, Google News RSS, DDGS, validated RSS; produce 25–50 candidates.
2. Extraction: fetch permitted content; parse clean metadata/body.
3. Normalize → Canonicalize → Hash → Deduplicate.
4. Clustering: group reports into ~10–20 story clusters.
5. Source Intelligence: assess provenance, authority, historical citation record, suspicious patterns.
6. Research: isolate claims and gather evidence.
7. Selection: rank by configured source weight, trend velocity, and global relevance; choose 5–10.
8. Verification: fact-check material claims; unsupported central claims block publication.
9. Editorial: approve claims, framing, tone, and platform requirements.
10. Writing: draft from approved claims only.
11. Hook: improve attention without changing factual meaning.
12. Platform Adaptation: X/LinkedIn/Substack/video transformation.
13. Final QA: schema, evidence, neutrality, uncertainty, duplicate, platform, CTA, and publication checks.
14. Publishing: publish and persist post IDs/timestamps/status.
15. Recovery: bounded retries; systemic failures trigger dry-run according to operational policy.

State:
DISCOVERED → EXTRACTED → NORMALIZED → CLUSTERED → RESEARCHED → SHORTLISTED → VERIFIED → EDITED → DRAFTED → QA_PASSED → PUBLISHED

Failure states:
EXTRACTION_FAILED, RESEARCH_BLOCKED, VERIFICATION_BLOCKED, EDITORIAL_BLOCKED, QA_FAILED, PUBLICATION_FAILED

No required gate may be skipped.
