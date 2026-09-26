"""Prompt composition — reuse existing prompt files, never duplicate them."""
from .loader import PromptLoader, compose_prompt

__all__ = ["PromptLoader", "compose_prompt"]
