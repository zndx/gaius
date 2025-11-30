"""Situational Awareness module for Gaius.

Provides startup reports, activity summaries, and time-horizon based
awareness of the knowledge base state.
"""

from .situational import (
    SituationalReport,
    SituationalAwareness,
    get_situational_awareness,
    generate_startup_report,
)

__all__ = [
    "SituationalReport",
    "SituationalAwareness",
    "get_situational_awareness",
    "generate_startup_report",
]
