"""NiFi SoM/ToM Dataset CLI - Thin gRPC Client.

This CLI is a thin client that submits jobs to the Gaius engine via gRPC.
All generation, calibration, and export happens in the engine.

Usage:
    # Generate dataset with default ArxivDoclingFlow (all steps)
    gaius-dataset submit

    # Generate with XAI calibration enabled
    gaius-dataset submit --calibration

    # Check job status
    gaius-dataset status dataset-1-abc12345

    # Query OpenLineage provenance
    gaius-dataset lineage nifi-som-v1

Design Principles:
- gRPC REQUIRED - all execution in engine, no local fallbacks
- Reasoning endpoint REQUIRED - LLM instruction generation is mandatory
- Fail-fast - errors include /health fix suggestions
- Progress streaming - real-time updates via server streaming
- OpenLineage tracking - full data provenance

Instruction Generation (--variants):
    Each action (click on a NiFi processor) gets multiple LLM-generated
    instruction candidates. The --variants parameter controls how many
    candidates are generated per action:

    --variants 1   : Single instruction (fastest, less diversity)
    --variants 3   : Three candidates, pick best (balanced)
    --variants 5   : Five candidates, pick best (default, high quality)
    --variants 10  : Ten candidates (highest quality, slower)

    Each candidate is scored on clarity, naturalness, specificity, and
    conciseness. The highest-scoring candidate is selected.

XAI Calibration (--calibration):
    Optional frontier model (xAI Grok) evaluation for quality assurance.
    When enabled, a sample of generated instructions are sent to xAI for
    independent scoring against a 6-dimension rubric:

    1. Intent Clarity     - Is the goal unambiguous?
    2. SoM Grounding      - Does it reference visual markers correctly?
    3. Action Semantics   - Is the action type appropriate?
    4. ToM Trace          - Does trajectory make sense? (ToM mode only)
    5. Constraints        - Are preconditions specified?
    6. Outcome            - Is expected result clear?

    Budget Management:
    - Daily limit: 100 xAI calls (configurable)
    - Weekly limit: 500 xAI calls
    - Sample rate: --calibration-rate (default 10%)
    - Tiered fallback: local model first, xAI for promotion decisions

    Use --export-calibration to persist calibration history to Iceberg
    for drift detection and model improvement tracking.
"""

import argparse
import asyncio
import logging
import sys
from typing import Optional

import grpc
from grpc import aio

logger = logging.getLogger(__name__)

# Default flow configuration - ArxivDoclingFlow with all steps
DEFAULT_FLOW = "ArxivDoclingFlow"
DEFAULT_STEPS = [
    "start",
    "fetch_pdf",
    "convert_to_markdown",
    "extract_topics",
    "score_relevance",
    "create_zettelkasten",
    "archive_step",
    "end",
]


async def _get_channel(host: str, port: int) -> aio.Channel:
    """Get gRPC channel to engine."""
    return aio.insecure_channel(f"{host}:{port}")


