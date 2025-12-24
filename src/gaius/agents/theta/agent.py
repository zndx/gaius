"""ThetaAgent - Neuromorphic Situational Awareness.

The ThetaAgent provides `/sitrep` as the single pane of glass for daily
situational awareness. It synthesizes:
- Objectives and agent thoughts
- Personal agenda (filtered from all project agendas)
- Current events via search/research actions
- Evolving Gaius capabilities

Phase 2 adds NVAR-mediated consolidation:
- ThetaDynamics for temporal embedding centroids
- BERTSubs for subsumption inference
- KB augmentation with wikilinks and action links
- SHAP effectiveness measurement
- Knowledge Gradient policy for economic justification

Grounded in Attention Schema Theory (AST) and theta wave dynamics.
"""

import asyncio
import re
from dataclasses import dataclass, field
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

# Phase 2: Consolidation
from .consolidation import ThetaDynamics, ConsolidationSignal, get_week_slice_id
from .subsumption import (
    SubsumptionInferencer,
    SubsumptionCandidate,
    DeepOntoNotAvailableError,
    OntologyValidationError,
    OntologyValidationResult,
    generate_ontology_from_kb,
    validate_ontology,
)
from .augmentation import inject_mixed, AugmentationResult, has_augmentation
from .effectiveness import EffectivenessTracker, compute_augmentation_contribution
from .kg_policy import KnowledgeGradientPolicy, BeliefState


# Action link pattern for detecting in thoughts
ACTION_LINK_PATTERN = re.compile(r'\[action:\w+\s*"[^"]+"\]')

import logging

logger = logging.getLogger(__name__)


