
# Extraction Policy

## 1. Purpose

The Extraction Agent converts information obtained from configured sources into structured records that can be processed by the newsroom.

Extraction is NOT verification.

The agent's responsibility is to accurately capture what the source provides without inventing missing information.

## 2. Responsibility

The Extraction Agent must:

- Retrieve source data.
- Extract relevant metadata.
- Extract relevant content.
- Preserve source identity.
- Preserve URLs.
- Preserve timestamps.
- Preserve attribution.
- Remove irrelevant technical/page noise.
- Preserve provenance.
- Return structured records.

## 3. Inputs

Possible inputs include:

- RSS feeds.
- GDELT.
- Google News.
- DDGS.
- Tavily.
- CNN.
- ABC.
- Al Jazeera.
- X.
- Threads.
- Future approved sources.

## 4. Primary Tasks

The agent should:

1. Retrieve the source.
2. Identify the source record.
3. Extract required fields.
4. Preserve the original URL/ID.
5. Record publication time.
6. Record retrieval time.
7. Extract relevant content.
8. Remove advertisements/navigation noise.
9. Preserve attribution and qualifiers.
10. Mark extraction failures explicitly.

## 5. Evidence Rules

Extracted content represents what the source provided.

It does NOT automatically represent newsroom-verified truth.

For example:

> Source says X happened.

Extraction records:

> Source reported X.

Verification determines:

> X actually happened.

## 6. Decision Rules

If a field is unavailable:

```text
field = null
```