async def submit_job(
    flow_name: str,
    steps: list[str],
    mode: str = "som",
    dataset_id: str = "",
    variants: int = 5,
    min_quality: float = 0.6,
    enable_calibration: bool = False,
    calibration_sample_rate: float = 0.1,
    export_calibration: bool = False,
    storage: str = "rustfs",
    host: str = "localhost",
    port: int = 50051,
    stream_progress: bool = True,
) -> dict:
    """Submit a dataset generation job to the engine.

    Args:
        flow_name: Name of the Metaflow flow
        steps: List of step names
        mode: "som" or "tom"
        dataset_id: Dataset identifier (auto-generated if empty)
        variants: Number of LLM candidates per action
        min_quality: Minimum quality score threshold
        enable_calibration: Enable XAI calibration
        calibration_sample_rate: Sample rate for calibration
        export_calibration: Export calibration to Iceberg
        storage: Storage backend ("rustfs" or "filesystem")
        host: Engine host
        port: Engine gRPC port
        stream_progress: Whether to stream progress

    Returns:
        Job status dict
    """
    # Import generated proto messages
    from gaius.engine.generated import (
        DatasetGenerationRequest,
        GetDatasetJobRequest,
        DatasetProgressEvent,
        gaius_service_pb2_grpc,
    )

    # Generate dataset ID if not provided
    if not dataset_id:
        dataset_id = f"nifi-{mode}-v1"

    async with aio.insecure_channel(f"{host}:{port}") as channel:
        stub = gaius_service_pb2_grpc.GaiusServiceAsyncStub(channel)

        # Submit job
        request = DatasetGenerationRequest(
            flow_name=flow_name,
            steps=steps,
            mode=mode,
            dataset_id=dataset_id,
            variants_per_action=variants,
            min_quality_score=min_quality,
            enable_calibration=enable_calibration,
            calibration_sample_rate=calibration_sample_rate,
            export_calibration=export_calibration,
            storage_backend=storage,
        )

        try:
            response = await stub.SubmitDatasetJob(request)

            if response.status == "failed":
                print(f"ERROR: {response.error}", file=sys.stderr)
                return {"status": "failed", "error": response.error}

            print(f"Job submitted: {response.job_id}")
            print(f"  Status: {response.status}")
            print(f"  Phase: {response.current_phase}")

            # Stream progress if requested
            if stream_progress and response.status != "failed":
                await _stream_progress(stub, response.job_id)

            # Get final status
            final_response = await stub.GetDatasetJobStatus(
                GetDatasetJobRequest(job_id=response.job_id)
            )

            return {
                "job_id": final_response.job_id,
                "status": final_response.status,
                "total_examples": final_response.total_examples,
                "accepted_examples": final_response.accepted_examples,
                "rejected_examples": final_response.rejected_examples,
                "error": final_response.error,
            }

        except grpc.aio.AioRpcError as e:
            error_msg = e.details()
            print(f"ERROR: {error_msg}", file=sys.stderr)
            return {"status": "failed", "error": error_msg}


async def _stream_progress(stub, job_id: str) -> None:
    """Stream progress events for a job."""
    from gaius.engine.generated import GetDatasetJobRequest

    print("\nProgress:")
    try:
        async for event in stub.DatasetProgressStream(
            GetDatasetJobRequest(job_id=job_id)
        ):
            # Format event
            progress_pct = int(event.progress * 100)
            msg = event.message or event.phase
            print(f"  [{progress_pct:3d}%] {msg}")

            # Stop on terminal events
            if event.type in (10, 11):  # COMPLETED, FAILED
                break

    except grpc.aio.AioRpcError as e:
        if e.code() != grpc.StatusCode.CANCELLED:
            logger.warning(f"Progress stream error: {e}")


async def get_status(job_id: str, host: str = "localhost", port: int = 50051) -> dict:
    """Get status of a dataset generation job."""
    from gaius.engine.generated import (
        GetDatasetJobRequest,
        gaius_service_pb2_grpc,
    )

    async with aio.insecure_channel(f"{host}:{port}") as channel:
        stub = gaius_service_pb2_grpc.GaiusServiceAsyncStub(channel)

        try:
            response = await stub.GetDatasetJobStatus(
                GetDatasetJobRequest(job_id=job_id)
            )

            return {
                "job_id": response.job_id,
                "status": response.status,
                "progress": response.progress,
                "current_phase": response.current_phase,
                "total_examples": response.total_examples,
                "completed_examples": response.completed_examples,
                "accepted_examples": response.accepted_examples,
                "rejected_examples": response.rejected_examples,
                "error": response.error,
            }

        except grpc.aio.AioRpcError as e:
            return {"error": e.details()}


async def cancel_job(job_id: str, host: str = "localhost", port: int = 50051) -> dict:
    """Cancel a dataset generation job."""
    from gaius.engine.generated import (
        CancelDatasetJobRequest,
        gaius_service_pb2_grpc,
    )

    async with aio.insecure_channel(f"{host}:{port}") as channel:
        stub = gaius_service_pb2_grpc.GaiusServiceAsyncStub(channel)

        try:
            response = await stub.CancelDatasetJob(
                CancelDatasetJobRequest(job_id=job_id)
            )

            return {
                "job_id": response.job_id,
                "status": response.status,
            }

        except grpc.aio.AioRpcError as e:
            return {"error": e.details()}


