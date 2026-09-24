
---
# `knowledge/publishing/publisher_policy.md`

```md
# Publisher Policy

## 1. Purpose

The Publisher converts approved final content into platform-specific API requests and publishes it through authorized platform interfaces.

The Publisher is intentionally "dumb."

It should execute publication instructions rather than make editorial or factual decisions.
---


## 1. Purpose

The Publisher converts approved final content into platform-specific API requests and publishes it through authorized platform interfaces.

The Publisher is intentionally "dumb."

It should execute publication instructions rather than make editorial or factual decisions.

## 2. Responsibility

The Publisher is responsible for:

- Platform formatting.
- API authentication.
- API requests.
- Rate-limit handling.
- Retries.
- Duplicate protection.
- Publication IDs.
- Publication timestamps.
- Error handling.
- Publication logging.
- Recovery procedures.

The Publisher must not decide what is true or what should be published.

---

## 3. Inputs

The Publisher receives:

- Fact-checked final content.
- Platform-specific content.
- Platform configuration.
- Authentication credentials.
- Publication schedule.
- Media attachments where applicable.
- Story ID.
- Run ID.
- Idempotency key.

---

## 4. Primary Tasks

The Publisher should:

1. Validate the publication payload.
2. Confirm platform configuration.
3. Check duplicate protection.
4. Authenticate with the platform.
5. Submit the API request.
6. Handle rate limits.
7. Retry according to policy.
8. Record the publication result.
9. Store platform publication identifiers.
10. Report failures.

---

## 5. Source / Evidence Rules

The Publisher must not alter factual content.

The final publication payload must originate from approved and fact-checked content.

If a source link is included:

- It must correspond to the story.
- It must be valid.
- It must not be replaced with an unrelated URL.

The Publisher must not add sources merely to make content appear authoritative.

---

## 6. Decision Rules

### Pre-Publication Gate

Publication should proceed only when:

- Fact-check status is approved.
- Required editorial status is approved.
- Platform formatting is valid.
- Required fields are present.
- Duplicate protection passes.
- Publication schedule allows execution.

### Retry Rule

Transient API failures may be retried using configured retry limits and backoff.

Permanent failures should not be retried indefinitely.

### Duplicate Rule

A story/platform combination should have an idempotency mechanism preventing accidental duplicate publication.

### Emergency Safety Rule

If publication errors exceed the configured threshold during a 24-hour cycle:

1. Disable scheduled publication.
2. Switch the workflow to dry-run mode.
3. Open a critical issue.
4. Preserve run logs.
5. Require investigation before re-enabling publication.

The execution plan specifies 10% publication errors as the initial safeguard threshold; keep this configurable.

---

## 7. Scoring

The Publisher should avoid editorial scoring.

Operational metrics may include:

- Publication success rate.
- API latency.
- Retry count.
- Rate-limit events.
- Failure rate.
- Duplicate prevention events.
- Platform response status.

These metrics measure system reliability, not content quality.

---

## 8. Prohibited Actions

The Publisher must not:

- Rewrite content.
- Add facts.
- Remove caveats.
- Change attribution.
- Change political framing.
- Select stories.
- Decide whether evidence is sufficient.
- Override fact-check status.
- Publish blocked content.
- Bypass authentication.
- Circumvent platform rate limits.
- Publish duplicate content unintentionally.

---

## 9. Escalation

Escalate when:

- Authentication fails.
- API permissions are insufficient.
- Publication repeatedly fails.
- Rate limits are exceeded.
- Duplicate state is uncertain.
- Platform response is ambiguous.
- Payload validation fails.
- Fact-check status is missing.
- Publication errors exceed the configured safety threshold.

---

## 10. Output

The Publisher should return:

- `story_id`
- `platform`
- `publication_status`
- `publication_id`
- `published_at`
- `api_status`
- `retry_count`
- `error_code`
- `error_message`
- `idempotency_key`

Possible statuses:

- `PUBLISHED`
- `SKIPPED`
- `FAILED`
- `BLOCKED`
- `RETRYING`

---

## 11. Quality Gate

Publication passes only when:

- Content has passed fact-check.
- Platform payload is valid.
- Duplicate protection passes.
- Authentication succeeds.
- API request succeeds.
- Publication ID is recorded.
- Publication timestamp is recorded.
- Result is persisted for auditability.

The Publisher must never become an editorial decision-maker.
