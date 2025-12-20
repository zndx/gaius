"""UOM Mark definitions for Set-of-Mark (SoM) annotations.

Provides data structures for representing UI elements as marked regions
on screenshots, following the Magma SoM approach.

Maps to SysML v2:
    item def Mark {
        attribute markId : Integer;
        attribute bbox : BoundingBox;
        attribute uiRole : String;
        ref part mapsTo : Processor[0..1];
    }

    item def ScreenshotWithSoM {
        attribute uri : String;
        part marks : Mark[*];
    }

The SoM pattern:
1. Capture a screenshot of the UI
2. Detect interactable elements (via accessibility tree, DOM, or CV)
3. Overlay numbered marks on each element
4. Train agents to reference elements by mark number

This enables precise grounding between language and UI actions.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from gaius.rase.traceability import TraceableId, IdScheme


class PixelCoord(BaseModel):
    """A point in pixel coordinates.

    Origin is top-left corner of the image.
    """

    x: int
    y: int

    model_config = {"frozen": True}

    def __add__(self, other: "PixelCoord") -> "PixelCoord":
        return PixelCoord(x=self.x + other.x, y=self.y + other.y)

    def __sub__(self, other: "PixelCoord") -> "PixelCoord":
        return PixelCoord(x=self.x - other.x, y=self.y - other.y)

    def distance_to(self, other: "PixelCoord") -> float:
        """Euclidean distance to another point."""
        import math
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)


class BoundingBox(BaseModel):
    """A rectangular region in pixel coordinates.

    Represented as top-left and bottom-right corners.
    """

    top_left: PixelCoord
    bottom_right: PixelCoord

    model_config = {"frozen": True}

    @classmethod
    def from_xywh(cls, x: int, y: int, width: int, height: int) -> "BoundingBox":
        """Create from x, y, width, height format."""
        return cls(
            top_left=PixelCoord(x=x, y=y),
            bottom_right=PixelCoord(x=x + width, y=y + height),
        )

    @classmethod
    def from_center(cls, center: PixelCoord, width: int, height: int) -> "BoundingBox":
        """Create from center point and dimensions."""
        hw, hh = width // 2, height // 2
        return cls(
            top_left=PixelCoord(x=center.x - hw, y=center.y - hh),
            bottom_right=PixelCoord(x=center.x + hw, y=center.y + hh),
        )

    @property
    def width(self) -> int:
        return self.bottom_right.x - self.top_left.x

    @property
    def height(self) -> int:
        return self.bottom_right.y - self.top_left.y

    @property
    def center(self) -> PixelCoord:
        """Center point of the bounding box."""
        return PixelCoord(
            x=self.top_left.x + self.width // 2,
            y=self.top_left.y + self.height // 2,
        )

    @property
    def area(self) -> int:
        return self.width * self.height

    def contains(self, point: PixelCoord) -> bool:
        """Check if point is inside the bounding box."""
        return (
            self.top_left.x <= point.x <= self.bottom_right.x and
            self.top_left.y <= point.y <= self.bottom_right.y
        )

    def overlaps(self, other: "BoundingBox") -> bool:
        """Check if this box overlaps with another."""
        return not (
            self.bottom_right.x < other.top_left.x or
            other.bottom_right.x < self.top_left.x or
            self.bottom_right.y < other.top_left.y or
            other.bottom_right.y < self.top_left.y
        )

    def intersection(self, other: "BoundingBox") -> "BoundingBox | None":
        """Compute intersection with another box."""
        if not self.overlaps(other):
            return None
        return BoundingBox(
            top_left=PixelCoord(
                x=max(self.top_left.x, other.top_left.x),
                y=max(self.top_left.y, other.top_left.y),
            ),
            bottom_right=PixelCoord(
                x=min(self.bottom_right.x, other.bottom_right.x),
                y=min(self.bottom_right.y, other.bottom_right.y),
            ),
        )

    def iou(self, other: "BoundingBox") -> float:
        """Intersection over Union with another box."""
        inter = self.intersection(other)
        if inter is None:
            return 0.0
        union_area = self.area + other.area - inter.area
        return inter.area / union_area if union_area > 0 else 0.0


class UIRole(str, Enum):
    """Semantic role of a UI element.

    Maps UI elements to their functional purpose for better grounding.
    """
    # NiFi-specific
    PROCESSOR = "processor"
    PROCESS_GROUP = "process_group"
    CONNECTION = "connection"
    PORT = "port"
    CONTROLLER_SERVICE = "controller_service"
    LABEL = "label"

    # Generic UI elements
    BUTTON = "button"
    INPUT = "input"
    DROPDOWN = "dropdown"
    MENU = "menu"
    MENU_ITEM = "menu_item"
    TOOLBAR = "toolbar"
    TOOLBAR_BUTTON = "toolbar_button"
    CANVAS = "canvas"
    DIALOG = "dialog"
    TAB = "tab"
    PANEL = "panel"

    # Unknown/other
    UNKNOWN = "unknown"


class Mark(BaseModel):
    """A single SoM mark on a screenshot.

    A mark is a labeled bounding box that identifies an interactable
    UI element. The mark_id is displayed as an overlay for agent reference.

    Attributes:
        mark_id: The numeric ID displayed on the overlay (1, 2, 3, ...)
        bbox: Bounding box of the element
        ui_role: Semantic role of the element
        label: Text label (from OCR, accessibility, or DOM)
        confidence: Detection confidence score (0-1)
        maps_to: Optional SSM reference for grounding

    Example:
        Mark(
            mark_id=1,
            bbox=BoundingBox.from_xywh(100, 200, 150, 50),
            ui_role=UIRole.PROCESSOR,
            label="GetFile",
            maps_to=TraceableId.from_nifi("pg1", processor_id="proc1"),
        )
    """

    mark_id: int
    bbox: BoundingBox
    ui_role: UIRole = UIRole.UNKNOWN
    label: str = ""
    confidence: float = 1.0

    # Grounding into SSM (optional)
    maps_to: TraceableId | None = None

    # Additional metadata
    attributes: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

    @property
    def display_label(self) -> str:
        """Label for display (mark_id + label if available)."""
        if self.label:
            return f"[{self.mark_id}] {self.label}"
        return f"[{self.mark_id}]"


class ScreenshotWithSoM(BaseModel):
    """Screenshot with Set-of-Mark annotations.

    This is the primary UOM artifact: a captured screenshot with marks
    overlaid on interactable elements.

    Attributes:
        id: Traceable identifier
        uri: Path to the screenshot image
        timestamp: When the screenshot was captured
        marks: List of marks on the screenshot
        viewport_size: Size of the captured viewport
        ssm_state_id: Link to SSM state at capture time

    Example:
        som = ScreenshotWithSoM(
            uri="file:///tmp/screenshot_001.png",
            marks=[
                Mark(mark_id=1, ...),
                Mark(mark_id=2, ...),
            ],
        )
    """

    id: TraceableId = Field(
        default_factory=lambda: TraceableId.generate(IdScheme.SOM, "screenshot")
    )
    uri: str
    timestamp: datetime = Field(default_factory=datetime.now)
    marks: list[Mark] = Field(default_factory=list)

    # Image metadata
    viewport_width: int = 0
    viewport_height: int = 0

    # SSM link (optional)
    ssm_state_id: TraceableId | None = None

    model_config = {"frozen": True}

    def get_mark(self, mark_id: int) -> Mark | None:
        """Find mark by ID."""
        for mark in self.marks:
            if mark.mark_id == mark_id:
                return mark
        return None

    def get_mark_at(self, point: PixelCoord) -> Mark | None:
        """Find mark containing the given point."""
        for mark in self.marks:
            if mark.bbox.contains(point):
                return mark
        return None

    def marks_by_role(self, role: UIRole) -> list[Mark]:
        """Get all marks with a specific role."""
        return [m for m in self.marks if m.ui_role == role]

    def to_training_format(self) -> dict[str, Any]:
        """Convert to Magma-style training format.

        Returns a dict suitable for training data:
        - image_path: URI to the screenshot
        - marks: List of mark annotations
        - ssm_grounding: Mapping from mark_id to SSM element
        """
        grounding = {}
        for mark in self.marks:
            if mark.maps_to:
                grounding[mark.mark_id] = mark.maps_to.uri

        return {
            "image_path": self.uri,
            "marks": [
                {
                    "id": m.mark_id,
                    "bbox": [
                        m.bbox.top_left.x,
                        m.bbox.top_left.y,
                        m.bbox.bottom_right.x,
                        m.bbox.bottom_right.y,
                    ],
                    "role": m.ui_role.value,
                    "label": m.label,
                }
                for m in self.marks
            ],
            "ssm_grounding": grounding,
        }


class SoMGenerator:
    """Generator for SoM annotations on screenshots.

    Provides methods for detecting UI elements and creating marks.
    This is a base class - subclasses implement specific detection strategies.
    """

    def __init__(self, next_mark_id: int = 1):
        self.next_mark_id = next_mark_id

    def _allocate_id(self) -> int:
        """Get next mark ID."""
        mid = self.next_mark_id
        self.next_mark_id += 1
        return mid

    def create_mark(
        self,
        bbox: BoundingBox,
        ui_role: UIRole = UIRole.UNKNOWN,
        label: str = "",
        maps_to: TraceableId | None = None,
        confidence: float = 1.0,
    ) -> Mark:
        """Create a new mark with auto-assigned ID."""
        return Mark(
            mark_id=self._allocate_id(),
            bbox=bbox,
            ui_role=ui_role,
            label=label,
            maps_to=maps_to,
            confidence=confidence,
        )

    async def generate_marks(
        self,
        screenshot_path: str,
    ) -> list[Mark]:
        """Generate marks for a screenshot.

        Override in subclasses to implement detection logic:
        - AccessibilitySoMGenerator: Uses accessibility tree
        - DOMSoMGenerator: Uses browser DOM
        - CVSoMGenerator: Uses computer vision
        """
        # Base implementation returns empty list
        return []

    async def annotate_screenshot(
        self,
        screenshot_path: str,
        ssm_state_id: TraceableId | None = None,
    ) -> ScreenshotWithSoM:
        """Generate marks and create annotated screenshot."""
        marks = await self.generate_marks(screenshot_path)

        return ScreenshotWithSoM(
            uri=screenshot_path,
            marks=marks,
            ssm_state_id=ssm_state_id,
        )


__all__ = [
    "PixelCoord",
    "BoundingBox",
    "UIRole",
    "Mark",
    "ScreenshotWithSoM",
    "SoMGenerator",
]