async def get_lineage(
    dataset_id: str,
    host: str = "localhost",
    port: int = 50051,
) -> dict:
    """Get lineage information for a dataset."""
    from gaius.engine.generated import (
        DatasetLineageRequest,
        gaius_service_pb2_grpc,
    )

    async with aio.insecure_channel(f"{host}:{port}") as channel:
        stub = gaius_service_pb2_grpc.GaiusServiceAsyncStub(channel)

        try:
            response = await stub.GetDatasetLineage(
                DatasetLineageRequest(dataset_id=dataset_id)
            )

            return {
                "dataset_id": response.dataset_id,
                "total_examples": response.total_examples,
                "nodes": [
                    {
                        "id": n.id,
                        "type": n.type,
                        "namespace": n.namespace,
                        "name": n.name,
                    }
                    for n in response.nodes
                ],
                "edges": [
                    {
                        "type": e.type,
                        "from": e.from_id,
                        "to": e.to_id,
                    }
                    for e in response.edges
                ],
            }

        except grpc.aio.AioRpcError as e:
            return {"error": e.details()}


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="NiFi SoM/ToM Dataset Generation CLI (gRPC client)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate SoM dataset with defaults (ArxivDoclingFlow, all steps)
  gaius-dataset submit

  # Generate with more LLM candidates for higher quality
  gaius-dataset submit --variants 10

  # Generate with XAI calibration enabled
  gaius-dataset submit --calibration --calibration-rate 0.2

  # Generate ToM (trajectory) dataset
  gaius-dataset submit --mode tom

  # Check job status
  gaius-dataset status dataset-1-abc12345

  # Query OpenLineage provenance
  gaius-dataset lineage nifi-som-v1

  # Cancel a running job
  gaius-dataset cancel dataset-1-abc12345

Requirements:
  - gaius-engine must be running (gRPC on port 50051)
  - Reasoning endpoint must be available (vLLM or optillm)
  - NiFi must be running (port 8450)
  - Selenium/chromedriver for screenshot capture
""",
    )

    parser.add_argument(
        "--host",
        default="localhost",
        help="Engine gRPC host (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=50051,
        help="Engine gRPC port (default: 50051)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Submit command (primary)
    submit_parser = subparsers.add_parser(
        "submit",
        help="Submit a dataset generation job to the engine",
        description="""
Submit a dataset generation job to the Gaius engine via gRPC.

All execution happens in the engine - this CLI is a thin client.
The reasoning endpoint is REQUIRED for LLM instruction generation.
""",
    )
    submit_parser.add_argument(
        "--flow",
        default=DEFAULT_FLOW,
        help=f"Metaflow flow name (default: {DEFAULT_FLOW})",
    )
    submit_parser.add_argument(
        "--steps",
        nargs="+",
        default=DEFAULT_STEPS,
        help=f"Flow steps (default: all {len(DEFAULT_STEPS)} ArxivDoclingFlow steps)",
    )
    submit_parser.add_argument(
        "--mode",
        choices=["som", "tom"],
        default="som",
        help="Generation mode: som (single image) or tom (trajectory)",
    )
    submit_parser.add_argument(
        "--dataset-id",
        default="",
        help="Dataset ID (auto-generated if not specified)",
    )
    submit_parser.add_argument(
        "--variants",
        type=int,
        default=5,
        metavar="N",
        help="""Number of LLM instruction candidates per action (default: 5).
Higher values produce better quality but take longer.
1=fast, 3=balanced, 5=quality, 10=best""",
    )
    submit_parser.add_argument(
        "--min-quality",
        type=float,
        default=0.6,
        metavar="SCORE",
        help="Minimum quality score threshold 0.0-1.0 (default: 0.6)",
    )
    submit_parser.add_argument(
        "--calibration",
        action="store_true",
        help="""Enable XAI calibration (uses xAI Grok for quality assurance).
