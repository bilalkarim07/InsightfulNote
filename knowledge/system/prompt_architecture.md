# Prompt Architecture

Layer 0 — immutable global policy.
Layer 1 — role system prompt.
Layer 2 — task/runtime state.
Layer 3 — authorized tool results.
Layer 4 — Pydantic output contract.
Layer 5 — deterministic validators.

Prompt versions use identifiers such as `researcher.v1.0`.

LLM output is never trusted merely because it is structured. Deterministic post-processing must validate:
- required fields
- evidence references
- platform constraints
- quote provenance
- unsupported claims
- duplicate/repetition checks
- CTA policy

Agents may transform approved evidence; they may not manufacture evidence.
