
# Evidence Policy

## 1. Purpose

The Evidence Policy defines how the newsroom evaluates, stores, and uses evidence supporting factual claims.

---

## 2. Responsibility

The system must maintain a traceable relationship between:

```text
Source
→ Evidence
→ Claim
→ Story
→ Published Content
3. Inputs

Evidence may originate from:

Official documents.
Official APIs.
Direct statements.
Reputable reporting.
Search/research systems.
Public social platforms.
Structured feeds.
4. Primary Tasks

The evidence system must:

Capture source metadata.
Preserve relevant evidence.
Associate evidence with claims.
Track source type.
Track retrieval time.
Track evidence status.
Support verification.
Preserve auditability.
5. Source / Evidence Rules

Evidence hierarchy:

A

Primary, official, direct evidence.

B

Reputable direct reporting.

C

Independent corroborating sources.

D

Discovery signals and social content.

Evidence category D should generally lead to further research rather than serve as sole proof for material claims.

6. Decision Rules

Evidence must be:

Relevant.
Traceable.
Current enough for the claim.
Specific enough to support the claim.
Properly attributed.

Multiple copies of the same original report do not automatically count as independent corroboration.

7. Scoring

Evidence may include:

evidence_strength
source_score
recency
independence
claim_support

These values must remain distinct.

8. Prohibited Actions

Do not:

Manufacture evidence.
Treat search snippets as full evidence without inspection.
Treat repeated reporting as independent confirmation.
Remove contradictory evidence without recording the decision.
Use unsupported evidence to increase confidence.
9. Escalation

Escalate when:

Evidence conflicts.
Source independence is unclear.
Evidence is incomplete.
A primary source is unavailable.
The evidence cannot support the exact claim.
10. Output

Evidence records should contain, where available:

evidence_id
source_id
claim_id
content
source_type
publisher
url
retrieved_at
published_at
evidence_strength
verification_status
11. Quality Gate

Every material published claim must have traceable supporting evidence or an explicitly documented basis for attribution.
```
