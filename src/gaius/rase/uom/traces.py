"""UOM Trace definitions for Trace-of-Mark (ToM) sequences.

Provides data structures for representing action sequences over time,
following the Magma ToM approach.

Maps to SysML v2:
    item def TraceOfMarks {
        part frames : ScreenshotWithSoM[*];
        attribute actionTokens : String;
    }

The ToM pattern:
1. Record a sequence of UI states (screenshots with marks)
2. Record the actions taken between states
3. Train agents to predict action sequences from initial state

This enables learning of multi-step UI interactions.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from gaius.rase.traceability import TraceableId, IdScheme
from .marks import PixelCoord, Mark, ScreenshotWithSoM


class UIActionType(str, Enum):
    """Types of UI actions that can be performed."""

    # Mouse actions
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    DRAG = "drag"
    DROP = "drop"
    HOVER = "hover"
    SCROLL = "scroll"

    # Keyboard actions
    TYPE = "type"
    KEY_PRESS = "key_press"
    KEY_COMBO = "key_combo"  # e.g., Ctrl+C

    # High-level actions (composite)
    SELECT_FROM_DROPDOWN = "select_from_dropdown"
    TOGGLE = "toggle"
    SUBMIT = "submit"
    CANCEL = "cancel"

    # NiFi-specific
    CONNECT_PORTS = "connect_ports"
    CONFIGURE_PROCESSOR = "configure_processor"
    START_PROCESSOR = "start_processor"
    STOP_PROCESSOR = "stop_processor"


class UIAction(BaseModel):
    """A UI action performed on a mark.

    Represents an atomic interaction with the UI.

    Attributes:
        action_type: Type of action performed
        target_mark_id: The mark this action targets
        parameters: Action-specific parameters
        timestamp: When the action was performed

    Examples:
        UIAction(action_type=UIActionType.CLICK, target_mark_id=3)
        UIAction(action_type=UIActionType.TYPE, target_mark_id=5,
                 parameters={"text": "GetFile"})
        UIAction(action_type=UIActionType.DRAG, target_mark_id=2,
                 parameters={"to_mark_id": 4})
    """

    action_type: UIActionType
    target_mark_id: int
    parameters: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)

    # Duration of the action (for timing analysis)
    duration_ms: int = 0

    # Success/failure status (filled after execution)
    succeeded: bool | None = None
    error_message: str | None = None

    model_config = {"frozen": True}

    def to_token(self) -> str:
        """Convert to string token for sequence modeling.

        Format: ACTION_TYPE(mark_id, params...)

        Examples:
            "CLICK(3)"
            "TYPE(5, 'GetFile')"
            "DRAG(2, to=4)"
        """
        params_str = ""
        if self.parameters:
            param_parts = [f"{k}={repr(v)}" for k, v in self.parameters.items()]
            params_str = ", " + ", ".join(param_parts)

        return f"{self.action_type.value}({self.target_mark_id}{params_str})"

    @classmethod
    def from_token(cls, token: str) -> "UIAction":
        """Parse from token string.

        Note: This is a simplified parser - production use would need
        more robust parsing.
        """
        import re
        match = re.match(r"(\w+)\((\d+)(?:,\s*(.+))?\)", token)
        if not match:
            raise ValueError(f"Invalid action token: {token}")

        action_type = UIActionType(match.group(1))
        target_mark_id = int(match.group(2))
        params = {}

        # Parse remaining params if present
        if match.group(3):
            # Simple key=value parsing
            for param in match.group(3).split(","):
                if "=" in param:
                    k, v = param.strip().split("=", 1)
                    # Try to eval the value (handle quotes, numbers)
                    try:
                        params[k] = eval(v)
                    except:
                        params[k] = v.strip("'\"")

        return cls(
            action_type=action_type,
            target_mark_id=target_mark_id,
            parameters=params,
        )

    # Convenience factory methods
    @classmethod
    def click(cls, mark_id: int) -> "UIAction":
        return cls(action_type=UIActionType.CLICK, target_mark_id=mark_id)

    @classmethod
    def double_click(cls, mark_id: int) -> "UIAction":
        return cls(action_type=UIActionType.DOUBLE_CLICK, target_mark_id=mark_id)

    @classmethod
    def right_click(cls, mark_id: int) -> "UIAction":
        return cls(action_type=UIActionType.RIGHT_CLICK, target_mark_id=mark_id)

    @classmethod
    def type_text(cls, mark_id: int, text: str) -> "UIAction":
        return cls(
            action_type=UIActionType.TYPE,
            target_mark_id=mark_id,
            parameters={"text": text},
        )

    @classmethod
    def drag_to(cls, from_mark_id: int, to_mark_id: int) -> "UIAction":
        return cls(
            action_type=UIActionType.DRAG,
            target_mark_id=from_mark_id,
            parameters={"to_mark_id": to_mark_id},
        )

    @classmethod
    def key_combo(cls, mark_id: int, keys: str) -> "UIAction":
        """Create key combo action (e.g., "ctrl+c", "shift+tab")."""
        return cls(
            action_type=UIActionType.KEY_COMBO,
            target_mark_id=mark_id,
            parameters={"keys": keys},
        )


class ActionFrame(BaseModel):
    """A single frame in an action trace.

    Captures the state before and after an action, enabling
    before/after comparison for verification.

    Attributes:
        frame_index: Position in the trace (0-indexed)
        before_screenshot: State before the action
        action: The action performed
        after_screenshot: State after the action (optional)
        state_change_detected: Whether SSM state changed
    """

    frame_index: int
    before_screenshot: ScreenshotWithSoM
    action: UIAction
    after_screenshot: ScreenshotWithSoM | None = None

    # Verification metadata
    state_change_detected: bool = False
    ssm_diff_summary: str | None = None

    model_config = {"frozen": True}


class TraceOfMarks(BaseModel):
    """A sequence of UI observations and actions.

    This is the primary training artifact for ToM-style learning:
    a complete trajectory through the UI showing how to accomplish
    a task.

    Attributes:
        id: Traceable identifier
        frames: Sequence of action frames
        scenario_id: Link to the OSM scenario being demonstrated
        start_time: When the trace began
        end_time: When the trace completed
        succeeded: Whether the trace completed successfully

    Example:
        trace = TraceOfMarks(
            scenario_id=TraceableId.from_bdd(...),
            frames=[
                ActionFrame(frame_index=0, ...),
                ActionFrame(frame_index=1, ...),
            ],
        )
    """

    id: TraceableId = Field(
        default_factory=lambda: TraceableId.generate(IdScheme.TOM, "trace")
    )
    frames: list[ActionFrame] = Field(default_factory=list)

    # Scenario link
    scenario_id: TraceableId | None = None
    scenario_name: str = ""

    # Timing
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: datetime | None = None

    # Outcome
    succeeded: bool | None = None
    failure_reason: str | None = None

    # Metadata
    agent_id: str | None = None  # Which agent produced this trace
    environment_id: str | None = None  # Which test environment

    model_config = {"frozen": True}

    @property
    def duration_seconds(self) -> float | None:
        """Total trace duration in seconds."""
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds()

    @property
    def action_count(self) -> int:
        """Number of actions in the trace."""
        return len(self.frames)

    @property
    def actions(self) -> list[UIAction]:
        """Extract just the actions from frames."""
        return [f.action for f in self.frames]

    def action_tokens(self) -> list[str]:
        """Convert actions to token sequence."""
        return [f.action.to_token() for f in self.frames]

    def action_sequence_str(self) -> str:
        """Actions as a single string (for display/logging)."""
        return " -> ".join(self.action_tokens())

    def to_training_format(self) -> dict[str, Any]:
        """Convert to Magma-style training format.

        Returns a dict suitable for training data:
        - trace_id: Unique identifier
        - scenario: Scenario name/ID
        - initial_state: First screenshot with marks
        - action_sequence: List of action tokens
        - frames: Full frame data for detailed training
        """
        return {
            "trace_id": str(self.id),
            "scenario": self.scenario_name or str(self.scenario_id),
            "initial_state": (
                self.frames[0].before_screenshot.to_training_format()
                if self.frames else None
            ),
            "action_sequence": self.action_tokens(),
            "frames": [
                {
                    "index": f.frame_index,
                    "before": f.before_screenshot.to_training_format(),
                    "action": f.action.to_token(),
                    "after": (
                        f.after_screenshot.to_training_format()
                        if f.after_screenshot else None
                    ),
                }
                for f in self.frames
            ],
            "succeeded": self.succeeded,
        }


class TraceRecorder:
    """Records UI action traces for training data generation.

    Provides methods for recording actions and screenshots during
    scenario execution.

    Example:
        recorder = TraceRecorder(scenario_id=scenario.id)

        async with recorder:
            # Capture initial state
            screenshot = await capture_screenshot()
            som = await generator.annotate_screenshot(screenshot)
            recorder.set_initial_state(som)

            # Record actions
            recorder.record_action(UIAction.click(3))
            recorder.update_state(new_som)

            # Finalize
            trace = recorder.finalize(succeeded=True)
    """

    def __init__(
        self,
        scenario_id: TraceableId | None = None,
        scenario_name: str = "",
        agent_id: str | None = None,
    ):
        self.scenario_id = scenario_id
        self.scenario_name = scenario_name
        self.agent_id = agent_id

        self._frames: list[ActionFrame] = []
        self._current_state: ScreenshotWithSoM | None = None
        self._frame_index = 0
        self._start_time = datetime.now()

    def set_initial_state(self, screenshot: ScreenshotWithSoM) -> None:
        """Set the initial state before any actions."""
        self._current_state = screenshot

    def record_action(
        self,
        action: UIAction,
        after_screenshot: ScreenshotWithSoM | None = None,
    ) -> ActionFrame:
        """Record an action and its effect.

        Args:
            action: The action performed
            after_screenshot: State after the action (optional, can be set later)

        Returns:
            The recorded ActionFrame
        """
        if self._current_state is None:
            raise ValueError("Initial state not set. Call set_initial_state first.")

        frame = ActionFrame(
            frame_index=self._frame_index,
            before_screenshot=self._current_state,
            action=action,
            after_screenshot=after_screenshot,
        )

        self._frames.append(frame)
        self._frame_index += 1

        # Update current state if after_screenshot provided
        if after_screenshot:
            self._current_state = after_screenshot

        return frame

    def update_state(self, screenshot: ScreenshotWithSoM) -> None:
        """Update the current state (after an action completes).

        This updates the after_screenshot of the last frame and sets
        the current state for the next action.
        """
        if self._frames:
            # Update the last frame's after_screenshot
            last_frame = self._frames[-1]
            self._frames[-1] = ActionFrame(
                frame_index=last_frame.frame_index,
                before_screenshot=last_frame.before_screenshot,
                action=last_frame.action,
                after_screenshot=screenshot,
                state_change_detected=last_frame.state_change_detected,
                ssm_diff_summary=last_frame.ssm_diff_summary,
            )

        self._current_state = screenshot

    def finalize(
        self,
        succeeded: bool | None = None,
        failure_reason: str | None = None,
    ) -> TraceOfMarks:
        """Finalize the trace and return the TraceOfMarks."""
        return TraceOfMarks(
            frames=self._frames,
            scenario_id=self.scenario_id,
            scenario_name=self.scenario_name,
            start_time=self._start_time,
            end_time=datetime.now(),
            succeeded=succeeded,
            failure_reason=failure_reason,
            agent_id=self.agent_id,
        )

    async def __aenter__(self) -> "TraceRecorder":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        # Auto-finalize on context exit if not already done
        pass


__all__ = [
    "UIActionType",
    "UIAction",
    "ActionFrame",
    "TraceOfMarks",
    "TraceRecorder",
]
