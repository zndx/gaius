"""NiFi Set-of-Mark dataset generation.

This module generates Magma-compatible training data from NiFi canvas
interactions, grounded by Metaflow flow discovery.

Usage:
    # Generate dataset (template-based instructions)
    uv run python -m gaius.datasets.nifi_som.generator

    # Generate with LLM-powered instructions (requires optillm)
    uv run python -m gaius.datasets.nifi_som.generator --use-llm

    # Generate with Metaflow database
    uv run python -m gaius.datasets.nifi_som.generator --use-database

    # ToM mode (Trace-of-Mark with trajectories)
    uv run python -m gaius.datasets.nifi_som.generator --mode tom

    # Dry run (no export)
    uv run python -m gaius.datasets.nifi_som.generator --dry-run
"""


def __getattr__(name: str):
    """Lazy imports to avoid circular import warnings when running as __main__."""
    if name == "NiFiSoMGenerator":
        from .generator import NiFiSoMGenerator
        return NiFiSoMGenerator
    elif name == "SoMAnnotator":
        from .annotator import SoMAnnotator
        return SoMAnnotator
    elif name == "MagmaExporter":
        from .exporter import MagmaExporter
        return MagmaExporter
    elif name == "validate_magma_format":
        from .exporter import validate_magma_format
        return validate_magma_format
    elif name == "LLMInstructionGenerator":
        from .llm_instructions import LLMInstructionGenerator
        return LLMInstructionGenerator
    elif name == "InstructionPipeline":
        from .llm_instructions import InstructionPipeline
        return InstructionPipeline
    elif name == "InstructionValidator":
        from .validation import InstructionValidator
        return InstructionValidator
    elif name == "InstructionQualityScorer":
        from .quality import InstructionQualityScorer
        return InstructionQualityScorer
    elif name in ("Mark", "Action", "DatasetExample", "Processor", "Connection", "Trajectory", "TraceExample"):
        from . import models
        return getattr(models, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Core classes
    "NiFiSoMGenerator",
    "SoMAnnotator",
    "MagmaExporter",
    "validate_magma_format",
    # LLM instruction generation
    "LLMInstructionGenerator",
    "InstructionPipeline",
    "InstructionValidator",
    "InstructionQualityScorer",
    # Data models
    "Mark",
    "Action",
    "DatasetExample",
    "Processor",
    "Connection",
    "Trajectory",
    "TraceExample",
]
