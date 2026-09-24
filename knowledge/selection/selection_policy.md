
# Selection Policy

## 1. Purpose

Selection determines which verified or sufficiently researched story candidates should proceed to editorial processing and publication.

Selection is a prioritization process.

It must not be used to determine whether a claim is true.

---

## 2. Responsibility

The Selection system is responsible for:

- Ranking story candidates for newsroom processing.
- Applying configured editorial priorities.
- Balancing recency and significance.
- Considering evidence availability.
- Reducing duplicate coverage.
- Selecting a manageable publication set.

Selection must remain independent from political preference or engagement manipulation.

---

## 3. Inputs

Selection receives:

- Story clusters.
- Verified claims.
- Source intelligence.
- Research results.
- Story timestamps.
- Source diversity.
- Global relevance signals.
- Trend velocity.
- Editorial constraints.
- Publication capacity.

---

## 4. Primary Tasks

Selection should:

1. Evaluate candidate stories.
2. Remove duplicates.
3. Consider evidence availability.
4. Consider global relevance.
5. Consider recency.
6. Consider source diversity.
7. Consider trend velocity.
8. Consider public significance.
9. Consider editorial value.
10. Produce the publication shortlist.

The execution plan targets a funnel approximately:

`25–50 candidates → 10–20 clusters → 5–10 shortlisted → ~5 verified stories`

These values should remain configurable.

---

## 5. Source / Evidence Rules

Selection should favor stories with:

- Sufficient evidence.
- Multiple independent sources where appropriate.
- Strong primary-source support where available.
- Recent and relevant reporting.
- Clear factual boundaries.

Selection must not treat popularity alone as evidence.

---

## 6. Decision Rules

A candidate may be evaluated using:

- Global relevance.
- Recency.
- Evidence availability.
- Source diversity.
- Public significance.
- Trend velocity.
- Uniqueness.
- Editorial value.
- Publication suitability.

### Selection Funnel

Selection should progressively reduce the candidate set.

Example:


```text
Discovery
↓
Candidate stories
↓
Deduplication
↓
Clustering
↓
Research
↓
Selection scoring
↓
Shortlist
↓
Verification
↓
Editorial
```


Political Content

Political stories must be selected based on documented editorial criteria such as relevance, significance, evidence, and recency.

Selection must not favor or suppress a political actor because of political preference.

7. Scoring

Selection may use a weighted score containing:

global_relevance
recency
evidence_availability
source_diversity
public_significance
trend_velocity
uniqueness
editorial_value
publication_suitability

The weights must be configurable.

Selection scores represent publication priority only.

They do not represent:

Truth.
Moral importance.
Political desirability.
Public approval.
Candidate quality.
8. Prohibited Actions

Selection must not:

Select stories solely for outrage.
Suppress stories because they are politically inconvenient.
Favor political actors.
Rank candidates or political parties.
Treat engagement as proof.
Manufacture importance.
Select an unverified claim merely because it is trending.
Remove important stories solely because they are difficult to write.
Convert selection scores into factual confidence.
9. Escalation

Escalate when:

Evidence is insufficient.
Multiple clusters may represent the same event.
Story importance cannot be distinguished using configured criteria.
Political content creates a potential neutrality conflict.
A story has high trend velocity but weak evidence.
Candidate information is materially contradictory.
10. Output

Selection should return:

selected_story_ids
rejected_story_ids
selection_scores
selection_reasons
priority_order
selection_timestamp

The reason should describe the configured selection criteria, not subjective political preference.

11. Quality Gate

Selection passes when:

Duplicate stories have been consolidated.
Selected stories meet minimum evidence requirements.
Selection criteria are applied consistently.
Political content is handled neutrally.
The shortlist fits publication capacity.
Selection does not override verification requirements.
