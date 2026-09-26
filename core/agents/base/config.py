"""Formal configuration for every agent in the NewsRoom.

No hard-coded if/else trees. Every agent declares its own mission,
schemas, tools, capabilities, model preferences, and middleware.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    name: str
    mission: str
    system_prompt: str = ""

    input_schema_name: str
    output_schema_name: str

    tools: list[str] = Field(default_factory=list)

    required_capabilities: list[str] = Field(default_factory=list)
    preferred_models: list[str] = Field(default_factory=list)
    fallback_models: list[str] = Field(default_factory=list)

    middleware: list[str] = Field(default_factory=list)

    max_tool_calls: int = 10
    max_model_calls: int = 5

    is_deterministic: bool = False
    uses_llm: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


DEFAULT_AGENT_CONFIGS: dict[str, AgentConfig] = {
    "discovery": AgentConfig(
        name="discovery",
        mission="Identify promising stories from the ingested candidate pool.",
        input_schema_name="DiscoveryInput",
        output_schema_name="DiscoveryResult",
        tools=["get_story", "find_recent_stories"],
        required_capabilities=["basic_invocation", "structured_output"],
        middleware=["ModelFallback", "ModelCallLimit"],
        max_tool_calls=0,
        max_model_calls=2,
    ),
    "source_intelligence": AgentConfig(
        name="source_intelligence",
        mission="Assess source quality, independence, and attribution.",
        input_schema_name="SourceIntelligenceInput",
        output_schema_name="SourceIntelligenceResult",
        tools=["get_story_sources"],
        required_capabilities=["basic_invocation", "structured_output"],
        middleware=["ModelFallback", "ModelCallLimit"],
        max_tool_calls=3,
        max_model_calls=2,
    ),
    "research": AgentConfig(
        name="research",
        mission="Build an evidence package for a selected story.",
        input_schema_name="ResearchInput",
        output_schema_name="ResearchResult",
        tools=["search_web", "get_story", "get_story_sources", "save_research_result"],
        required_capabilities=[
            "basic_invocation", "structured_output",
            "tool_calling", "tool_plus_structure",
        ],
        middleware=[
            "Todo", "ToolCallLimit", "ToolRetry",
            "ModelFallback", "ModelCallLimit",
        ],
        max_tool_calls=12,
        max_model_calls=6,
    ),
    "selection": AgentConfig(
        name="selection",
        mission="Decide whether a story proceeds to verification.",
        input_schema_name="SelectionInput",
        output_schema_name="SelectionDecision",
        tools=["find_recent_stories", "find_duplicate_publication"],
        required_capabilities=["basic_invocation", "structured_output"],
        middleware=["ModelFallback", "ModelCallLimit"],
        max_tool_calls=3,
        max_model_calls=2,
    ),
    "verification": AgentConfig(
        name="verification",
        mission="Determine which claims can be responsibly stated.",
        input_schema_name="VerificationInput",
        output_schema_name="VerificationResult",
        tools=["get_story_claims", "get_story_evidence", "search_web"],
        required_capabilities=[
            "basic_invocation", "structured_output",
            "tool_calling", "tool_plus_structure",
        ],
        middleware=["ToolCallLimit", "ToolRetry", "ModelFallback", "ModelCallLimit"],
        max_tool_calls=8,
        max_model_calls=4,
    ),
    "editorial": AgentConfig(
        name="editorial",
        mission="Define the editorial brief from verified claims.",
        input_schema_name="EditorialInput",
        output_schema_name="EditorialDecision",
        tools=[],
        required_capabilities=["basic_invocation", "structured_output"],
        middleware=["ModelFallback", "ModelCallLimit"],
        max_tool_calls=0,
        max_model_calls=2,
    ),
    "tone": AgentConfig(
        name="tone",
        mission="Choose presentation tone appropriate to the story.",
        input_schema_name="ToneInput",
        output_schema_name="ToneDecision",
        tools=[],
        required_capabilities=["basic_invocation", "structured_output"],
        middleware=["ModelFallback", "ModelCallLimit"],
        max_tool_calls=0,
        max_model_calls=2,
    ),
    "writer": AgentConfig(
        name="writer",
        mission="Write the post using only approved claims.",
        input_schema_name="WriterInput",
        output_schema_name="WriterDraft",
        tools=[],
        required_capabilities=["basic_invocation", "structured_output"],
        middleware=["ModelFallback", "ModelCallLimit"],
        max_tool_calls=0,
        max_model_calls=3,
    ),
    "platform_adapter": AgentConfig(
        name="platform_adapter",
        mission="Adapt the draft to the target platform without altering facts.",
        input_schema_name="PlatformAdapterInput",
        output_schema_name="PlatformPost",
        tools=[],
        required_capabilities=["basic_invocation", "structured_output"],
        middleware=["ModelFallback", "ModelCallLimit"],
        max_tool_calls=0,
        max_model_calls=2,
    ),
    "validation": AgentConfig(
        name="validation",
        mission="Deterministic final QA.",
        input_schema_name="ValidationInput",
        output_schema_name="ValidationResult",
        tools=["find_duplicate_publication"],
        required_capabilities=[],
        middleware=[],
        max_tool_calls=2,
        max_model_calls=0,
        is_deterministic=True,
        uses_llm=False,
    ),
    "publisher": AgentConfig(
        name="publisher",
        mission="Publish the validated post to Threads.",
        input_schema_name="PublishInput",
        output_schema_name="PublishResult",
        tools=["find_duplicate_publication", "save_publication_result"],
        required_capabilities=[],
        middleware=[],
        max_tool_calls=2,
        max_model_calls=0,
        is_deterministic=True,
        uses_llm=False,
    ),
}
