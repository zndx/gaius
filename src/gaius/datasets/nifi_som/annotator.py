"""Set-of-Mark and Trace-of-Mark annotation overlays for NiFi screenshots."""

import math
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

from .models import Mark, Processor, Action, Trajectory


class SoMAnnotator:
    """Overlay Set-of-Mark annotations on NiFi screenshots."""

    # Default marker colors and styling
    MARKER_BG_COLOR = (255, 0, 0)  # Red background
    MARKER_TEXT_COLOR = (255, 255, 255)  # White text
    MARKER_BORDER_COLOR = (128, 0, 0)  # Dark red border
    MARKER_RADIUS = 12
    MARKER_FONT_SIZE = 14

    def __init__(
        self,
        marker_radius: int = 12,
        font_size: int = 14,
        bg_color: tuple = (255, 0, 0),
        text_color: tuple = (255, 255, 255),
    ):
        self.marker_radius = marker_radius
        self.font_size = font_size
        self.bg_color = bg_color
        self.text_color = text_color
        self._font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None

    def _get_font(self) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        """Get or create the annotation font."""
        if self._font is None:
            try:
                # Try to load a nice font
                self._font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    self.font_size,
                )
            except (OSError, IOError):
                try:
                    # Fallback to another common font
                    self._font = ImageFont.truetype(
                        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
                        self.font_size,
                    )
                except (OSError, IOError):
                    # Use default font
                    self._font = ImageFont.load_default()
        return self._font

    def annotate(
        self,
        image: Image.Image,
        processors: list[Processor],
        offset: tuple[float, float] = (0, 0),
    ) -> tuple[Image.Image, list[Mark]]:
        """Add numbered markers to processors on the image.

        Args:
            image: The source image to annotate
            processors: List of processors with position information
            offset: Offset to apply to processor positions (for canvas scrolling)

        Returns:
            Tuple of (annotated image, list of marks)
        """
        # Create a copy to avoid modifying original
        annotated = image.copy()
        draw = ImageDraw.Draw(annotated)
        font = self._get_font()
        marks = []

        for i, proc in enumerate(processors, 1):
            # Get processor center position
            # NiFi positions are absolute canvas coordinates
            x = proc.position.get("x", 0) + offset[0]
            y = proc.position.get("y", 0) + offset[1]

            # Adjust for processor size (approximate center)
            # NiFi processors are roughly 150x50 pixels
            proc_width = 150
            proc_height = 50
            center_x = x + proc_width / 2
            center_y = y + proc_height / 2

            # Draw the marker circle
            self._draw_marker(draw, center_x, center_y, i, font)

            # Calculate normalized bounding box
            # Normalize coordinates to [0, 1]
            x1 = x / image.width
            y1 = y / image.height
            x2 = (x + proc_width) / image.width
            y2 = (y + proc_height) / image.height

            marks.append(
                Mark(
                    id=i,
                    label=proc.name,
                    bbox=[x1, y1, x2, y2],
                    type="processor",
                )
            )

        return annotated, marks

    def _draw_marker(
        self,
        draw: ImageDraw.ImageDraw,
        x: float,
        y: float,
        number: int,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    ):
        """Draw a numbered marker at the specified position."""
        r = self.marker_radius

        # Draw filled circle with border
        draw.ellipse(
            [x - r, y - r, x + r, y + r],
            fill=self.bg_color,
            outline=self.MARKER_BORDER_COLOR,
            width=2,
        )

        # Draw number centered in circle
        text = str(number)
        bbox = font.getbbox(text)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        text_x = x - text_width / 2
        text_y = y - text_height / 2 - 2  # Small adjustment for visual centering

        draw.text((text_x, text_y), text, fill=self.text_color, font=font)

    def annotate_with_connections(
        self,
        image: Image.Image,
        processors: list[Processor],
        connections: list,
        offset: tuple[float, float] = (0, 0),
    ) -> tuple[Image.Image, list[Mark]]:
        """Annotate image with both processors and connection markers.

        Args:
            image: The source image
            processors: List of processors
            connections: List of connections
            offset: Canvas offset

        Returns:
            Tuple of (annotated image, list of marks)
        """
        # First annotate processors
        annotated, marks = self.annotate(image, processors, offset)

        # TODO: Add connection annotations if needed
        # For now, we focus on processors only

        return annotated, marks


