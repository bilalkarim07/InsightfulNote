
# Verification Policy

## 1. Purpose

Verification determines whether specific claims about a story are adequately supported by available evidence.

Verification is a claim-level process.

Its purpose is to establish whether the newsroom has sufficient evidence to publish a factual statement.

---

## 2. Responsibility

The Verification system is responsible for:

- Checking claims against evidence.
- Determining evidence sufficiency.
- Identifying contradictions.
- Checking source agreement.
- Checking dates and currentness.
- Checking quotations.
- Checking numbers and statistics.
- Assigning claim-level confidence.
- Blocking unsupported claims.

Verification does not determine whether a story is interesting or suitable for publication.

---

## 3. Inputs

The Verification system receives:

- Candidate claims.
- Extracted source content.
- Source metadata.
- Evidence records.
- Research results.
- Official statements where available.
- Cross-source comparisons.
- Story timestamps.

---

## 4. Primary Tasks

For each material claim:

1. Identify the exact claim.
2. Identify supporting evidence.
3. Determine evidence quality.
4. Check source relevance.
5. Check source recency.
6. Check whether the evidence actually supports the claim.
7. Check for contradictions.
8. Check attribution.
9. Assign confidence.
10. Decide whether the claim is publishable.

---

## 5. Source / Evidence Rules

Evidence should be evaluated according to the newsroom evidence hierarchy:

### A — Primary / Official / Direct

Examples:

- Government statements.
- Company announcements.
- Official documents.
- Official APIs.
- Court documents.
- Direct statements.
- Original datasets.

### B — Reputable Direct Reporting

Established news organizations directly reporting the event.

### C — Corroborating Secondary Sources

Additional reporting that independently supports the claim.

### D — Discovery / Social Signals

Examples:

- Search snippets.
- Social posts.
- Unverified user reports.
- Aggregators.

Category D is primarily a lead and should not normally serve as sole proof for important claims.

---

## 6. Decision Rules

### Rule 1 — Claim-Level Verification

A source may be credible while a specific claim remains unsupported.

Verification must evaluate the claim itself.

### Rule 2 — Evidence Must Entail the Claim

The evidence must actually support what is being stated.

Topical similarity is not sufficient.

### Rule 3 — Conflicting Evidence

If credible sources disagree:

- Preserve the conflict.
- Identify the disagreement.
- Avoid choosing a side without sufficient evidence.
- Reduce confidence when appropriate.

### Rule 4 — Time Sensitivity

Current events require current evidence.

Old evidence must not automatically be treated as evidence of the current state.

### Rule 5 — Quotes

Quotes require direct source evidence or reliable transcription.

### Rule 6 — Numbers

Numbers require explicit supporting evidence.

Do not estimate missing numbers.

### Rule 7 — Configurable Threshold

The verification similarity/confidence threshold specified by the newsroom configuration should be treated as the publication gate.

The PDF execution plan specifies an 85% verification similarity threshold as the initial safeguard; implementation should keep this threshold configurable rather than hard-code it.

---

## 7. Scoring

Verification may calculate:

- `claim_confidence`
- `evidence_strength`
- `source_agreement`
- `source_diversity`
- `recency`
- `contradiction_level`

These scores describe evidence support.

They must not be confused with:

- source reputation,
- story importance,
- political desirability,
- engagement potential.

---

## 8. Prohibited Actions

Verification must not:

- Treat search snippets as final proof.
- Treat repeated copying as independent corroboration.
- Assume a reputable source is always correct.
- Assume multiple sources are independent without checking.
- Fill missing evidence with assumptions.
- Invent corroboration.
- Ignore contradictions.
- Convert uncertainty into certainty.
- Verify a claim using the claim itself.
- Use political preference as evidence quality.

---

## 9. Escalation

Escalate or block when:

- Evidence is insufficient.
- Important claims conflict.
- A primary source cannot be located.
- A quote cannot be confirmed.
- Numbers cannot be verified.
- The event appears outdated.
- The evidence threshold is not met.
- A claim requires speculation.

Blocked claims must not enter final publication.

---

## 10. Output

For each claim, return:

- `claim_id`
- `claim_text`
- `supporting_evidence_ids`
- `support_level`
- `confidence`
- `source_agreement`
- `contradictions`
- `attribution_required`
- `verification_status`

Possible statuses:

- `VERIFIED`
- `PARTIALLY_VERIFIED`
- `UNVERIFIED`
- `CONTRADICTED`
- `BLOCKED`

---

## 11. Quality Gate

A story passes verification only when:

- Material claims have sufficient evidence.
- Evidence actually supports the claims.
- Important contradictions are identified.
- Quotes are supported.
- Numbers are supported.
- Currentness has been checked.
- Attribution is correct.
- The configured verification threshold is satisfied.
- Unsupported claims are removed or blocked.
