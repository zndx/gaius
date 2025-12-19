"""Prompt templates for LLM-powered instruction generation."""

from .generation import GENERATION_PROMPTS, get_generation_prompt
from .validation import ALIGNMENT_PROMPT, get_alignment_prompt
from .quality import QUALITY_RUBRIC_PROMPT, get_quality_prompt
from .rubric import (
    RUBRIC_SYSTEM_PROMPT,
    build_rubric_prompt,
    parse_rubric_response,
    compute_weighted_reward,
    extract_errors,
)

__all__ = [
    "GENERATION_PROMPTS",
    "get_generation_prompt",
    "ALIGNMENT_PROMPT",
    "get_alignment_prompt",
    "QUALITY_RUBRIC_PROMPT",
    "get_quality_prompt",
    "RUBRIC_SYSTEM_PROMPT",
    "build_rubric_prompt",
    "parse_rubric_response",
    "compute_weighted_reward",
    "extract_errors",
]
