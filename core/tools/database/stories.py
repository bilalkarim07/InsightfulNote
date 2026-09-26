"""Semantic story-level tools.

These functions are placeholders for the real Supabase-backed implementation.
They define the STABLE BOUNDARY that agents use — the agent layer never sees
the raw Supabase client and never runs arbitrary SQL.

Replace the placeholder bodies with real Supabase calls as the next step.
"""
from __future__ import annotations

from typing import Any, Optional


def get_story(story_id: str) -> Optional[dict[str, Any]]:
    """Fetch a single story by ID."""
    raise NotImplementedError("Wire to existing Supabase client.")


def find_recent_stories(limit: int = 20, topic: Optional[str] = None) -> list[dict[str, Any]]:
    """Find recent stories, optionally filtered by topic."""
    raise NotImplementedError("Wire to existing Supabase client.")


def get_story_sources(story_id: str) -> list[dict[str, Any]]:
    """Return all sources attached to a story."""
    raise NotImplementedError("Wire to existing Supabase client.")


def get_story_claims(story_id: str) -> list[dict[str, Any]]:
    """Return all claims attached to a story."""
    raise NotImplementedError("Wire to existing Supabase client.")


def get_story_evidence(story_id: str) -> list[dict[str, Any]]:
    """Return all evidence attached to a story."""
    raise NotImplementedError("Wire to existing Supabase client.")


def find_duplicate_publication(story_id: str, platform: str = "threads") -> Optional[dict[str, Any]]:
    """Return an existing publication record if this story was already published."""
    raise NotImplementedError("Wire to existing Supabase client.")


def save_research_result(run_id: str, payload: dict[str, Any]) -> str:
    raise NotImplementedError("Wire to existing Supabase client.")


def save_verification_result(run_id: str, payload: dict[str, Any]) -> str:
    raise NotImplementedError("Wire to existing Supabase client.")


def save_editorial_decision(run_id: str, payload: dict[str, Any]) -> str:
    raise NotImplementedError("Wire to existing Supabase client.")


def save_publication_result(run_id: str, payload: dict[str, Any]) -> str:
    raise NotImplementedError("Wire to existing Supabase client.")
