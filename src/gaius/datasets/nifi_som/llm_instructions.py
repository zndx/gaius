"""LLM-powered instruction generation for diverse, high-quality training data.

Uses optillm BON (Best-of-N) technique for diverse candidate generation,
then validates and scores candidates through the pipeline stages.

Supports optional XAI calibration using the 6-dimension rubric:
- Intent Understanding (15%)
- SoM Grounding (20%)
- Action Semantics (20%)
- ToM Trace (15%) - 4/4 for single actions
- Constraints (15%)
- Outcome (15%)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from .models import Action, Processor, Mark, Trajectory
from .prompts.generation import (
    get_generation_prompt,
    get_connection_prompt,
    get_trajectory_prompt,
)
from gaius.core.budgets import EXTERNAL_MAX_TOKENS

if TYPE_CHECKING:
    from .calibration import CalibrationOrchestrator, LocalScoreInput
    from .rubric import RubricScore

logger = logging.getLogger(__name__)

# Style dimensions for diverse generation
STYLES = ["technical", "conversational", "brief", "detailed", "action_oriented"]


@dataclass
class FlowContext:
    """Context about the NiFi flow for instruction generation."""

    flow_name: str
    flow_description: str = "processes data through multiple stages"
    processor_purposes: dict[str, str] = field(default_factory=dict)


@dataclass
class InstructionCandidate:
    """A candidate instruction with metadata."""

    text: str
    style: str
    target_mark: Optional[int] = None
    processor_name: Optional[str] = None
    processor_type: Optional[str] = None
    quality_score: Optional[float] = None
    alignment_score: Optional[float] = None
    is_aligned: bool = False

    # Quality score breakdown (from local scorer)
    clarity: Optional[float] = None
    naturalness: Optional[float] = None
    specificity: Optional[float] = None
    conciseness: Optional[float] = None

    # Calibration results (from XAI)
    xai_score: Optional["RubricScore"] = None
    calibration_delta: Optional[float] = None


class LLMInstructionGenerator:
    """Generate diverse instructions via optillm BON.

    Architecture:
        1. For each action, generate N candidates using BON (Best-of-N)
        2. Each candidate uses a different style (technical, conversational, etc.)
        3. Candidates are filtered by alignment and quality scoring

    Usage:
        generator = LLMInstructionGenerator()
        candidates = await generator.generate_candidates(
            action=Action(type="click", coordinates=(0.5, 0.5), target_mark=1),
            processor=Processor(id="1", name="fetch_pdf", type="GetHTTP", position={"x": 100, "y": 100}),
            context=FlowContext(flow_name="ArxivDoclingFlow"),
        )
    """

    def __init__(
        self,
        n_candidates: int = 5,
        temperature: float = 0.8,
        max_tokens: int = EXTERNAL_MAX_TOKENS,
    ):
        """Initialize the generator.

        Args:
            n_candidates: Number of candidates to generate per action
            temperature: Sampling temperature for diversity
            max_tokens: Maximum tokens per generation
        """
        self.n_candidates = n_candidates
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = None

    async def _get_client(self):
        """Lazy-load inference client."""
        if self._client is None:
            from gaius.client.engine_client import EngineInferenceClient as InferenceClient
            self._client = InferenceClient()
        return self._client

    async def generate_candidates(
        self,
        action: Action,
        processor: Processor,
        context: FlowContext,
        n_candidates: Optional[int] = None,
    ) -> list[InstructionCandidate]:
        """Generate diverse instruction candidates for an action.

        Uses BON (Best-of-N) with different style prompts to create
        diverse candidates.

        Args:
            action: The action to generate instructions for
            processor: The target processor
            context: Flow context for additional information
            n_candidates: Override default candidate count

        Returns:
            List of InstructionCandidate objects
        """
        n = n_candidates or self.n_candidates
        client = await self._get_client()

        # Select styles to use (cycle through if n > len(STYLES))
        styles_to_use = []
        for i in range(n):
            styles_to_use.append(STYLES[i % len(STYLES)])

        # Generate candidates concurrently
        tasks = []
        for style in styles_to_use:
            tasks.append(
                self._generate_single(
                    client=client,
                    style=style,
                    processor=processor,
                    context=context,
                    target_mark=action.target_mark,
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        candidates = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"Generation failed for style {styles_to_use[i]}: {result}")
                continue
            candidates.append(result)

        return candidates

    async def _generate_single(
        self,
        client,
        style: str,
        processor: Processor,
        context: FlowContext,
        target_mark: Optional[int],
    ) -> InstructionCandidate:
        """Generate a single instruction candidate."""
        from gaius.client.engine_client import Message

        # Get processor purpose from context or use default
        purpose = context.processor_purposes.get(
            processor.name, f"handles {processor.type} operations"
        )

        # Get prompts
        system_prompt, user_prompt = get_generation_prompt(
            style=style,
            processor_name=processor.name,
            processor_type=processor.type,
            position=(processor.position.get("x", 0), processor.position.get("y", 0)),
            flow_description=context.flow_description,
            processor_purpose=purpose,
        )

        # Call LLM
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

        result = await client.complete(
            messages=messages,
            technique="bon",  # Best-of-N sampling
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        # Extract instruction text (strip whitespace and quotes)
        text = result.content.strip().strip('"').strip("'")

        return InstructionCandidate(
            text=text,
            style=style,
            target_mark=target_mark,
            processor_name=processor.name,
        )

    async def generate_connection_candidates(
        self,
        source: Processor,
        dest: Processor,
        relationships: list[str],
        n_candidates: Optional[int] = None,
    ) -> list[InstructionCandidate]:
        """Generate instruction candidates for a connection action."""
        n = n_candidates or min(self.n_candidates, 3)  # Fewer styles for connections
        client = await self._get_client()

        from gaius.client.engine_client import Message

        styles_to_use = ["technical", "conversational", "brief"][:n]
        candidates = []

        for style in styles_to_use:
            try:
                system_prompt, user_prompt = get_connection_prompt(
                    style=style,
                    source_name=source.name,
                    dest_name=dest.name,
                    source_type=source.type,
                    dest_type=dest.type,
                    relationships=", ".join(relationships) if relationships else "success",
                )

                messages = [
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=user_prompt),
                ]

                result = await client.complete(
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )

                text = result.content.strip().strip('"').strip("'")
                candidates.append(InstructionCandidate(
                    text=text,
                    style=style,
                    processor_name=f"{source.name}->{dest.name}",
                ))
            except Exception as e:
                logger.warning(f"Connection instruction generation failed: {e}")

        return candidates

    async def generate_trajectory_candidates(
        self,
        trajectory: Trajectory,
        processors: list[Processor],
        context: FlowContext,
        n_candidates: Optional[int] = None,
    ) -> list[InstructionCandidate]:
        """Generate instruction candidates for a multi-step trajectory."""
        n = n_candidates or self.n_candidates
        client = await self._get_client()

        from gaius.client.engine_client import Message

        # Build step list
        step_names = []
        for step in trajectory.steps:
            if step.target_mark is not None:
                idx = step.target_mark - 1
                if 0 <= idx < len(processors):
                    step_names.append(processors[idx].name)

        if not step_names:
            step_names = [f"step {i+1}" for i in range(len(trajectory.steps))]

        # Generate with single detailed prompt for trajectories
        system_prompt, user_prompt = get_trajectory_prompt(
            steps=step_names,
            flow_name=context.flow_name,
            flow_description=context.flow_description,
        )

        candidates = []
        for i in range(n):
            try:
                messages = [
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=user_prompt),
                ]

                result = await client.complete(
                    messages=messages,
                    technique="bon",
                    temperature=self.temperature + 0.1 * i,  # Vary temperature slightly
                    max_tokens=self.max_tokens * 2,  # Allow longer for trajectories
                )

                text = result.content.strip().strip('"').strip("'")
                candidates.append(InstructionCandidate(
                    text=text,
                    style="trajectory",
                    processor_name=context.flow_name,
                ))
            except Exception as e:
                logger.warning(f"Trajectory instruction generation failed: {e}")

        return candidates


class InstructionPipeline:
    """Full pipeline for LLM-powered instruction generation.

    Combines:
    - LLMInstructionGenerator (BON generation)
    - InstructionValidator (alignment checking)
    - InstructionQualityScorer (rubric scoring)
    - CalibrationOrchestrator (XAI 6-dimension rubric, optional)

    Usage:
        pipeline = InstructionPipeline()
        instruction = await pipeline.generate_best_instruction(
            action=action,
            processor=processor,
            marks=marks,
            context=context,
        )

        # With XAI calibration
        pipeline = InstructionPipeline(enable_xai_calibration=True)
        # This will occasionally sample for XAI evaluation
    """

    def __init__(
        self,
        min_quality_score: float = 0.6,
        n_candidates: int = 5,
        enable_xai_calibration: bool = False,
        calibration_orchestrator: Optional["CalibrationOrchestrator"] = None,
    ):
        self.min_quality_score = min_quality_score
        self.generator = LLMInstructionGenerator(n_candidates=n_candidates)
        self.validator = None  # Lazy-loaded
        self.scorer = None  # Lazy-loaded
        self.enable_xai_calibration = enable_xai_calibration
        self._calibrator = calibration_orchestrator

    async def _get_validator(self):
        """Lazy-load validator."""
        if self.validator is None:
            from .validation import InstructionValidator
            self.validator = InstructionValidator()
        return self.validator

    async def _get_scorer(self):
        """Lazy-load scorer."""
        if self.scorer is None:
            from .quality import InstructionQualityScorer
            self.scorer = InstructionQualityScorer()
        return self.scorer

    async def _get_calibrator(self) -> Optional["CalibrationOrchestrator"]:
        """Lazy-load calibration orchestrator."""
        if not self.enable_xai_calibration:
            return None

        if self._calibrator is None:
            try:
                from .calibration import get_calibration_orchestrator
                self._calibrator = get_calibration_orchestrator()
            except Exception as e:
                logger.warning(f"Failed to initialize calibration orchestrator: {e}")
                return None

        return self._calibrator

    async def generate_best_instruction(
        self,
        action: Action,
        processor: Processor,
        marks: list[Mark],
        context: FlowContext,
    ) -> Optional[InstructionCandidate]:
        """Generate and select the best instruction for an action.

        Pipeline:
            1. Generate diverse candidates (BON)
            2. Validate alignment (filter misaligned)
            3. Score quality (rubric)
            4. Select best candidate

        Args:
            action: The action to generate instruction for
            processor: Target processor
            marks: All visible marks for alignment checking
            context: Flow context

        Returns:
            Best InstructionCandidate or None if all fail
        """
        # Stage 1: Generate candidates
        candidates = await self.generator.generate_candidates(
            action=action,
            processor=processor,
            context=context,
        )

        if not candidates:
            logger.warning("No candidates generated")
            return None

        # Stage 2: Validate alignment
        validator = await self._get_validator()
        elements = [{"id": m.id, "name": m.label, "type": m.type} for m in marks]

        aligned_candidates = []
        for candidate in candidates:
            try:
                result = await validator.check_alignment(
                    instruction=candidate.text,
                    elements=elements,
                    expected_mark=action.target_mark,
                )
                candidate.is_aligned = result.is_aligned
                candidate.alignment_score = 1.0 if result.confidence == "high" else 0.5 if result.confidence == "medium" else 0.0

                if result.is_aligned:
                    aligned_candidates.append(candidate)
                else:
                    logger.debug(f"Filtered misaligned: {candidate.text[:50]}...")
            except Exception as e:
                logger.warning(f"Alignment check failed: {e}")
                # Include candidate anyway if alignment check fails
                aligned_candidates.append(candidate)

        if not aligned_candidates:
            logger.warning("All candidates failed alignment, using original candidates")
            aligned_candidates = candidates

        # Stage 3: Score quality
        scorer = await self._get_scorer()
        for candidate in aligned_candidates:
            try:
                score = await scorer.score(
                    instruction=candidate.text,
                    target_name=processor.name,
                    target_type=processor.type,
                )
                candidate.quality_score = score.overall
                # Store breakdown for calibration
                candidate.clarity = score.clarity
                candidate.naturalness = score.naturalness
                candidate.specificity = score.specificity
                candidate.conciseness = score.conciseness
                candidate.processor_type = processor.type
            except Exception as e:
                logger.warning(f"Quality scoring failed: {e}")
                candidate.quality_score = 0.5  # Default middle score

        # Stage 4: Select best
        # Sort by: alignment confidence, then quality score
        aligned_candidates.sort(
            key=lambda c: (c.alignment_score or 0, c.quality_score or 0),
            reverse=True,
        )

        best = aligned_candidates[0]

        # Check minimum quality threshold
        if best.quality_score and best.quality_score < self.min_quality_score:
            logger.warning(
                f"Best candidate below quality threshold: {best.quality_score:.2f} < {self.min_quality_score}"
            )
            # Return anyway, but log the warning
            # In production, might want to regenerate or use fallback

        # Stage 5: Optional XAI calibration
        if self.enable_xai_calibration and best.quality_score is not None:
            await self._maybe_calibrate(best, marks)

        return best

    async def _maybe_calibrate(
        self,
        candidate: InstructionCandidate,
        marks: list[Mark],
    ) -> None:
        """Maybe run XAI calibration on the selected candidate.

        Uses inline calibration from CalibrationOrchestrator (5% sample
        or uncertainty band).
        """
        calibrator = await self._get_calibrator()
        if calibrator is None:
            return

        try:
            from .calibration import LocalScoreInput

            # Build LocalScoreInput from candidate
            local_input = LocalScoreInput(
                example_id=f"inline_{candidate.processor_name}_{candidate.style}",
                instruction=candidate.text,
                target_name=candidate.processor_name or "",
                target_type=candidate.processor_type or "",
                marks=[{"id": m.id, "name": m.label, "type": m.type} for m in marks],
                action_type="click",
                clarity=candidate.clarity or 0.5,
                naturalness=candidate.naturalness or 0.5,
                specificity=candidate.specificity or 0.5,
                conciseness=candidate.conciseness or 0.5,
                overall=candidate.quality_score or 0.5,
            )

            # Attempt inline calibration (may return None if not sampled or budget exceeded)
            result = await calibrator.maybe_calibrate_inline(local_input)

            if result:
                candidate.xai_score = result
                candidate.calibration_delta = (
                    result.weighted_reward - (candidate.quality_score or 0.5)
                )
                logger.info(
                    f"XAI calibration: local={candidate.quality_score:.2f}, "
                    f"xai={result.weighted_reward:.2f}, "
                    f"delta={candidate.calibration_delta:.2f}"
                )

        except Exception as e:
            logger.warning(f"Calibration failed: {e}")

    async def generate_trajectory_instruction(
        self,
        trajectory: Trajectory,
        processors: list[Processor],
        marks: list[Mark],
        context: FlowContext,
    ) -> Optional[InstructionCandidate]:
        """Generate instruction for a multi-step trajectory."""
        candidates = await self.generator.generate_trajectory_candidates(
            trajectory=trajectory,
            processors=processors,
            context=context,
        )

        if not candidates:
            return None

        # For trajectories, we skip alignment validation (too complex)
        # and just score quality
        scorer = await self._get_scorer()
        for candidate in candidates:
            try:
                score = await scorer.score(
                    instruction=candidate.text,
                    target_name=context.flow_name,
                    target_type="trajectory",
                )
                candidate.quality_score = score.overall
            except Exception as e:
                logger.warning(f"Quality scoring failed: {e}")
                candidate.quality_score = 0.5

        # Select best by quality
        candidates.sort(key=lambda c: c.quality_score or 0, reverse=True)
        return candidates[0]