@dataclass
class ConsolidationResult:
    """Result of a consolidation cycle.

    Attributes:
        slice_id: Temporal slice processed
        signal: Consolidation signal from NVAR dynamics
        candidates_evaluated: Number of subsumption candidates evaluated
        candidates_selected: Number selected by KG policy
        documents_augmented: Number of documents augmented
        augmentations: List of augmentation results
        effectiveness: Effectiveness measurement if available
        error: Error message if consolidation failed
    """

    slice_id: str
    signal: ConsolidationSignal | None = None
    candidates_evaluated: int = 0
    candidates_selected: int = 0
    documents_augmented: int = 0
    augmentations: list = field(default_factory=list)
    effectiveness: dict | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "slice_id": self.slice_id,
            "signal": self.signal.to_dict() if self.signal else None,
            "candidates_evaluated": self.candidates_evaluated,
            "candidates_selected": self.candidates_selected,
            "documents_augmented": self.documents_augmented,
            "effectiveness": self.effectiveness,
            "error": self.error,
        }


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
        research_mode: bool = True,
    ):
        """Initialize ThetaAgent.

        Args:
            profile: Configuration profile name.
            kb_root: Root of the knowledge base.
            research_mode: If True, bypass KG cost threshold (for theory development).
        """
        self.profile = profile

        if kb_root is None:
            kb_root = Path("build/dev")
        self.kb_root = Path(kb_root)

        # Core components
        self.schema = AttentionSchema()
        self.agenda = AgendaAggregator(kb_root)
        self.actions = ActionLinkProcessor(kb_root)

        # Phase 2: Consolidation components
        self.dynamics = ThetaDynamics(k=4, polynomial_order=2, drift_scale=1.0)

        # Generate domain ontology from KB for BERTSubs
        # Ontology is cached in .cache/ontology/ and regenerated per temporal slice
        self._ontology_cache_dir = self.kb_root / ".cache" / "ontology"
        self._ontology_cache_dir.mkdir(parents=True, exist_ok=True)
        self._current_ontology_path: Path | None = None

        # SubsumptionInferencer is initialized lazily when ontology is generated
        self._subsumption: SubsumptionInferencer | None = None
        self._last_validation: OntologyValidationResult | None = None
        self.confidence_threshold = 0.8

        self.kg_policy = KnowledgeGradientPolicy(
            measurement_cost=1.0,
            research_mode=research_mode,
        )
        self.effectiveness_tracker = EffectivenessTracker(history_limit=100)

        # Register action handlers
        self._register_action_handlers()

    def get_subsumption_inferencer(self, slice_id: str | None = None) -> SubsumptionInferencer:
        """Get SubsumptionInferencer, generating ontology if needed.

        Creates an OWL ontology from KB content for the specified temporal slice
        (or current content if no slice specified). Ontologies are cached by slice_id.

        The ontology generation includes a validation feedback loop that ensures:
        1. Generated OWL is syntactically valid XML/RDF
        2. owlready2 can load the ontology
        3. DeepOnto can load the ontology (critical for BERTSubs)

        Args:
            slice_id: Temporal slice to generate ontology from (e.g., "2025-W52")

        Returns:
            SubsumptionInferencer initialized with domain ontology

        Raises:
            DeepOntoNotAvailableError: If DeepOnto/owlready2 not available
            OntologyValidationError: If generated ontology fails validation
        """
        # Determine ontology path based on slice
        ontology_filename = f"kb_{slice_id or 'current'}.owl"
        ontology_path = self._ontology_cache_dir / ontology_filename

        # Generate ontology if it doesn't exist or slice changed
        if not ontology_path.exists() or self._current_ontology_path != ontology_path:
            logger.info(f"Generating ontology for slice: {slice_id or 'current'}")

            # Generate with validation enabled (fail-fast on invalid ontology)
            path, validation_result = generate_ontology_from_kb(
                kb_root=self.kb_root,
                output_path=ontology_path,
                slice_id=slice_id,
                validate=True,  # Enforce validation feedback loop
            )

            if validation_result:
                logger.info(
                    f"Ontology validated: {validation_result.concept_count} classes, "
                    f"DeepOnto loaded: {validation_result.deeponto_loaded}, "
                    f"stages: {validation_result.stages_passed}"
                )
                self._last_validation = validation_result
            else:
                logger.warning("Ontology generated without validation")

            self._current_ontology_path = ontology_path
            # Reinitialize inferencer with new ontology
            self._subsumption = None

        if self._subsumption is None:
            self._subsumption = SubsumptionInferencer(
                ontology_path=ontology_path,
                confidence_threshold=self.confidence_threshold,
            )

        return self._subsumption

    @property
    def subsumption(self) -> SubsumptionInferencer:
        """Get default subsumption inferencer (uses current KB content)."""
        return self.get_subsumption_inferencer()

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

    # =========================================================================
    # Phase 2: Consolidation
    # =========================================================================

    async def run_consolidation(
        self,
        temporal_slice: str | None = None,
        max_candidates: int = 10,
        holdout_queries: list[str] | None = None,
    ) -> ConsolidationResult:
        """Run a consolidation cycle for a temporal slice.

        The consolidation cycle:
        1. Compute consolidation signal from NVAR dynamics
        2. Extract concept pairs from slice documents
        3. Use BERTSubs to infer subsumption relationships
        4. Apply KG policy to select candidates for verification
        5. Augment KB documents with wikilinks and action links
        6. Measure effectiveness if holdout queries provided

        Args:
            temporal_slice: Slice ID (e.g., "2025-W52"). If None, uses current week.
            max_candidates: Maximum candidates to evaluate per cycle.
            holdout_queries: Queries reserved for effectiveness measurement.

        Returns:
            ConsolidationResult with cycle outcomes.

        Raises:
            DeepOntoNotAvailableError: If BERTSubs is required but unavailable.
        """
        import numpy as np

        slice_id = temporal_slice or get_week_slice_id()
        logger.info(f"Starting consolidation cycle for slice {slice_id}")

        result = ConsolidationResult(slice_id=slice_id)

        try:
            # Step 1: Get slice centroid from latent memory
            centroid = await self._get_slice_centroid(slice_id)
            if centroid is None:
                result.error = f"No documents found for slice {slice_id}"
                logger.warning(result.error)
                return result

            # Step 2: Compute consolidation signal from NVAR dynamics
            signal = self.dynamics.add_slice(
                slice_id=slice_id,
                centroid=centroid,
                document_count=await self._get_slice_document_count(slice_id),
            )
            result.signal = signal

            if signal is None:
                logger.info("Insufficient history for NVAR prediction (need k+1 slices)")
                # Continue without signal - use default urgency
                urgency = 0.5
            else:
                urgency = signal.urgency
                logger.info(f"Consolidation signal: urgency={urgency:.3f}, drift={signal.drift:.3f}")

            # Step 3: Extract concept pairs from slice documents
            concept_pairs = await self._extract_concept_pairs(slice_id, limit=max_candidates * 2)
            if not concept_pairs:
                result.error = "No concept pairs extracted"
                logger.warning(result.error)
                return result

            result.candidates_evaluated = len(concept_pairs)

            # Step 4: Infer subsumptions using BERTSubs
            # The consolidation signal mediates depth (how many we evaluate)
            candidates = await self.subsumption.infer_subsumptions(
                candidates=concept_pairs,
                consolidation_signal=urgency,
                source_slice=slice_id,
                target_slice=slice_id,
            )

            # Step 5: Apply KG policy to select candidates
            selected = self.kg_policy.select_candidates(
                candidates=candidates,
                max_candidates=max_candidates,
            )
            result.candidates_selected = len(selected)

            logger.info(f"KG policy selected {len(selected)}/{len(candidates)} candidates")

            # Step 6: Augment KB documents
            augmentation_results = await self._augment_documents(
                candidates=selected,
                slice_id=slice_id,
            )
            result.documents_augmented = len(augmentation_results)
            result.augmentations = [ar.to_dict() for ar in augmentation_results]

            # Step 7: Measure effectiveness if holdout queries provided
            if holdout_queries:
                effectiveness = await self._measure_effectiveness(
                    holdout_queries=holdout_queries,
                    slice_id=slice_id,
                )
                result.effectiveness = effectiveness
                self.effectiveness_tracker.add_result(effectiveness)

            logger.info(
                f"Consolidation complete: {result.documents_augmented} documents augmented, "
                f"{result.candidates_selected} subsumptions applied"
            )

        except DeepOntoNotAvailableError as e:
            result.error = str(e)
            logger.error(f"DeepOnto unavailable: {e}")
            raise  # Re-raise - fail-fast

        except Exception as e:
            result.error = f"Consolidation failed: {e}"
            logger.exception(result.error)

        return result

    async def _get_slice_centroid(self, slice_id: str) -> "np.ndarray | None":
        """Get centroid embedding for a temporal slice.

        Args:
            slice_id: Temporal slice ID.

        Returns:
            Centroid embedding or None if slice is empty.
        """
        try:
            from ..latent.memory import LatentWorkingMemory

            memory = LatentWorkingMemory()
            centroid = await memory.compute_slice_centroid(slice_id)
            return centroid
        except Exception as e:
            logger.warning(f"Failed to compute slice centroid: {e}")
            return None

    async def _get_slice_document_count(self, slice_id: str) -> int:
        """Get document count for a temporal slice.

        Args:
            slice_id: Temporal slice ID.

        Returns:
            Number of documents in the slice.
        """
        try:
            from ..latent.memory import LatentWorkingMemory

            memory = LatentWorkingMemory()
            thoughts = await memory.retrieve_by_slice(slice_id)
            return len(thoughts)
        except Exception:
            return 0

    async def _extract_concept_pairs(
        self,
        slice_id: str,
        limit: int = 20,
    ) -> list[tuple[str, str]]:
        """Extract concept pairs from slice documents for subsumption inference.

        Concept pairs are extracted from:
        - KB document frontmatter (tags, categories)
        - Wikilinks in document content
        - Named entities extracted by NLP

        Args:
            slice_id: Temporal slice ID.
            limit: Maximum pairs to extract.

        Returns:
            List of (subclass, superclass) candidate pairs.
        """
        pairs = []

        try:
            from ..mcp_client import call_mcp_tool

            # Search KB for documents in this slice
            result = await call_mcp_tool(
                "search_kb",
                {"query": f"slice:{slice_id}", "max_results": limit * 2},
            )

            if not isinstance(result, dict):
                return pairs

            entries = result.get("entries", [])

            # Extract concepts from document paths and content
            concepts = set()
            for entry in entries:
                path = entry.get("path", "")
                content = entry.get("content", "")

                # Extract from path (e.g., "current/topics/kudu.md" -> "kudu")
                if "/" in path:
                    topic = Path(path).stem
                    if topic and not topic.startswith("_"):
                        concepts.add(topic)

                # Extract wikilinks [[concept]]
                wikilinks = re.findall(r"\[\[([^\]]+)\]\]", content)
                concepts.update(wikilinks)

            # Generate candidate pairs (smaller concept -> larger concept by name length heuristic)
            concept_list = sorted(concepts, key=len)
            for i, subclass in enumerate(concept_list[: limit // 2]):
                for superclass in concept_list[i + 1: i + 4]:  # Pair with 3 longer concepts
                    if subclass != superclass:
                        pairs.append((subclass, superclass))

            logger.debug(f"Extracted {len(pairs)} concept pairs from slice {slice_id}")

        except Exception as e:
            logger.warning(f"Failed to extract concept pairs: {e}")

        return pairs[:limit]

    async def _augment_documents(
        self,
        candidates: list[SubsumptionCandidate],
        slice_id: str,
    ) -> list[AugmentationResult]:
        """Augment KB documents with discovered subsumptions.

        For each accepted subsumption:
        1. Find the subclass document
        2. Inject wikilink to superclass
        3. Inject action:search link for exploration

        Args:
            candidates: Accepted subsumption candidates.
            slice_id: Temporal slice for augmentation metadata.

        Returns:
            List of augmentation results.
        """
        results = []
        cycle_id = f"consolidation_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        for candidate in candidates:
            # Find document for subclass concept
            doc_path = self._find_concept_document(candidate.subclass)
            if doc_path is None:
                logger.debug(f"No document found for concept: {candidate.subclass}")
                continue

            try:
                content = doc_path.read_text()

                # Skip if already augmented with this relationship
                if f"[[{candidate.superclass}]]" in content:
                    logger.debug(f"Document already has link to {candidate.superclass}")
                    continue

                # Inject mixed augmentation (wikilinks + action links)
                augmented_content, wiki_count, action_count = inject_mixed(
                    content=content,
                    wikilinks=[candidate.superclass],
                    action_links=[f"{candidate.subclass} {candidate.superclass} relationship"],
                    slice_id=slice_id,
                    cycle_id=cycle_id,
                )

                # Write augmented content
                doc_path.write_text(augmented_content)

                # Create AugmentationResult for tracking
                aug_result = AugmentationResult(
                    document_path=doc_path,
                    augmentation_type="mixed",
                    content_added=f"[[{candidate.superclass}]]",
                    slice_id=slice_id,
                    cycle_id=cycle_id or "",
                    wikilinks_added=wiki_count,
                    action_links_added=action_count,
                )
                results.append(aug_result)

                logger.info(
                    f"Augmented {doc_path.name}: added [[{candidate.superclass}]] "
                    f"(confidence={candidate.confidence:.2f})"
                )

                # Update KG belief state with measurement
                # For now, use confidence as proxy for retrieval improvement
                self.kg_policy.update_from_measurement(
                    candidate=candidate,
                    observed_improvement=candidate.confidence * 0.5,  # Conservative estimate
                )

            except Exception as e:
                logger.warning(f"Failed to augment {doc_path}: {e}")

        return results

    def _find_concept_document(self, concept: str) -> Path | None:
        """Find KB document for a concept.

        Searches in standard KB locations:
        - current/topics/{concept}.md
        - current/content/domains/*/{concept}.md
        - scratch/*/{concept}.md

        Args:
            concept: Concept name to find.

        Returns:
            Path to document or None if not found.
        """
        # Normalize concept name for file matching
        normalized = concept.lower().replace(" ", "_").replace("-", "_")

        search_patterns = [
            f"current/topics/{normalized}.md",
            f"current/topics/{concept}.md",
            f"current/content/domains/**/{normalized}.md",
            f"scratch/**/{normalized}.md",
        ]

        for pattern in search_patterns:
            matches = list(self.kb_root.glob(pattern))
            if matches:
                return matches[0]

        return None

    async def _measure_effectiveness(
        self,
        holdout_queries: list[str],
        slice_id: str,
    ) -> dict:
        """Measure consolidation effectiveness on holdout queries.

        Args:
            holdout_queries: Queries reserved for evaluation.
            slice_id: Temporal slice being evaluated.

        Returns:
            Dict with effectiveness metrics.
        """
        from .effectiveness import EffectivenessResult

        try:
            from ..mcp_client import call_mcp_tool

            # Get embedder function
            async def embedder(text: str):
                import numpy as np

                result = await call_mcp_tool("embed_text", {"text": text})
                if isinstance(result, dict) and "embedding" in result:
                    return np.array(result["embedding"])
                return np.zeros(768)  # Default dimension

            # Find documents in slice
            doc_paths = list(self.kb_root.glob(f"scratch/{slice_id.replace('-W', '/')}/**/*.md"))
            if not doc_paths:
                doc_paths = list(self.kb_root.glob("current/**/*.md"))[:50]

            # Compute effectiveness
            result = await compute_augmentation_contribution(
                queries=holdout_queries,
                document_paths=doc_paths,
                embedder=embedder,
            )

            return result.to_dict()

        except Exception as e:
            logger.warning(f"Failed to measure effectiveness: {e}")
            return {"error": str(e)}

    def get_consolidation_stats(self) -> dict:
        """Get consolidation statistics.

        Returns:
            Dict with dynamics, KG policy, effectiveness, and ontology validation stats.
        """
        stats = {
            "dynamics": self.dynamics.get_stats(),
            "kg_policy": self.kg_policy.get_stats(),
            "effectiveness": self.effectiveness_tracker.get_stats(),
        }

        # Include subsumption stats if inferencer is initialized
        if self._subsumption is not None:
            stats["subsumption"] = self._subsumption.get_stats()
        else:
            stats["subsumption"] = {"initialized": False}

        # Include last validation result
        if self._last_validation is not None:
            stats["ontology_validation"] = self._last_validation.to_dict()
        else:
            stats["ontology_validation"] = {"validated": False}

        return stats