Budget: 100/day, 500/week. Use --calibration-rate to control sampling.""",
    )
    submit_parser.add_argument(
        "--calibration-rate",
        type=float,
        default=0.1,
        metavar="RATE",
        help="Fraction of examples to send to XAI (default: 0.1 = 10%%)",
    )
    submit_parser.add_argument(
        "--export-calibration",
        action="store_true",
        help="Export calibration history to Iceberg for drift detection",
    )
    submit_parser.add_argument(
        "--storage",
        choices=["rustfs", "filesystem"],
        default="rustfs",
        help="Storage backend (default: rustfs/S3)",
    )
    submit_parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Don't stream progress (submit and exit immediately)",
    )

    # Status command
    status_parser = subparsers.add_parser(
        "status",
        help="Get job status",
    )
    status_parser.add_argument(
        "job_id",
        help="Job ID to query",
    )

    # Cancel command
    cancel_parser = subparsers.add_parser(
        "cancel",
        help="Cancel a job",
    )
    cancel_parser.add_argument(
        "job_id",
        help="Job ID to cancel",
    )

    # Lineage command
    lineage_parser = subparsers.add_parser(
        "lineage",
        help="Get dataset lineage",
    )
    lineage_parser.add_argument(
        "dataset_id",
        help="Dataset ID to query",
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

    # Run command
    if args.command == "submit":
        # Print configuration summary
        print(f"Submitting dataset generation job...")
        print(f"  Flow: {args.flow}")
        print(f"  Steps: {len(args.steps)} ({args.steps[0]} -> ... -> {args.steps[-1]})")
        print(f"  Mode: {args.mode}")
        print(f"  Variants: {args.variants} LLM candidates per action")
        print(f"  Min quality: {args.min_quality}")
        if args.calibration:
            print(f"  XAI Calibration: enabled ({args.calibration_rate*100:.0f}% sample rate)")
        print(f"  Storage: {args.storage}")
        print()

        result = asyncio.run(
            submit_job(
                flow_name=args.flow,
                steps=args.steps,
                mode=args.mode,
                dataset_id=args.dataset_id,
                variants=args.variants,
                min_quality=args.min_quality,
                enable_calibration=args.calibration,
                calibration_sample_rate=args.calibration_rate,
                export_calibration=args.export_calibration,
                storage=args.storage,
                host=args.host,
                port=args.port,
                stream_progress=not args.no_stream,
            )
        )

        if result.get("status") == "completed":
            print(f"\n✓ Dataset generated: {result.get('accepted_examples', 0)} examples")
            sys.exit(0)
        else:
            print(f"\n✗ Generation failed: {result.get('error', 'unknown')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "status":
        result = asyncio.run(
            get_status(args.job_id, host=args.host, port=args.port)
        )

        # Check for RPC error (error without job_id) vs job error (has job_id)
        if "error" in result and result["error"] and "job_id" not in result:
            print(f"ERROR: {result['error']}", file=sys.stderr)
            sys.exit(1)

        print(f"Job: {result['job_id']}")
        print(f"  Status: {result['status']}")
        print(f"  Progress: {int(result.get('progress', 0) * 100)}%")
        print(f"  Phase: {result.get('current_phase', '-')}")
        print(f"  Examples: {result.get('accepted_examples', 0)} accepted, "
              f"{result.get('rejected_examples', 0)} rejected")

        if result.get("error"):
            print(f"  Error: {result['error']}")

    elif args.command == "cancel":
        result = asyncio.run(
            cancel_job(args.job_id, host=args.host, port=args.port)
        )

        if "error" in result:
            print(f"ERROR: {result['error']}", file=sys.stderr)
            sys.exit(1)

        print(f"Job {result['job_id']} status: {result['status']}")

    elif args.command == "lineage":
        result = asyncio.run(
            get_lineage(args.dataset_id, host=args.host, port=args.port)
        )

        if "error" in result:
            print(f"ERROR: {result['error']}", file=sys.stderr)
            sys.exit(1)

        print(f"Dataset: {result['dataset_id']}")
        print(f"Total examples: {result['total_examples']}")

        if result.get("nodes"):
            print("\nNodes:")
            for node in result["nodes"]:
                print(f"  [{node['type']}] {node['namespace']}:{node['name']}")

        if result.get("edges"):
            print("\nEdges:")
            for edge in result["edges"]:
                print(f"  {edge['from']} --{edge['type']}--> {edge['to']}")


if __name__ == "__main__":
    main()
