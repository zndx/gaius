"""ThetaAgent - Neuromorphic Situational Awareness.

The ThetaAgent provides `/sitrep` as the single pane of glass for daily
situational awareness. It synthesizes:
- Objectives and agent thoughts
- Personal agenda (filtered from all project agendas)
- Current events via search/research actions
- Evolving Gaius capabilities

Grounded in Attention Schema Theory (AST) and theta wave dynamics.
"""

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .horizons import Horizon, HorizonView
from .schema import AttentionSchema, AttentionTarget
from .sitrep import (
    SituationReport,
    HealthStatus,
    PriorityItem,
    ThoughtSummary,
    ObjectiveStatus,
    EvolutionStatus,
    QuickAction,
)
from .agenda import AgendaAggregator
from .actions import ActionLinkProcessor, ActionLink, ActionType, ActionResult


# Action link pattern for detecting in thoughts
ACTION_LINK_PATTERN = re.compile(r'\[action:\w+\s*"[^"]+"\]')


class ThetaAgent:
    """Neuromorphic situational awareness with AST grounding.

    The ThetaAgent models attention as an oscillatory process using
    theta rhythm dynamics. It maintains an AttentionSchema (S+A+V model)
    and generates SITREPs at four temporal horizons.
    """

    def __init__(
        self,
        profile: str = "default",
        kb_root: Path | str | None = None,
    ):
        """Initialize ThetaAgent.

        Args:
            profile: Configuration profile name.
            kb_root: Root of the knowledge base.
        """
        self.profile = profile

        if kb_root is None:
            kb_root = Path("build/dev")
        self.kb_root = Path(kb_root)

        # Core components
        self.schema = AttentionSchema()
        self.agenda = AgendaAggregator(kb_root)
        self.actions = ActionLinkProcessor(kb_root)

        # Register action handlers
        self._register_action_handlers()

    def _register_action_handlers(self) -> None:
        """Register handlers for action link types."""
        self.actions.register_handler(ActionType.SEARCH, self._handle_search)
        self.actions.register_handler(ActionType.WEB, self._handle_web_search)
        self.actions.register_handler(ActionType.EMBED, self._handle_embed)
        self.actions.register_handler(ActionType.RESEARCH, self._handle_research)
        self.actions.register_handler(ActionType.VERIFY, self._handle_verify)

    async def _handle_search(self, link: ActionLink) -> ActionResult:
        """Handle search action links."""
        try:
            from ..mcp_client import call_mcp_tool

            result = await call_mcp_tool("search_kb", {"query": link.argument})
            return ActionResult(action=link, success=True, result=result)
        except Exception as e:
            return ActionResult(action=link, success=False, error=str(e))

    async def _handle_web_search(self, link: ActionLink) -> ActionResult:
        """Handle web search action links."""
        try:
            from ..mcp_client import call_mcp_tool

            result = await call_mcp_tool("web_search", {"query": link.argument})
            return ActionResult(action=link, success=True, result=result)
        except Exception as e:
            return ActionResult(action=link, success=False, error=str(e))

    async def _handle_embed(self, link: ActionLink) -> ActionResult:
        """Handle embed action links."""
        try:
            from ..mcp_client import call_mcp_tool

            result = await call_mcp_tool("embed_text", {"text": link.argument})
            return ActionResult(action=link, success=True, result=result)
        except Exception as e:
            return ActionResult(action=link, success=False, error=str(e))

    async def _handle_research(self, link: ActionLink) -> ActionResult:
        """Handle research action links (requires manual approval)."""
        try:
            from ..mcp_client import call_mcp_tool

            result = await call_mcp_tool(
                "research_topic",
                {"topic": link.argument, "save_to_kb": True},
            )
            artifact_path = result.get("kb_path") if isinstance(result, dict) else None
            return ActionResult(
                action=link,
                success=True,
                result=result,
                artifact_path=artifact_path,
            )
        except Exception as e:
            return ActionResult(action=link, success=False, error=str(e))

    async def _handle_verify(self, link: ActionLink) -> ActionResult:
        """Handle verify action links (requires manual approval)."""
        try:
            from ..mcp_client import call_mcp_tool

            result = await call_mcp_tool(
                "verify_objective",
                {"objective_path": f"current/objectives/{link.argument}.md"},
            )
            return ActionResult(action=link, success=True, result=result)
        except Exception as e:
            return ActionResult(action=link, success=False, error=str(e))

    async def sitrep(
        self,
        horizon: Horizon | str = Horizon.DAY,
    ) -> SituationReport:
        """Generate situational report for time horizon.

        This is the main entry point for the `/sitrep` command.

        Args:
            horizon: Temporal horizon (day, week, quarter, open).

        Returns:
            Complete SituationReport ready for display.
        """
        if isinstance(horizon, str):
            horizon = Horizon(horizon.lower())

        # Collect data in parallel
        results = await asyncio.gather(
            self._collect_health_status(),
            self._collect_priorities(horizon),
            self._collect_thoughts(),
            self._collect_objectives(),
            self._collect_evolution(),
            return_exceptions=True,
        )

        # Unpack results, handling exceptions
        health, priorities, thoughts, objectives, evolution = [
            r if not isinstance(r, Exception) else self._handle_collection_error(r, i)
            for i, r in enumerate(results)
        ]

        # Check if this is a bootstrap scenario (empty KB)
        is_bootstrap = (
            not priorities
            and not objectives
            and not thoughts
            and self.agenda.get_project_count() == 0
        )

        # Generate quick actions based on context
        quick_actions = self._generate_quick_actions(
            is_bootstrap=is_bootstrap,
            has_priorities=bool(priorities),
            has_thoughts=bool(thoughts),
            health_ok=health.healthy if isinstance(health, HealthStatus) else True,
        )

        return SituationReport(
            horizon=horizon,
            generated_at=datetime.now(),
            system_status=health if isinstance(health, HealthStatus) else HealthStatus(),
            priorities=priorities if isinstance(priorities, list) else [],
            thoughts=thoughts if isinstance(thoughts, list) else [],
            objectives=objectives if isinstance(objectives, list) else [],
            evolution=evolution if isinstance(evolution, EvolutionStatus) else EvolutionStatus(),
            quick_actions=quick_actions,
            is_bootstrap=is_bootstrap,
            project_count=self.agenda.get_project_count(),
            total_thoughts=len(thoughts) if isinstance(thoughts, list) else 0,
            total_objectives=len(objectives) if isinstance(objectives, list) else 0,
        )

    def _handle_collection_error(self, error: Exception, index: int) -> Any:
        """Handle errors during data collection.

        Args:
            error: The exception that occurred.
            index: Index of the failed collection (0=health, 1=priorities, etc).

        Returns:
            Default value for the failed collection.
        """
        # Return appropriate defaults
        defaults = [
            HealthStatus(
                healthy=False,
                status_text="ERROR",
                error=str(error),
                suggestion="/health diagnose",
            ),
            [],  # priorities
            [],  # thoughts
            [],  # objectives
            EvolutionStatus(),  # evolution
        ]
        return defaults[index] if index < len(defaults) else None

    async def _collect_health_status(self) -> HealthStatus:
        """Collect system health status."""
        try:
            from ..mcp_client import call_mcp_tool

            # Try to get GPU health
            gpu_result = await call_mcp_tool("gpu_health", {})
            gpu_count = 0
            if isinstance(gpu_result, dict):
                gpus = gpu_result.get("gpus", [])
                gpu_count = len(gpus) if isinstance(gpus, list) else 0

            # Try to get orchestrator status
            orch_result = await call_mcp_tool("orchestrator_status", {})
            endpoint_count = 0
            if isinstance(orch_result, dict):
                endpoints = orch_result.get("endpoints", {})
                endpoint_count = len(endpoints) if isinstance(endpoints, dict) else 0

            # Determine overall status
            healthy = gpu_count > 0
            status_text = "HEALTHY" if healthy else "DEGRADED"

            return HealthStatus(
                healthy=healthy,
                status_text=status_text,
                gpu_count=gpu_count,
                endpoint_count=endpoint_count,
            )
        except Exception as e:
            return HealthStatus(
                healthy=False,
                status_text="UNKNOWN",
                error=str(e),
                suggestion="/health diagnose engine",
            )

    async def _collect_priorities(self, horizon: Horizon) -> list[PriorityItem]:
        """Collect priority items from agenda aggregation."""
        try:
            return self.agenda.to_priority_items(horizon, limit=7)
        except Exception:
            return []

    async def _collect_thoughts(self) -> list[ThoughtSummary]:
        """Collect recent agent thoughts."""
        try:
            from ..mcp_client import call_mcp_tool

            result = await call_mcp_tool("get_recent_thoughts", {"limit": 10})

            if not isinstance(result, dict):
                return []

            thoughts = result.get("thoughts", [])
            summaries = []

            for t in thoughts[:7]:  # Limit to 7±2
                if not isinstance(t, dict):
                    continue

                title = t.get("title", "Untitled")
                content = t.get("content", "")

                # Check for action links
                has_action = bool(ACTION_LINK_PATTERN.search(content))

                # Truncate summary
                summary = content[:80] + "..." if len(content) > 80 else content

                summaries.append(
                    ThoughtSummary(
                        id=t.get("id", ""),
                        thought_type=t.get("thought_type", "unknown"),
                        title=title,
                        summary=summary,
                        has_action_link=has_action,
                    )
                )

            return summaries
        except Exception:
            return []

    async def _collect_objectives(self) -> list[ObjectiveStatus]:
        """Collect objective status from RASE."""
        try:
            from ..mcp_client import call_mcp_tool

            result = await call_mcp_tool("list_objectives", {})

            if not isinstance(result, dict):
                return []

            objectives = result.get("objectives", [])
            statuses = []

            for obj in objectives[:7]:  # Limit to 7±2
                if not isinstance(obj, dict):
                    continue

                name = obj.get("name", "unknown")
                priority = obj.get("priority", "normal")

                # Get verification history for progress
                try:
                    history = await call_mcp_tool(
                        "verification_history",
                        {"objective_name": name, "limit": 1},
                    )
                    if isinstance(history, dict):
                        runs = history.get("runs", [])
                        if runs:
                            latest = runs[0]
                            accuracy = latest.get("accuracy", 0)
                            verdict = latest.get("verdict", "NOT RUN")
                            progress = int(accuracy * 100)
                            status = verdict.upper()
                        else:
                            progress = 0
                            status = "NOT RUN"
                    else:
                        progress = 0
                        status = "NOT RUN"
                except Exception:
                    progress = 0
                    status = "NOT RUN"

                statuses.append(
                    ObjectiveStatus(
                        name=name,
                        progress_pct=progress,
                        status=status,
                        priority=priority,
                    )
                )

            return statuses
        except Exception:
            return []

    async def _collect_evolution(self) -> EvolutionStatus:
        """Collect evolution daemon status."""
        try:
            from ..mcp_client import call_mcp_tool

            result = await call_mcp_tool("evolution_status", {})

            if not isinstance(result, dict):
                return EvolutionStatus()

            return EvolutionStatus(
                next_agent=result.get("next_agent", ""),
                mode=result.get("mode", ""),
                running=result.get("running", False),
                score_before=result.get("score_before"),
                score_after=result.get("score_after"),
            )
        except Exception:
            return EvolutionStatus()

    def _generate_quick_actions(
        self,
        is_bootstrap: bool = False,
        has_priorities: bool = True,
        has_thoughts: bool = True,
        health_ok: bool = True,
    ) -> list[QuickAction]:
        """Generate context-sensitive quick actions.

        Args:
            is_bootstrap: Whether this is a new/empty KB.
            has_priorities: Whether there are agenda items.
            has_thoughts: Whether there are recent thoughts.
            health_ok: Whether system health is good.

        Returns:
            List of suggested quick actions.
        """
        actions = []

        if is_bootstrap:
            actions.extend(
                [
                    QuickAction('/project new "name"', "Create a new project"),
                    QuickAction('/research "topic"', "Research a topic"),
                    QuickAction("/thoughts", "Let Gaius think"),
                ]
            )
        else:
            if not has_priorities:
                actions.append(QuickAction("/agenda init", "Create today's agenda"))

            if not has_thoughts:
                actions.append(QuickAction("/thoughts", "Trigger cognition cycle"))

            if not health_ok:
                actions.append(QuickAction("/health fix", "Run auto-repair"))

            # Always useful actions
            actions.append(QuickAction("/research <topic>", "Start research on topic"))

            if has_thoughts:
                actions.append(QuickAction("/thoughts recent", "View recent thoughts"))

        return actions[:5]  # Limit to 5 actions

    async def update_attention(self) -> AttentionSchema:
        """Update attention schema from current KB state.

        Populates the schema with attention targets derived from:
        - Agenda items (highest priority first)
        - Recent thoughts (by salience)
        - Objective status (failing objectives get attention)

        Returns:
            Updated AttentionSchema.
        """
        # Get current data
        priorities = await self._collect_priorities(Horizon.DAY)
        thoughts = await self._collect_thoughts()
        objectives = await self._collect_objectives()

        # Create attention targets
        targets = []

        # Agenda items as targets
        for i, item in enumerate(priorities[:3]):
            target = AttentionTarget(
                id=f"agenda_{i}",
                content_type="agenda_item",
                title=item.description,
                urgency=1.0 if item.priority == "P0" else 0.7 if item.priority == "P1" else 0.4,
                recency=1.0,  # Today's items are recent
            )
            target.compute_salience(self.schema.salience_weights)
            targets.append(target)

        # Thoughts as targets
        for thought in thoughts[:3]:
            target = AttentionTarget(
                id=thought.id,
                content_type="thought",
                title=thought.title,
                novelty=0.8 if thought.has_action_link else 0.5,
                recency=0.9,
            )
            target.compute_salience(self.schema.salience_weights)
            targets.append(target)

        # Failing objectives as targets
        for obj in objectives:
            if obj.status == "FAIL":
                target = AttentionTarget(
                    id=f"obj_{obj.name}",
                    content_type="objective",
                    title=obj.name,
                    urgency=0.9,  # Failing objectives are urgent
                    relevance=0.8,
                )
                target.compute_salience(self.schema.salience_weights)
                targets.append(target)

        # Sort by salience and update schema
        targets.sort(key=lambda t: t.salience, reverse=True)

        if targets:
            self.schema.shift_attention(targets[0])
            for target in targets[1:]:
                self.schema.add_to_periphery(target)

        return self.schema

    async def process_thought_actions(
        self,
        thought_content: str,
        source_path: str | None = None,
    ) -> list[ActionResult]:
        """Process action links in thought content.

        Args:
            thought_content: The thought content to parse.
            source_path: Optional source path for traceability.

        Returns:
            List of action execution results.
        """
        return await self.actions.process_document(
            Path(source_path) if source_path else Path("/dev/null"),
            auto_only=True,  # Only auto-execute low-RPN actions
        )

    def get_pending_actions(
        self,
        thought_content: str,
        source_path: str | None = None,
    ) -> list[ActionLink]:
        """Get action links that require manual approval.

        Args:
            thought_content: The thought content to parse.
            source_path: Optional source path.

        Returns:
            List of high-RPN action links needing approval.
        """
        return self.actions.get_pending_manual_actions(thought_content, source_path)

    def get_grid_targets(self) -> list[tuple[str, int, int, str]]:
        """Get attention targets as grid positions for THETA view mode.

        Returns:
            List of (id, x, y, color) tuples for grid rendering.
        """
        return self.schema.get_grid_targets()
