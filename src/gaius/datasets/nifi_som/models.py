"""Data models for NiFi SoM dataset generation.

Outputs Magma/LLaVA-compatible conversation format for training.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from PIL import Image


@dataclass
class Mark:
    """A Set-of-Mark annotation on an image element."""

    id: int
    label: str
    bbox: list[float]  # Normalized [x1, y1, x2, y2]
    type: str  # processor, connection, port, label

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON export."""
        return {
            "id": self.id,
            "label": self.label,
            "bbox": self.bbox,
            "type": self.type,
        }

    @property
    def center(self) -> tuple[float, float]:
        """Get center point of bounding box (normalized)."""
        return (
            (self.bbox[0] + self.bbox[2]) / 2,
            (self.bbox[1] + self.bbox[3]) / 2,
        )


@dataclass
class Action:
    """An action that can be performed on the NiFi canvas."""

    type: str  # click, drag, connect, configure
    coordinates: tuple[float, float]  # Normalized [0, 1]
    target_mark: Optional[int]  # SoM mark ID
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON export."""
        return {
            "type": self.type,
            "coordinates": list(self.coordinates),
            "target_mark": self.target_mark,
            "metadata": self.metadata,
        }

    def to_response_text(self) -> str:
        """Generate Magma-style response text for this action."""
        x, y = self.coordinates
        if self.target_mark:
            return f"[{self.target_mark}]"
        else:
            # Point format: [x, y] normalized
            return f"[{x:.3f}, {y:.3f}]"


@dataclass
class Processor:
    """A NiFi processor with position information."""

    id: str
    name: str
    type: str
    position: dict  # {"x": float, "y": float}
    config: dict = field(default_factory=dict)


@dataclass
class Connection:
    """A connection between NiFi processors."""

    id: str
    source_id: str
    destination_id: str
    source_name: str
    destination_name: str
    relationships: list[str] = field(default_factory=list)


@dataclass
class DatasetExample:
    """A single SoM example in the dataset."""

    id: str
    image: Image.Image
    marks: list[Mark]
    instruction: str
    actions: list[Action]
    flow_id: str
    metadata: dict = field(default_factory=dict)

    def to_magma_format(self, image_path: str) -> dict:
        """Convert to Magma/LLaVA conversation format.

        This is the primary export format for training Magma-8B or
        other LLaVA-family models on UI grounding tasks.

        Format:
        {
            "id": "unique_id",
            "image": "path/to/image.png",
            "conversations": [
                {"from": "human", "value": "<image>\n{instruction}"},
                {"from": "gpt", "value": "{action_output}"}
            ]
        }
        """
        # Build human instruction with image token
        human_value = f"<image>\n{self.instruction}"

        # Build GPT response - action output
        if self.actions:
            gpt_value = self.actions[0].to_response_text()
        else:
            gpt_value = "No action required."

        return {
            "id": self.id,
            "image": image_path,
            "conversations": [
                {"from": "human", "value": human_value},
                {"from": "gpt", "value": gpt_value},
            ],
            # Additional metadata for our use (not part of standard format)
            "_metadata": {
                "width": self.image.width,
                "height": self.image.height,
                "domain": "ui",
                "task_type": "ui_grounding",
                "flow_id": self.flow_id,
                "som_marks": [m.to_dict() for m in self.marks],
                "action": self.actions[0].to_dict() if self.actions else None,
                **self.metadata,
            },
        }

    # Keep legacy method for backward compatibility
    def to_annotation(self, image_path: Path, output_dir: Path) -> dict:
        """Legacy format - use to_magma_format() instead."""
        rel_path = str(image_path.relative_to(output_dir))
        return self.to_magma_format(rel_path)


@dataclass
class FlowStep:
    """A step from a Metaflow flow."""

    name: str
    next_steps: list[str] = field(default_factory=list)
    docstring: Optional[str] = None


@dataclass
class Trajectory:
    """A sequence of actions forming a trace (for ToM)."""

    steps: list[Action]
    description: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON export."""
        return {
            "steps": [s.to_dict() for s in self.steps],
            "description": self.description,
            "step_count": len(self.steps),
        }

    def to_response_text(self) -> str:
        """Generate Magma-style trajectory response.

        Format: sequence of mark IDs representing the action trace.
        Example: "[1] -> [3] -> [5]" or "1:3:5" for compact form.
        """
        mark_ids = [s.target_mark for s in self.steps if s.target_mark]
        if mark_ids:
            # Compact trace format used by Magma
            return ":".join(f"[{m}]" for m in mark_ids)
        else:
            # Fall back to coordinate sequence
            coords = [f"[{s.coordinates[0]:.3f}, {s.coordinates[1]:.3f}]"
                      for s in self.steps]
            return " -> ".join(coords)


@dataclass
class TraceExample:
    """A multi-frame example with trajectory overlay (Trace-of-Mark).

    Unlike SoM which has a single image, ToM captures a sequence of
    frames showing the progression of an interaction.
    """

    id: str
    frames: list[Image.Image]  # Sequence of screenshots
    marks: list[Mark]  # Element markers (same across frames)
    trajectory: Trajectory  # Action sequence with path
    instruction: str
    flow_id: str
    metadata: dict = field(default_factory=dict)

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def to_magma_format(self, frame_paths: list[str]) -> dict:
        """Convert to Magma/LLaVA conversation format for ToM.

        For multi-frame examples, we use the first frame as the primary
        image and include trajectory in the response.

        Format follows Magma's trace representation:
        "action_t:mark_t:trace_{t+1:t+l}"
        """
        # Human instruction with image token
        human_value = f"<image>\n{self.instruction}"

        # GPT response - trajectory trace
        gpt_value = self.trajectory.to_response_text()

        return {
            "id": self.id,
            "image": frame_paths[0] if frame_paths else "",
            "conversations": [
                {"from": "human", "value": human_value},
                {"from": "gpt", "value": gpt_value},
            ],
            # Additional metadata
            "_metadata": {
                "mode": "tom",
                "frame_count": self.frame_count,
                "frames": [
                    {
                        "frame_id": f"{self.id}_frame_{i:02d}",
                        "image_path": path,
                        "width": self.frames[i].width if i < len(self.frames) else 0,
                        "height": self.frames[i].height if i < len(self.frames) else 0,
                    }
                    for i, path in enumerate(frame_paths)
                ],
                "domain": "ui",
                "task_type": "ui_navigation",
                "flow_id": self.flow_id,
                "som_marks": [m.to_dict() for m in self.marks],
                "trajectory": self.trajectory.to_dict(),
                **self.metadata,
            },
        }

    # Keep legacy method for backward compatibility
    def to_annotation(self, frame_paths: list[str], output_dir: Path) -> dict:
        """Legacy format - use to_magma_format() instead."""
        return self.to_magma_format(frame_paths)
