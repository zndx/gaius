"""Knowledge Base utilities for Gaius.

This package provides tools for working with the KB structure,
including Obsidian .base file validation and generation.
"""

from .base_validator import (
    ValidationResult,
    validate_base,
    VALID_OPERATORS,
    VALID_VIEW_TYPES,
)

__all__ = [
    "ValidationResult",
    "validate_base",
    "VALID_OPERATORS",
    "VALID_VIEW_TYPES",
]
