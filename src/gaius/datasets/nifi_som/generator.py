"""Main NiFi SoM/ToM dataset generator.

Supports two instruction generation modes:
- Template-based: Fast, deterministic, uses rule-based templates
- LLM-powered: Diverse, high-quality, uses optillm BON + validation + scoring

Optional XAI calibration using 6-dimension rubric:
- Inline: 5% sample during generation
- Batch: Strategic sampling post-processing
- Storage: Iceberg in S3 adjacent to dataset
"""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional, Union, TYPE_CHECKING

from .models import DatasetExample, TraceExample, Action, Trajectory, FlowStep
from .nifi_client import NiFiClient
from .annotator import SoMAnnotator, TrajectoryAnnotator
from .capture import NiFiScreenshotCapture, SELENIUM_AVAILABLE
from .instructions import InstructionGenerator
from .exporter import MagmaExporter

if TYPE_CHECKING:
    from .calibration import CalibrationOrchestrator, LocalScoreInput
    from .calibration_store import CalibrationStore, CalibrationItem

logger = logging.getLogger(__name__)


class LLMGenerationError(Exception):
    """LLM generation failed - includes remediation hints."""
    pass


class NiFiSoMGenerator:
    """Generate SoM/ToM-annotated NiFi screenshots from Metaflow flows.

    Supports two instruction generation modes:
    - use_llm=False: Template-based (default, fast)
    - use_llm=True: LLM-powered via optillm BON + validation + scoring

    Optional XAI calibration:
    - enable_calibration=True: Enable inline/batch calibration with 6-dim rubric
    - export_calibration=True: Export calibration history to Iceberg in S3
    """

    def __init__(
        self,
        nifi_url: str = "http://localhost:8450",
        output_dir: Path | None = None,
        storage_backend: str = "filesystem",
        dataset_id: str = "nifi-som-v1",
        dataset_version: str = "1.0.0",
        mode: str = "som",  # "som" or "tom"
        use_llm: bool = False,  # Enable LLM-powered instruction generation
        llm_candidates: int = 5,  # Number of LLM candidates to generate
        min_quality_score: float = 0.6,  # Minimum quality score threshold
        enable_calibration: bool = False,  # Enable XAI calibration
        calibration_sample_rate: float = 0.1,  # Sample rate for batch calibration
        export_calibration: bool = False,  # Export calibration to Iceberg
    ):
        self.nifi_url = nifi_url
        self.nifi = NiFiClient(nifi_url)
        self.annotator = SoMAnnotator()
        self.trajectory_annotator = TrajectoryAnnotator()
        self.instruction_gen = InstructionGenerator()
        self.output_dir = output_dir or Path(
            "build/dev/current/datasets/nifi-som-v1"
        )
        self.storage_backend = storage_backend
        self.dataset_id = dataset_id
        self.dataset_version = dataset_version
        self.mode = mode
        self.use_llm = use_llm
        self.llm_candidates = llm_candidates
        self.min_quality_score = min_quality_score
        self.enable_calibration = enable_calibration
        self.calibration_sample_rate = calibration_sample_rate
        self.export_calibration = export_calibration

        # LLM pipeline (lazy-loaded)
        self._llm_pipeline = None
        self._calibration_orchestrator = None
        self._calibration_store = None
        self._calibration_results = []

    async def _get_llm_pipeline(self):
        """Lazy-load the LLM instruction pipeline."""
        if self._llm_pipeline is None:
            from .llm_instructions import InstructionPipeline, FlowContext

            # If calibration enabled, pass orchestrator to pipeline
            calibrator = None
            if self.enable_calibration:
                calibrator = await self._get_calibration_orchestrator()

            self._llm_pipeline = InstructionPipeline(
                min_quality_score=self.min_quality_score,
                n_candidates=self.llm_candidates,
                enable_xai_calibration=self.enable_calibration,
                calibration_orchestrator=calibrator,
            )
        return self._llm_pipeline

    async def _get_calibration_orchestrator(self) -> Optional["CalibrationOrchestrator"]:
        """Lazy-load calibration orchestrator."""
        if not self.enable_calibration:
            return None

        if self._calibration_orchestrator is None:
            try:
                from .calibration import CalibrationOrchestrator, CalibrationConfig
                from ...models.tiered_evaluation import EvalBudget

                budget = EvalBudget()
                config = CalibrationConfig(
                    inline_sample_rate=self.calibration_sample_rate,
                )
                self._calibration_orchestrator = CalibrationOrchestrator(
                    budget=budget,
                    config=config,
                )
                logger.info("Initialized XAI calibration orchestrator")
            except Exception as e:
                logger.warning(f"Failed to initialize calibration: {e}")
                return None

        return self._calibration_orchestrator

    async def _get_calibration_store(self) -> Optional["CalibrationStore"]:
        """Lazy-load calibration store for Iceberg persistence."""
        if not self.export_calibration:
            return None

        if self._calibration_store is None:
            try:
                from .calibration_store import CalibrationStore
                self._calibration_store = CalibrationStore(dataset_id=self.dataset_id)
                logger.info(f"Initialized calibration store for {self.dataset_id}")
            except Exception as e:
                logger.warning(f"Failed to initialize calibration store: {e}")
                return None

        return self._calibration_store

    async def _generate_llm_instruction(
        self,
        action: Action,
        processor,
        marks: list,
        flow_name: str,
        flow_description: str = "processes data through multiple stages",
    ) -> tuple[str, dict]:
        """Generate instruction using LLM pipeline.

        Args:
            action: The action to generate instruction for
            processor: NiFi processor object
            marks: List of SoM marks
            flow_name: Name of the flow
            flow_description: Description of the flow

        Returns:
            Tuple of (instruction_text, metadata_dict)
            metadata_dict includes quality scores and calibration info if available

        Raises:
            LLMGenerationError: If LLM pipeline fails
        """
        try:
            from .llm_instructions import FlowContext

            pipeline = await self._get_llm_pipeline()
            context = FlowContext(
                flow_name=flow_name,
                flow_description=flow_description,
            )

            candidate = await pipeline.generate_best_instruction(
                action=action,
                processor=processor,
                marks=marks,
                context=context,
            )

            if candidate:
                logger.info(
                    f"LLM instruction (style={candidate.style}, "
                    f"quality={candidate.quality_score:.2f}): {candidate.text[:50]}..."
                )

                # Build metadata dict with quality scores
                metadata = {
                    "instruction_source": "llm",
                    "instruction_style": candidate.style,
                    "quality_overall": candidate.quality_score,
                    "quality_clarity": candidate.clarity,
                    "quality_naturalness": candidate.naturalness,
                    "quality_specificity": candidate.specificity,
                    "quality_conciseness": candidate.conciseness,
                    "processor_type": processor.type,
                }

                # Add calibration info if available
                if candidate.xai_score is not None:
                    metadata["calibration"] = {
                        "calibrated": True,
                        "xai_overall": candidate.xai_score.weighted_reward,
                        "calibration_delta": candidate.calibration_delta,
                        "xai_model": candidate.xai_score.evaluator_model,
                        "dimensions": {
                            dim.value: {
                                "score": score.score,
                                "normalized": score.normalized,
                                "evidence": score.evidence[:100] if score.evidence else "",
                            }
                            for dim, score in candidate.xai_score.dimension_scores.items()
                        },
                    }

                return candidate.text, metadata
            else:
                # No candidate returned - fail
                raise LLMGenerationError(
                    f"LLM pipeline returned no candidate for processor {processor.name}.\n"
                    "  Try: /health fix llm\n"
                    "  Or:  gaius-cli orchestrator start reasoning"
                )

        except LLMGenerationError:
            raise  # Re-raise
        except Exception as e:
            raise LLMGenerationError(
                f"LLM instruction generation failed for {processor.name}: {e}\n"
                "  Try: /health fix llm\n"
                "  Or:  gaius-cli orchestrator start reasoning"
            ) from e

    async def generate_from_flow(
        self,
        flow_name: str,
        steps: list[str],
        capture_screenshot: bool = True,
    ) -> list[Union[DatasetExample, TraceExample]]:
        """Generate dataset examples from a Metaflow flow definition.

        Args:
            flow_name: Name of the flow
            steps: List of step names in order
            capture_screenshot: Whether to capture actual screenshots

        Returns:
            List of dataset examples (SoM or ToM based on mode)
        """
        if self.mode == "tom":
            return await self._generate_tom_examples(
                flow_name, steps, capture_screenshot
            )
        else:
            return await self._generate_som_examples(
                flow_name, steps, capture_screenshot
            )

    async def _generate_som_examples(
        self,
        flow_name: str,
        steps: list[str],
        capture_screenshot: bool = True,
    ) -> list[DatasetExample | TraceExample]:
        """Generate Set-of-Mark examples (single image per example)."""
        # Sync flow to NiFi (creates process group with processors)
        pg_id = await self.nifi.sync_flow(flow_name, steps)

        # Get processor information
        processors = await self.nifi.get_processors(pg_id)

        # Screenshots are REQUIRED - no fallback to placeholders
        if not capture_screenshot:
            raise LLMGenerationError(
                "capture_screenshot=False is not supported. "
                "Screenshots are required for dataset generation."
            )
        if not SELENIUM_AVAILABLE:
            raise LLMGenerationError(
                "Selenium not available for screenshot capture.\n"
                "  Try: uv sync --extra dataset\n"
                "  Or:  pip install selenium"
            )

        # Capture screenshot
        async with NiFiScreenshotCapture(self.nifi_url) as capture:
            screenshot = await capture.capture_canvas(pg_id)

        # Annotate with SoM markers
        annotated_image, marks = self.annotator.annotate(
            screenshot, processors
        )

        examples = []

        # Generate examples for each processor (click actions)
        for i, proc in enumerate(processors):
            action = Action(
                type="click",
                coordinates=(
                    (proc.position["x"] + 75) / 1920,  # Normalized center
                    (proc.position["y"] + 25) / 1080,
                ),
                target_mark=i + 1,
                metadata={"processor_type": proc.type},
            )

            # Generate instruction using LLM or template
            if self.use_llm:
                instruction, llm_metadata = await self._generate_llm_instruction(
                    action=action,
                    processor=proc,
                    marks=marks,
                    flow_name=flow_name,
                )
            else:
                instruction = self.instruction_gen.generate_click_instruction(proc)
                llm_metadata = {"instruction_source": "template"}

            example = DatasetExample(
                id=f"{flow_name}_{proc.name}_{uuid.uuid4().hex[:8]}",
                image=annotated_image,
                marks=marks,
                instruction=instruction,
                actions=[action],
                flow_id=flow_name,
                metadata={
                    "process_group_id": pg_id,
                    "target_processor": proc.name,
                    "processor_type": proc.type,
                    **llm_metadata,  # Merge LLM/calibration metadata
                },
            )
            examples.append(example)

        return examples

    async def _generate_tom_examples(
        self,
        flow_name: str,
        steps: list[str],
        capture_screenshot: bool = True,
    ) -> list[DatasetExample | TraceExample]:
        """Generate Trace-of-Mark examples (multi-frame with trajectory)."""
        # Sync flow to NiFi
        pg_id = await self.nifi.sync_flow(flow_name, steps)
        processors = await self.nifi.get_processors(pg_id)

        # Screenshots are REQUIRED - no fallback to placeholders
        if not capture_screenshot:
            raise LLMGenerationError(
                "capture_screenshot=False is not supported. "
                "Screenshots are required for dataset generation."
            )
        if not SELENIUM_AVAILABLE:
            raise LLMGenerationError(
                "Selenium not available for screenshot capture.\n"
                "  Try: uv sync --extra dataset\n"
                "  Or:  pip install selenium"
            )

        async with NiFiScreenshotCapture(self.nifi_url) as capture:
            base_screenshot = await capture.capture_canvas(pg_id)

        # Get SoM marks
        _, marks = self.annotator.annotate(base_screenshot, processors)

        examples = []

        # Generate trajectory examples - workflows through multiple processors
        # Example 1: Click through first 3 processors in sequence
        if len(processors) >= 3:
            trajectory_actions = []
            for i, proc in enumerate(processors[:3]):
                action = Action(
                    type="click",
                    coordinates=(
                        (proc.position["x"] + 75) / 1920,
                        (proc.position["y"] + 25) / 1080,
                    ),
                    target_mark=i + 1,
                    metadata={"processor_type": proc.type, "step_in_sequence": i + 1},
                )
                trajectory_actions.append(action)

            trajectory = Trajectory(
                steps=trajectory_actions,
                description=f"Navigate through {', '.join(p.name for p in processors[:3])}",
            )

            # Generate frame sequence showing trajectory progression
            frames = self.trajectory_annotator.create_frame_sequence(
                base_screenshot, trajectory, self.annotator, processors
            )

            instruction = (
                f"Navigate the flow by clicking: "
                f"{processors[0].name} → {processors[1].name} → {processors[2].name}"
            )

            example = TraceExample(
                id=f"{flow_name}_trajectory_{uuid.uuid4().hex[:8]}",
                frames=frames,
                marks=marks,
                trajectory=trajectory,
                instruction=instruction,
                flow_id=flow_name,
                metadata={
                    "process_group_id": pg_id,
                    "trajectory_type": "sequential_navigation",
                },
            )
            examples.append(example)

        # Example 2: Full flow traversal (if small enough)
        if len(processors) <= 6:
            trajectory_actions = []
            for i, proc in enumerate(processors):
                action = Action(
                    type="click",
                    coordinates=(
                        (proc.position["x"] + 75) / 1920,
                        (proc.position["y"] + 25) / 1080,
                    ),
                    target_mark=i + 1,
                    metadata={"processor_type": proc.type},
                )
                trajectory_actions.append(action)

            trajectory = Trajectory(
                steps=trajectory_actions,
                description=f"Complete flow: {flow_name}",
            )

            frames = self.trajectory_annotator.create_frame_sequence(
                base_screenshot, trajectory, self.annotator, processors
            )

            instruction = f"Execute the complete {flow_name} workflow from start to end"

            example = TraceExample(
                id=f"{flow_name}_full_flow_{uuid.uuid4().hex[:8]}",
                frames=frames,
                marks=marks,
                trajectory=trajectory,
                instruction=instruction,
                flow_id=flow_name,
                metadata={
                    "process_group_id": pg_id,
                    "trajectory_type": "full_flow",
                },
            )
            examples.append(example)

        return examples

    async def generate_from_metaflow_db(
        self,
        db_url: str | None = None,
        limit: int = 10,
    ) -> list[DatasetExample]:
        """Generate examples from flows in the Metaflow database.

        Args:
            db_url: Metaflow database URL
            limit: Maximum number of flows to process

        Returns:
            List of dataset examples
        """
        # Resolve database URL from config if not provided
        if db_url is None:
            from gaius.core.config import get_database_url
            db_url = get_database_url()

        # Query flows from database
        flows = await self._query_metaflow_flows(db_url, limit)

        all_examples = []
        for flow in flows:
            examples = await self.generate_from_flow(
                flow["name"], flow["steps"]
            )
            all_examples.extend(examples)

        return all_examples

    async def _query_metaflow_flows(
        self, db_url: str, limit: int
    ) -> list[dict]:
        """Query flow definitions from Metaflow database.

        Returns list of {name, steps} dictionaries.
        """
        try:
            import asyncpg
        except ImportError:
            # Fall back to test data if asyncpg not available
            return self._get_test_flows()

        try:
            conn = await asyncpg.connect(db_url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT DISTINCT flow_id, step_name
                    FROM steps_v3
                    ORDER BY flow_id, step_name
                    LIMIT $1
                    """,
                    limit * 10,  # Get more rows to group by flow
                )

                # Group by flow
                flows = {}
                for row in rows:
                    flow_id = row["flow_id"]
                    if flow_id not in flows:
                        flows[flow_id] = {"name": flow_id, "steps": []}
                    flows[flow_id]["steps"].append(row["step_name"])

                return list(flows.values())[:limit]
            finally:
                await conn.close()
        except Exception:
            return self._get_test_flows()

    def _get_test_flows(self) -> list[dict]:
        """Get test flow definitions when database is unavailable."""
        return [
            {
                "name": "ArxivDoclingFlow",
                "steps": [
                    "start",
                    "fetch_pdf",
                    "convert_to_markdown",
                    "extract_topics",
                    "score_relevance",
                    "create_zettelkasten",
                    "archive_step",
                    "end",
                ],
            },
            {
                "name": "EmbeddingFlow",
                "steps": [
                    "start",
                    "load_documents",
                    "chunk_text",
                    "embed_chunks",
                    "store_vectors",
                    "end",
                ],
            },
        ]

    async def run(
        self,
        use_database: bool = False,
        flows: list[dict] | None = None,
        export: bool = True,
    ) -> list[DatasetExample]:
        """Run the full generation pipeline.

        Args:
            use_database: Whether to query Metaflow database
            flows: Optional list of flow definitions to use
            export: Whether to export results

        Returns:
            List of generated examples
        """
        # Screenshots are REQUIRED for dataset generation - no fallbacks
        if not SELENIUM_AVAILABLE:
            raise LLMGenerationError(
                "Selenium not available for screenshot capture.\n"
                "  Try: uv sync --extra dataset\n"
                "  Or:  pip install selenium"
            )

        if flows is None:
            if use_database:
                examples = await self.generate_from_metaflow_db()
            else:
                # Use test flows
                flows = self._get_test_flows()
                examples = []
                for flow in flows:
                    flow_examples = await self.generate_from_flow(
                        flow["name"],
                        flow["steps"],
                        capture_screenshot=True,
                    )
                    examples.extend(flow_examples)
        else:
            examples = []
            for flow in flows:
                flow_examples = await self.generate_from_flow(
                    flow["name"],
                    flow["steps"],
                    capture_screenshot=True,
                )
                examples.extend(flow_examples)

        # Optional batch calibration after generation
        if self.enable_calibration and examples:
            await self._run_batch_calibration(examples)

        if export and examples:
            exporter = MagmaExporter(
                self.output_dir,
                storage_backend=self.storage_backend,
                dataset_id=self.dataset_id,
                dataset_version=self.dataset_version,
            )
            # Cast to union type for exporter (list invariance workaround)
            export_examples: list[DatasetExample | TraceExample] = list(examples)
            exporter.export(export_examples)

        # Export calibration results to Iceberg if requested
        if self.export_calibration and self._calibration_results:
            await self._export_calibration_results()

        return examples

    async def _run_batch_calibration(self, examples: list[DatasetExample]) -> None:
        """Run batch calibration on generated examples."""
        orchestrator = await self._get_calibration_orchestrator()
        if orchestrator is None:
            return

        try:
            from .calibration import LocalScoreInput

            # Build LocalScoreInput list from examples
            local_inputs = []
            for example in examples:
                # Extract local scores from metadata if available
                metadata = example.metadata or {}
                local_inputs.append(LocalScoreInput(
                    example_id=example.id,
                    instruction=example.instruction,
                    target_name=metadata.get("target_processor", "unknown"),
                    target_type=metadata.get("processor_type", "unknown"),
                    marks=[{"id": m.id, "name": m.label, "type": m.type} for m in example.marks],
                    action_type="click",
                    clarity=metadata.get("quality_clarity", 0.5),
                    naturalness=metadata.get("quality_naturalness", 0.5),
                    specificity=metadata.get("quality_specificity", 0.5),
                    conciseness=metadata.get("quality_conciseness", 0.5),
                    overall=metadata.get("quality_overall", 0.5),
                ))

            # Run batch calibration
            results = await orchestrator.calibrate_batch(local_inputs)
            self._calibration_results.extend(results)

            logger.info(f"Batch calibration complete: {len(results)} samples")
            logger.info(f"Calibration status: {orchestrator.get_status()}")

        except Exception as e:
            logger.error(f"Batch calibration failed: {e}")

    async def _export_calibration_results(self) -> None:
        """Export calibration results to Iceberg."""
        store = await self._get_calibration_store()
        if store is None or not self._calibration_results:
            return

        try:
            from .calibration_store import CalibrationItem

            # Convert RubricScore to CalibrationItem
            items = []
            for result in self._calibration_results:
                # Find corresponding local input (we'd need to track this properly)
                item = CalibrationItem(
                    example_id=result.example_id,
                    dataset_id=self.dataset_id,
                    instruction="",  # Would need to be tracked
                    target_name="",
                    target_type="",
                    action_type="click",
                    # Local scores (placeholder - would need to be tracked)
                    local_clarity=0.5,
                    local_naturalness=0.5,
                    local_specificity=0.5,
                    local_conciseness=0.5,
                    local_overall=0.5,
                    # XAI scores from RubricScore
                    xai_intent=result.dimension_scores.get("intent", lambda: type("obj", (), {"score": 0})()).score if hasattr(result, "dimension_scores") else 0,
                    xai_som_grounding=0,
                    xai_action_semantics=0,
                    xai_tom_trace=4,
                    xai_constraints=0,
                    xai_outcome=0,
                    xai_overall=result.weighted_reward,
                    evidence_json="{}",
                    errors_json="{}",
                    calibration_delta=0.0,
                    xai_model=result.evaluator_model,
                    tokens_used=result.tokens_used,
                    evaluated_at=result.evaluated_at,
                )
                items.append(item)

            # Store to Iceberg
            write_result = store.store_samples(items)
            logger.info(
                f"Exported {write_result.items_written} calibration samples "
                f"to {write_result.table_path}"
            )

        except Exception as e:
            logger.error(f"Failed to export calibration results: {e}")


def _check_minio_available() -> bool:
    """Check if MinIO is available and configured."""
    try:
        from ..storage import DatasetStorage, MINIO_AVAILABLE
        if not MINIO_AVAILABLE:
            return False
        storage = DatasetStorage(backend="minio")
        client = storage._get_client()
        # Check bucket exists
        return client.bucket_exists(storage.bucket)
    except Exception:
        return False


async def main():
    """CLI entry point for dataset generation."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Generate NiFi SoM/ToM dataset"
    )
    parser.add_argument(
        "--nifi-url",
        default="http://localhost:8450",
        help="NiFi base URL",
    )
    parser.add_argument(
        "--output",
        default="build/dev/current/datasets/nifi-som-v1",
        help="Output directory (KB path for manifest when using minio)",
    )
    parser.add_argument(
        "--storage",
        choices=["filesystem", "minio"],
        default="minio",
        help="Storage backend: minio (S3, default) or filesystem (local, for testing)",
    )
    parser.add_argument(
        "--mode",
        choices=["som", "tom"],
        default="som",
        help="Generation mode: som (Set-of-Mark, single image) or tom (Trace-of-Mark, multi-frame)",
    )
    parser.add_argument(
        "--use-database",
        action="store_true",
        help="Query flows from Metaflow database",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate without exporting",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use LLM-powered instruction generation (requires optillm)",
    )
    parser.add_argument(
        "--llm-candidates",
        type=int,
        default=5,
        help="Number of LLM candidates to generate per action (default: 5)",
    )
    parser.add_argument(
        "--min-quality",
        type=float,
        default=0.6,
        help="Minimum quality score threshold for LLM instructions (default: 0.6)",
    )
    parser.add_argument(
        "--enable-calibration",
        action="store_true",
        help="Enable XAI calibration with 6-dimension rubric",
    )
    parser.add_argument(
        "--calibration-sample-rate",
        type=float,
        default=0.1,
        help="Sample rate for XAI calibration (default: 0.1 = 10%%)",
    )
    parser.add_argument(
        "--export-calibration",
        action="store_true",
        help="Export calibration history to Iceberg in S3",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    if args.verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(levelname)s: %(message)s",
        )

    # Validate storage backend before proceeding
    if args.storage == "minio" and not args.dry_run:
        if not _check_minio_available():
            print("ERROR: MinIO storage is not available.", file=sys.stderr)
            print("", file=sys.stderr)
            print("Options:", file=sys.stderr)
            print("  1. Start MinIO: devenv processes up", file=sys.stderr)
            print("  2. Use filesystem (testing only): --storage filesystem", file=sys.stderr)
            print("", file=sys.stderr)
            print("Dataset artifacts should be stored in S3, not the KB.", file=sys.stderr)
            sys.exit(1)

    # Adjust dataset ID based on mode
    dataset_id = f"nifi-{args.mode}-v1"

    generator = NiFiSoMGenerator(
        nifi_url=args.nifi_url,
        output_dir=Path(args.output),
        storage_backend=args.storage,
        dataset_id=dataset_id,
        mode=args.mode,
        use_llm=args.use_llm,
        llm_candidates=args.llm_candidates,
        min_quality_score=args.min_quality,
        enable_calibration=args.enable_calibration,
        calibration_sample_rate=args.calibration_sample_rate,
        export_calibration=args.export_calibration,
    )

    mode_name = "Trace-of-Mark" if args.mode == "tom" else "Set-of-Mark"
    inst_mode = "LLM-powered" if args.use_llm else "template-based"
    print(f"Generating NiFi {mode_name} dataset...")
    print(f"  NiFi URL: {args.nifi_url}")
    print(f"  Output: {args.output}")
    print(f"  Storage: {args.storage}")
    print(f"  Mode: {args.mode} ({mode_name})")
    print(f"  Instructions: {inst_mode}")
    if args.use_llm:
        print(f"    Candidates: {args.llm_candidates}")
        print(f"    Min quality: {args.min_quality}")
    if args.enable_calibration:
        print(f"  XAI Calibration: enabled")
        print(f"    Sample rate: {args.calibration_sample_rate}")
        print(f"    Export to Iceberg: {args.export_calibration}")
    print(f"  Selenium available: {SELENIUM_AVAILABLE}")

    examples = await generator.run(
        use_database=args.use_database,
        export=not args.dry_run,
    )

    # Count frames for ToM
    total_frames = 0
    if args.mode == "tom":
        for ex in examples:
            frames = getattr(ex, "frames", None)
            if frames is not None:
                total_frames += len(frames)

    print(f"\nGenerated {len(examples)} examples")
    if args.mode == "tom" and total_frames:
        print(f"Total frames: {total_frames}")

    if not args.dry_run:
        if args.storage == "minio":
            print(f"Manifest: {args.output}/manifest.json")
            print(f"Artifacts: s3://zndx-gaius/datasets/{dataset_id}/")
        else:
            print(f"Exported to: {args.output}/annotations.json")


if __name__ == "__main__":
    asyncio.run(main())
