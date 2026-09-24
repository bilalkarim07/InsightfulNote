# Validation Policy

## 1. Purpose

Validation ensures that extracted and processed data is structurally usable, internally consistent, and suitable for downstream processing.

Validation checks data integrity.

Validation does not establish whether a claim is true.

---

## 2. Responsibility

The Validation system is responsible for:

- Checking required fields.
- Checking data types.
- Checking URL structure.
- Checking timestamps.
- Checking source identity.
- Checking extraction completeness.
- Detecting malformed records.
- Detecting duplicate records where applicable.
- Preventing invalid data from entering downstream agents.

---

## 3. Inputs

Validation receives:

- Raw extraction results.
- Normalized source records.
- Article metadata.
- Extracted text.
- Source identifiers.
- URLs.
- Timestamps.
- Content hashes.
- Adapter metadata.

---

## 4. Primary Tasks

Validation should:

1. Check schema compliance.
2. Check required fields.
3. Validate URLs.
4. Validate timestamps.
5. Validate source identifiers.
6. Check text availability.
7. Detect malformed content.
8. Check extraction status.
9. Check duplicate identifiers.
10. Return a deterministic validation result.

---

## 5. Source / Evidence Rules

Validation may confirm that:

- A URL exists.
- A source is recognized.
- Content was successfully extracted.
- Required metadata exists.
- A timestamp is parseable.
- A record follows the expected schema.

Validation must not conclude:

> This event definitely happened.

That is a Verification responsibility.

---

## 6. Decision Rules

### Required Data

A source record should normally contain:

- `source_id`
- `source_type`
- `publisher`
- `url`
- `title`
- `published_at`
- `retrieved_at`
- `content`
- `content_hash`

Additional fields may be required by individual adapters.

### URL Rule

Invalid or missing URLs should cause the record to fail validation when the source requires a URL.

### Timestamp Rule

Malformed timestamps must be rejected or normalized before downstream processing.

### Content Rule

Records containing no usable content should not enter research or verification.

### Duplicate Rule

Records with identical canonical identifiers or content hashes should be handled by deduplication before creating independent story candidates.

---

## 7. Scoring

Validation should primarily use deterministic checks rather than subjective scoring.

Possible status:

- `VALID`
- `INVALID`
- `PARTIAL`

A validation score may be used internally for diagnostics, but should not replace required-field rules.

---

## 8. Prohibited Actions

Validation must not:

- Determine truth.
- Determine story importance.
- Select stories.
- Rewrite factual content.
- Guess missing values.
- Invent metadata.
- Treat malformed data as valid.
- Use popularity as evidence.
- Replace verification.

---

## 9. Escalation

Escalate or reject when:

- Required fields are missing.
- Content extraction failed.
- URL is malformed.
- Timestamp is invalid.
- Source identity is ambiguous.
- Content appears truncated beyond usable limits.
- The adapter violates its schema.
- Data cannot be normalized deterministically.

---

## 10. Output

Validation should return:

- `record_id`
- `validation_status`
- `failed_checks`
- `warnings`
- `normalized_fields`
- `validation_timestamp`

---

## 11. Quality Gate

A record passes validation when:

- Required fields exist.
- Data types are correct.
- URLs are usable where required.
- Timestamps are valid.
- Content is usable.
- Source metadata is recognized.
- No blocking schema errors exist.

Validation success does not imply factual verification.
