"""Action link processing with FMEA-based execution control.

Action links in thoughts/documents trigger automated knowledge expansion.
Processing is FMEA-based: low-RPN actions auto-execute, high-RPN actions
surface for manual approval.

Syntax:
    [action:search "query"]      - KB/web search (auto)
    [action:web "query"]         - Web search only (auto)
    [action:embed "text"]        - Generate embedding (auto)
    [action:research "topic"]    - Research synthesis (manual)
    [action:verify "objective"]  - RASE verification (manual)
    [action:swarm "query"]       - Multi-agent swarm (manual)
    [action:evolve "agent"]      - Trigger evolution (manual)
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Awaitable


# Action link regex pattern
# Matches: [action:type "argument"] or [action:type "arg1" "arg2"]
ACTION_LINK_PATTERN = re.compile(
    r'\[action:(\w+)\s*"([^"]+)"(?:\s*"([^"]+)")?\]'
)


class ActionType(str, Enum):
    """Types of action links."""

    SEARCH = "search"
    WEB = "web"
    EMBED = "embed"
    RESEARCH = "research"
    VERIFY = "verify"
    SWARM = "swarm"
    EVOLVE = "evolve"


@dataclass
class FMEAScore:
    """FMEA Risk Priority Number components.

    RPN = Severity × Occurrence × Detection
    Lower RPN = safer to auto-execute.
    """

    severity: int  # 1-10: Impact if action fails
    occurrence: int  # 1-10: How often action is used
    detection: int  # 1-10: How hard to detect failure

    @property
    def rpn(self) -> int:
        """Calculate Risk Priority Number."""
        return self.severity * self.occurrence * self.detection

    @property
    def auto_execute(self) -> bool:
        """Whether this action should auto-execute."""
        return self.rpn <= AUTO_THRESHOLD


# FMEA scores for each action type
# RPN = Severity × Occurrence × Detection
ACTION_FMEA: dict[ActionType, FMEAScore] = {
    # Read-only, fast, cheap actions (auto-execute)
    ActionType.SEARCH: FMEAScore(severity=1, occurrence=10, detection=1),  # RPN=10
    ActionType.WEB: FMEAScore(severity=1, occurrence=8, detection=1),  # RPN=8
    ActionType.EMBED: FMEAScore(severity=1, occurrence=6, detection=1),  # RPN=6
    # Actions that create content (manual)
    ActionType.RESEARCH: FMEAScore(severity=5, occurrence=5, detection=3),  # RPN=75
    ActionType.VERIFY: FMEAScore(severity=4, occurrence=4, detection=4),  # RPN=64
    # High-impact actions (manual)
    ActionType.SWARM: FMEAScore(severity=6, occurrence=3, detection=4),  # RPN=72
    ActionType.EVOLVE: FMEAScore(severity=8, occurrence=2, detection=5),  # RPN=80
}

# Threshold for auto-execution
AUTO_THRESHOLD = 50


@dataclass
class ActionLink:
    """A parsed action link from document content."""

    action_type: ActionType
    argument: str
    second_argument: str | None = None
    source_path: str | None = None
    line_number: int | None = None

    @property
    def fmea(self) -> FMEAScore:
        """Get FMEA score for this action type."""
        return ACTION_FMEA.get(
            self.action_type,
            FMEAScore(severity=5, occurrence=5, detection=5),  # Default medium
        )

    @property
    def rpn(self) -> int:
        """Get Risk Priority Number."""
        return self.fmea.rpn

    @property
    def auto_execute(self) -> bool:
        """Whether this action should auto-execute."""
        return self.fmea.auto_execute

    @property
    def rpn_category(self) -> str:
        """Get RPN category for display."""
        if self.rpn <= 20:
            return "low"
        elif self.rpn <= 50:
            return "medium"
        else:
            return "high"


@dataclass
class ActionResult:
    """Result of executing an action link."""

    action: ActionLink
    success: bool
    result: Any = None
    error: str | None = None
    executed_at: datetime = field(default_factory=datetime.now)
    artifact_path: str | None = None  # Path to created KB entry if any

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "action_type": self.action.action_type.value,
            "argument": self.action.argument,
            "success": self.success,
            "error": self.error,
            "artifact_path": self.artifact_path,
            "executed_at": self.executed_at.isoformat(),
            "rpn": self.action.rpn,
            "auto_executed": self.action.auto_execute,
        }


def parse_action_links(content: str, source_path: str | None = None) -> list[ActionLink]:
    """Parse action links from document content.

    Args:
        content: Document content to parse.
        source_path: Optional source path for traceability.

    Returns:
        List of parsed action links.
    """
    links = []

    for i, line in enumerate(content.split("\n"), 1):
        for match in ACTION_LINK_PATTERN.finditer(line):
            action_type_str, arg1, arg2 = match.groups()

            try:
                action_type = ActionType(action_type_str.lower())
            except ValueError:
                continue  # Skip unknown action types

            link = ActionLink(
                action_type=action_type,
                argument=arg1,
                second_argument=arg2,
                source_path=source_path,
                line_number=i,
            )
            links.append(link)

    return links


class ActionLinkProcessor:
    """Processes action links with FMEA-based execution control.

    Low-RPN actions (search, web, embed) auto-execute.
    High-RPN actions (research, swarm, evolve) require manual approval.
    """

    def __init__(self, kb_root: Path | str | None = None):
        """Initialize processor.

        Args:
            kb_root: Root of the knowledge base.
        """
        if kb_root is None:
            kb_root = Path("build/dev")
        self.kb_root = Path(kb_root)

        # Execution handlers (set by ThetaAgent)
        self.handlers: dict[ActionType, Callable[[ActionLink], Awaitable[ActionResult]]] = {}

    def register_handler(
        self,
        action_type: ActionType,
        handler: Callable[[ActionLink], Awaitable[ActionResult]],
    ) -> None:
        """Register a handler for an action type.

        Args:
            action_type: The action type to handle.
            handler: Async function to execute the action.
        """
        self.handlers[action_type] = handler

    async def process_document(
        self,
        path: Path | str,
        auto_only: bool = True,
    ) -> list[ActionResult]:
        """Process all action links in a document.

        Args:
            path: Path to the document.
            auto_only: Only execute auto-executable actions.

        Returns:
            List of action results.
        """
        path = Path(path)
        if not path.exists():
            return []

        content = path.read_text(encoding="utf-8")
        links = parse_action_links(content, str(path))

        results = []
        for link in links:
            if auto_only and not link.auto_execute:
                continue

            result = await self.execute(link)
            results.append(result)

        return results

    async def execute(self, link: ActionLink) -> ActionResult:
        """Execute a single action link.

        Args:
            link: The action link to execute.

        Returns:
            Execution result.
        """
        handler = self.handlers.get(link.action_type)

        if handler is None:
            return ActionResult(
                action=link,
                success=False,
                error=f"No handler registered for {link.action_type.value}",
            )

        try:
            return await handler(link)
        except Exception as e:
            return ActionResult(
                action=link,
                success=False,
                error=str(e),
            )

    def get_pending_manual_actions(
        self,
        content: str,
        source_path: str | None = None,
    ) -> list[ActionLink]:
        """Get action links that require manual approval.

        Args:
            content: Document content to parse.
            source_path: Optional source path.

        Returns:
            List of high-RPN action links.
        """
        links = parse_action_links(content, source_path)
        return [link for link in links if not link.auto_execute]

    def get_auto_actions(
        self,
        content: str,
        source_path: str | None = None,
    ) -> list[ActionLink]:
        """Get action links that can auto-execute.

        Args:
            content: Document content to parse.
            source_path: Optional source path.

        Returns:
            List of low-RPN action links.
        """
        links = parse_action_links(content, source_path)
        return [link for link in links if link.auto_execute]
