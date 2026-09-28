
# Discovery Policy

## Purpose

The deterministic ETL identifies potentially important news events from approved structured sources and creates normalized candidate stories. The graph's Discovery stage only interprets and validates a candidate already selected from the database.

## Responsibility

The graph's candidate interpreter is responsible for interpreting a loaded candidate, not searching external news or proving that claims are true.

## Primary Sources

Approved discovery sources may include:

- GDELT
- Google News RSS
- validated RSS feeds
- DDGS
- Tavily, when enabled
- X
- Threads

The source registry determines which sources are active.

## Discovery Goals

Prioritize events based on:

1. Global relevance
2. Recency
3. Source diversity
4. Trend velocity
5. Potential public significance
6. Availability of verifiable evidence

## Discovery Rules

The agent should search broadly enough to avoid depending on a single publisher.

Multiple articles describing the same event should become one candidate cluster rather than multiple independent stories.

A search result is a lead, not automatically verified news.

## Prohibited Actions

The Discovery Agent must not:

- declare a story verified;
- invent missing details;
- treat social reactions as facts;
- write final publication copy;
- infer importance solely from engagement;
- manufacture urgency.

## Output

Each candidate should contain:

- candidate_id
- title
- source
- URL
- discovered_at
- published_at
- preliminary topic
- preliminary relevance
- source type
- extraction requirement
- initial confidence

## Quality Gate

A candidate proceeds only when sufficient metadata exists to identify the underlying source or event.
