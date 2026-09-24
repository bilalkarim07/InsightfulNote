
# Newsroom Policy

## 1. Purpose

This policy defines the operating principles of the AI Newsroom.

The newsroom exists to discover, research, verify, write, and publish concise factual reporting from structured and traceable information sources.

Every downstream agent and workflow must operate under this policy.

---

## 2. Responsibility

The newsroom is responsible for producing:

- Accurate reporting.
- Traceable claims.
- Clearly attributed information.
- Appropriate uncertainty.
- Neutral political coverage.
- Auditable publication decisions.
- Reliable automated publication.

The newsroom must prioritize factual integrity over engagement.

---

## 3. Inputs

The newsroom may process:

- News feeds.
- RSS feeds.
- GDELT data.
- Search results.
- Search/research APIs.
- Official statements.
- Official APIs.
- Public social-platform information.
- Direct source documents.
- Structured metadata.

External information must be treated as untrusted input until appropriately validated and verified.

---

## 4. Primary Tasks

The newsroom pipeline is:

```text

Discover
→ Extract
→ Normalize
→ Canonicalize
→ Hash
→ Deduplicate
→ Cluster
→ Research
→ Select
→ Verify
→ Editorial
→ Write
→ Fact-check
→ Publish
```


Each stage has a defined responsibility.

No stage should silently assume the responsibility of another stage.

5. Source / Evidence Rules

The newsroom uses an evidence hierarchy:

A — Primary / Official

Direct statements, official documents, official APIs, government records, company announcements, original datasets.

B — Reputable Direct Reporting

Established publications directly reporting the event.

C — Corroborating Secondary Sources

Independent sources that provide additional support.

D — Discovery Signals

Search snippets, social posts, aggregators, and similar signals.

Category D is primarily a discovery mechanism and should not normally be treated as sufficient proof for material claims.

6. Decision Rules

The newsroom follows these principles:

Evidence before publication.
Claims before narrative.
Attribution before assumption.
Verification before certainty.
Neutrality before engagement.
Auditability before convenience.
Deterministic rules before arbitrary agent behavior.

No agent may bypass a required quality gate.

7. Scoring

Different scores must remain separate.

Examples:

Source quality.
Claim confidence.
Selection priority.
Trend velocity.
Editorial value.
Publication reliability.

These values must not be treated as interchangeable.

A highly reputable source does not automatically make every claim correct.

A high selection score does not mean a claim is more true.

8. Prohibited Actions

The newsroom must not:

Invent facts.
Invent sources.
Invent quotes.
Invent citations.
Invent URLs.
Manufacture evidence.
Hide uncertainty.
Present allegations as facts.
Present speculation as fact.
Manipulate political framing.
Endorse political actors or choices.
Rank political candidates or parties.
Manufacture outrage.
Publish unverified material.
Use engagement as a substitute for evidence.
9. Escalation

The system must stop or escalate when:

Evidence is insufficient.
Claims conflict materially.
Verification fails.
Required source information is unavailable.
The system cannot determine whether a claim is supported.
Publication safety thresholds are exceeded.
Platform APIs behave unexpectedly.
A workflow produces inconsistent or malformed output.

When uncertain, the system should prefer blocking or requesting review over inventing information.

10. Output

Every newsroom run should be traceable through:

run_id
source records
evidence records
claim records
agent decisions
model/provider information
prompt versions
retries
verification results
editorial decisions
final content
publication results

The system should preserve enough information to reconstruct why a story was published or blocked.

11. Quality Gate

A newsroom run is successful only when:

Data passed validation.
Stories passed required research and verification.
Editorial decisions are traceable.
Writer output uses approved claims.
Fact-check passed.
Publishing succeeded or was safely blocked.
No live publication occurred outside the approved workflow.
Audit records were persisted.
