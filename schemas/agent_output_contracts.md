# Agent Output Contracts

Implement these as Pydantic models under `core/schemas/`.

## ResearchResult
story_id
story_summary
claims[]
evidence[]
source_assessment[]
conflicts[]
missing_information[]
recommended_status

## EditorialDecision
story_id
approved_claim_ids[]
blocked_claim_ids[]
framing_notes
tone
platform_requirements
publication_decision

## PlatformPost
platform
post_text
structure
cta
source_claim_ids[]
validation_notes

## QAResult
passed
blocking_errors[]
warnings[]
checked_claim_ids[]
prompt_version
model_provider
