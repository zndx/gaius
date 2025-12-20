"""UOM - UI Observation Model for RASE.

The UI Observation Model represents visual observations of the system
under test, following the Magma SoM/ToM (Set-of-Mark/Trace-of-Mark) pattern.

Package structure mirrors SysML v2:
    package RASE_NiFi::UOM {
        item def Mark { ... }
        item def ScreenshotWithSoM { ... }
        item def TraceOfMarks { ... }
    }

Key concepts:
- Mark: A labeled bounding box on a screenshot (SoM element)
- ScreenshotWithSoM: A screenshot with overlaid marks
- TraceOfMarks: A sequence of screenshots showing action progression (ToM)
- UIAction: An action performed on a mark (click, type, drag, etc.)

The UOM provides the "perceptual surface" that agents learn to act on,
while SSM provides the "ground truth" for verification.

Magma SoM/ToM reference:
    SoM: Overlay numeric marks on UI elements for grounding
    ToM: Sequence marks in temporal order for action learning
"""

from .marks import (
    PixelCoord,
    BoundingBox,
    UIRole,
    Mark,
    ScreenshotWithSoM,
    SoMGenerator,
)
from .traces import (
    UIActionType,
    UIAction,
    ActionFrame,
    TraceOfMarks,
    TraceRecorder,
)

__all__ = [
    # Marks
    "PixelCoord",
    "BoundingBox",
    "UIRole",
    "Mark",
    "ScreenshotWithSoM",
    "SoMGenerator",
    # Traces
    "UIActionType",
    "UIAction",
    "ActionFrame",
    "TraceOfMarks",
    "TraceRecorder",
]