class TrajectoryAnnotator:
    """Overlay trajectory paths for Trace-of-Mark annotations."""

    # Arrow and path styling
    PATH_COLOR = (0, 120, 255)  # Blue path
    PATH_WIDTH = 3
    ARROW_COLOR = (0, 80, 200)  # Darker blue for arrows
    ARROW_SIZE = 12
    STEP_MARKER_RADIUS = 16
    STEP_BG_COLOR = (0, 120, 255)  # Blue background
    STEP_TEXT_COLOR = (255, 255, 255)  # White text
    STEP_FONT_SIZE = 12

    def __init__(
        self,
        path_color: tuple = (0, 120, 255),
        path_width: int = 3,
        show_arrows: bool = True,
    ):
        self.path_color = path_color
        self.path_width = path_width
        self.show_arrows = show_arrows
        self._font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None

    def _get_font(self) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        """Get or create the annotation font."""
        if self._font is None:
            try:
                self._font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    self.STEP_FONT_SIZE,
                )
            except (OSError, IOError):
                try:
                    self._font = ImageFont.truetype(
                        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
                        self.STEP_FONT_SIZE,
                    )
                except (OSError, IOError):
                    self._font = ImageFont.load_default()
        return self._font

    def annotate_trajectory(
        self,
        image: Image.Image,
        trajectory: Trajectory,
        current_step: int = -1,
    ) -> Image.Image:
        """Draw trajectory path on image.

        Args:
            image: The source image to annotate
            trajectory: The trajectory with action steps
            current_step: Highlight steps up to this index (-1 = all)

        Returns:
            Annotated image with trajectory overlay
        """
        annotated = image.copy()
        draw = ImageDraw.Draw(annotated)
        font = self._get_font()

        steps = trajectory.steps
        if not steps:
            return annotated

        # Determine which steps to show
        max_step = len(steps) if current_step < 0 else min(current_step + 1, len(steps))

        # Convert normalized coordinates to pixel coordinates
        points = []
        for action in steps[:max_step]:
            x = action.coordinates[0] * image.width
            y = action.coordinates[1] * image.height
            points.append((x, y))

        # Draw path lines between consecutive points
        for i in range(len(points) - 1):
            self._draw_path_segment(
                draw, points[i], points[i + 1], i + 1, len(points) - 1
            )

        # Draw step markers at each point
        for i, point in enumerate(points):
            self._draw_step_marker(draw, point[0], point[1], i + 1, font)

        return annotated

    def _draw_path_segment(
        self,
        draw: ImageDraw.ImageDraw,
        start: tuple[float, float],
        end: tuple[float, float],
        segment_num: int,
        total_segments: int,
    ):
        """Draw a path segment with optional arrow."""
        # Draw the line
        draw.line([start, end], fill=self.path_color, width=self.path_width)

        # Draw arrow at the end if enabled
        if self.show_arrows:
            self._draw_arrow(draw, start, end)

    def _draw_arrow(
        self,
        draw: ImageDraw.ImageDraw,
        start: tuple[float, float],
        end: tuple[float, float],
    ):
        """Draw an arrowhead at the end of a line segment."""
        # Calculate angle of line
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        angle = math.atan2(dy, dx)

        # Arrow point is slightly before the end (to not overlap with marker)
        arrow_tip_x = end[0] - math.cos(angle) * self.STEP_MARKER_RADIUS
        arrow_tip_y = end[1] - math.sin(angle) * self.STEP_MARKER_RADIUS

        # Calculate arrowhead points
        arrow_angle = math.pi / 6  # 30 degrees
        arrow_len = self.ARROW_SIZE

        left_x = arrow_tip_x - arrow_len * math.cos(angle - arrow_angle)
        left_y = arrow_tip_y - arrow_len * math.sin(angle - arrow_angle)
        right_x = arrow_tip_x - arrow_len * math.cos(angle + arrow_angle)
        right_y = arrow_tip_y - arrow_len * math.sin(angle + arrow_angle)

        # Draw filled triangle
        draw.polygon(
            [(arrow_tip_x, arrow_tip_y), (left_x, left_y), (right_x, right_y)],
            fill=self.ARROW_COLOR,
        )

    def _draw_step_marker(
        self,
        draw: ImageDraw.ImageDraw,
        x: float,
        y: float,
        step_num: int,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    ):
        """Draw a numbered step marker (circled number)."""
        r = self.STEP_MARKER_RADIUS

        # Draw filled circle
        draw.ellipse(
            [x - r, y - r, x + r, y + r],
            fill=self.STEP_BG_COLOR,
            outline=(0, 60, 150),
            width=2,
        )

        # Draw circled number (①, ②, etc.) or plain number
        # Use plain numbers for simplicity
        text = str(step_num)
        bbox = font.getbbox(text)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        text_x = x - text_width / 2
        text_y = y - text_height / 2 - 1

        draw.text((text_x, text_y), text, fill=self.STEP_TEXT_COLOR, font=font)

    def create_frame_sequence(
        self,
        base_image: Image.Image,
        trajectory: Trajectory,
        som_annotator: SoMAnnotator,
        processors: list[Processor],
    ) -> list[Image.Image]:
        """Create a sequence of frames showing trajectory progression.

        Args:
            base_image: The base screenshot
            trajectory: The trajectory to animate
            som_annotator: SoM annotator for element markers
            processors: Processors for SoM markers

        Returns:
            List of frames, each showing one more step of the trajectory
        """
        frames = []

        # First frame: just SoM markers, no trajectory
        som_image, _ = som_annotator.annotate(base_image, processors)
        frames.append(som_image)

        # Subsequent frames: add trajectory steps progressively
        for step_idx in range(len(trajectory.steps)):
            # Start with SoM-annotated image
            frame = som_image.copy()
            # Add trajectory up to current step
            frame = self.annotate_trajectory(frame, trajectory, current_step=step_idx)
            frames.append(frame)

        return frames
