"""OTel heartbeat emission for long-running operations.

Provides async context manager for emitting periodic heartbeat events
within OTel spans. Heartbeats enable real-time progress monitoring
and anomaly detection without hard timeouts.

Key concepts:
- Heartbeat events: Periodic span events indicating operation is alive
- Progress events: Optional progress percentage updates
- Anomaly tracking: Integration with OperationBaseline for detection

Usage:
    from gaius.core.heartbeat import heartbeat_context

    async with heartbeat_context("gpu_allocation", interval_secs=10) as progress:
        result = await long_running_operation()
        progress.set_phase("loading_model")
        await another_step()
        if progress.anomaly_detected:
            logger.warning(f"Anomaly: Z={progress.z_score:.2f}")
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, TYPE_CHECKING

from opentelemetry import trace

from .operation_baseline import get_baseline_registry, OperationBaseline, OperationTypes
from .telemetry import get_tracer

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class OperationProgress:
    """Progress tracker for long-running operations.

    Provides mutable state for tracking operation progress and anomalies.
    Passed to code within the heartbeat context.

    Attributes:
        operation: Operation type identifier
        endpoint: Optional endpoint context
        start_time: Operation start timestamp
        phase: Current operation phase (for logging)
        progress_pct: Optional progress percentage (0-100)
        heartbeat_count: Number of heartbeats emitted
        anomaly_detected: Whether duration exceeds baseline threshold
        z_score: Current Z-score relative to baseline
        baseline: Reference to the OperationBaseline
    """

    operation: str
    endpoint: str = ""
    start_time: float = field(default_factory=time.time)
    phase: str = ""
    progress_pct: float = -1.0  # -1 means not set
    heartbeat_count: int = 0
    anomaly_detected: bool = False
    z_score: float = 0.0
    baseline: OperationBaseline | None = None

    @property
    def elapsed_seconds(self) -> float:
        """Time elapsed since operation start."""
        return time.time() - self.start_time

    def set_phase(self, phase: str) -> None:
        """Update the current operation phase."""
        self.phase = phase

    def set_progress(self, pct: float) -> None:
        """Update progress percentage (0-100)."""
        self.progress_pct = max(0.0, min(100.0, pct))


async def _emit_heartbeat(
    span: Any,
    progress: OperationProgress,
    metrics: Any | None = None,
) -> None:
    """Emit a heartbeat event on the span with meaningful metrics.

    Each heartbeat includes observability value beyond just "still alive":
    - Baseline statistics for comparison (mean, stddev, expected completion)
    - Z-score for anomaly assessment
    - Rate metrics (elapsed vs expected)
    - Phase/progress context

    Args:
        span: OTel span to add event to
        progress: Current progress state
        metrics: Optional EngineMetrics for recording
    """
    progress.heartbeat_count += 1
    elapsed = progress.elapsed_seconds

    # Build event attributes - always include meaningful metrics
    attrs: dict[str, Any] = {
        "heartbeat.sequence": progress.heartbeat_count,
        "heartbeat.operation": progress.operation,
        "heartbeat.elapsed_s": round(elapsed, 3),
    }

    if progress.endpoint:
        attrs["heartbeat.endpoint"] = progress.endpoint
    if progress.phase:
        attrs["heartbeat.phase"] = progress.phase
    if progress.progress_pct >= 0:
        attrs["heartbeat.progress_pct"] = round(progress.progress_pct, 1)

    # Always include baseline stats for observability value
    if progress.baseline:
        bl = progress.baseline
        attrs["heartbeat.baseline_count"] = bl.count
        attrs["heartbeat.baseline_mean_s"] = round(bl.mean, 3) if bl.count > 0 else 0.0
        attrs["heartbeat.baseline_stddev_s"] = round(bl.stddev, 3) if bl.count > 0 else 0.0

        if bl.count >= bl.min_samples:
            # Meaningful metrics: Z-score and expected completion ratio
            progress.z_score = bl.z_score(elapsed)
            progress.anomaly_detected = bl.is_anomaly(elapsed)
            attrs["heartbeat.z_score"] = round(progress.z_score, 2)
            attrs["heartbeat.anomaly"] = progress.anomaly_detected

            # Rate metric: how far along are we vs expected?
            if bl.mean > 0:
                attrs["heartbeat.elapsed_vs_mean_ratio"] = round(elapsed / bl.mean, 2)

            # Estimated time remaining (if we follow the baseline)
            if elapsed < bl.mean:
                attrs["heartbeat.eta_s"] = round(bl.mean - elapsed, 1)

            if progress.anomaly_detected:
                logger.warning(
                    f"Operation anomaly detected: operation={progress.operation} "
                    f"endpoint={progress.endpoint} elapsed={elapsed:.1f}s "
                    f"Z={progress.z_score:.2f} (threshold={bl.get_effective_threshold():.2f})"
                )
        else:
            # Cold start: indicate we're gathering baseline data
            attrs["heartbeat.baseline_warming"] = True
            attrs["heartbeat.samples_needed"] = bl.min_samples - bl.count

    # Emit span event
    if hasattr(span, "add_event"):
        span.add_event("heartbeat", attrs)

    # Record metric if available - check method exists before calling
    if metrics and hasattr(metrics, "record_heartbeat"):
        metrics.record_heartbeat(
            operation=progress.operation,
            endpoint=progress.endpoint,
            elapsed_s=elapsed,
        )

    logger.debug(
        f"Heartbeat #{progress.heartbeat_count}: operation={progress.operation} "
        f"elapsed={elapsed:.1f}s phase={progress.phase} "
        f"baseline_mean={progress.baseline.mean:.1f}s" if progress.baseline else ""
    )


async def _heartbeat_loop(
    span: Any,
    progress: OperationProgress,
    interval_secs: float,
    stop_event: asyncio.Event,
    metrics: Any | None = None,
) -> None:
    """Background task that emits heartbeats at regular intervals.

    Args:
        span: OTel span to add events to
        progress: Progress tracker
        interval_secs: Seconds between heartbeats
        stop_event: Event to signal shutdown
        metrics: Optional EngineMetrics
    """
    try:
        while not stop_event.is_set():
            await asyncio.sleep(interval_secs)
            if stop_event.is_set():
                break
            await _emit_heartbeat(span, progress, metrics)
    except asyncio.CancelledError:
        pass  # Normal shutdown


@asynccontextmanager
async def heartbeat_context(
    operation: str,
    interval_secs: float = 5.0,
    span: Any = None,
    endpoint: str = "",
    baseline: OperationBaseline | None = None,
    update_baseline: bool = True,
) -> AsyncIterator[OperationProgress]:
    """Emit periodic heartbeat events within current span.

    Creates a background task that emits heartbeat span events at the
    specified interval. Integrates with OperationBaseline for anomaly
    detection.

    Args:
        operation: Operation type identifier (e.g., "gpu_allocation")
        interval_secs: Seconds between heartbeat events (default 5.0)
        span: OTel span to add events to (uses current if None)
        endpoint: Optional endpoint context for baseline lookup
        baseline: Pre-fetched baseline (fetches from registry if None)
        update_baseline: Whether to update baseline on completion

    Yields:
        OperationProgress tracker for accessing/updating progress state

    Example:
        async with heartbeat_context("gpu_allocation", interval_secs=10) as progress:
            progress.set_phase("requesting")
            result = await allocate_gpu()
            progress.set_phase("loading")
            await load_model()
            progress.set_progress(50.0)
    """
    # Get or create span
    if span is None:
        span = trace.get_current_span()

    # Get or create baseline
    if baseline is None:
        registry = get_baseline_registry()
        baseline = registry.get_or_create(operation, endpoint=endpoint)

    # Create progress tracker
    progress = OperationProgress(
        operation=operation,
        endpoint=endpoint,
        baseline=baseline,
    )

    # Get metrics instance (optional)
    metrics = None
    try:
        from gaius.engine.metrics import EngineMetrics
        metrics = EngineMetrics.get_instance()
    except ImportError:
        pass

    # Emit initial heartbeat
    await _emit_heartbeat(span, progress, metrics)

    # Start background heartbeat task
    stop_event = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(span, progress, interval_secs, stop_event, metrics)
    )

    try:
        yield progress
    finally:
        # Stop heartbeat task
        stop_event.set()
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

        # Record duration to baseline
        elapsed = progress.elapsed_seconds
        if update_baseline and baseline is not None:
            baseline.update(elapsed)

        # Emit final completion event
        if hasattr(span, "add_event"):
            span.add_event(
                "heartbeat.completed",
                {
                    "heartbeat.operation": operation,
                    "heartbeat.endpoint": endpoint,
                    "heartbeat.elapsed_s": round(elapsed, 3),
                    "heartbeat.total_heartbeats": progress.heartbeat_count,
                    "heartbeat.final_z_score": round(progress.z_score, 2) if progress.baseline else 0,
                },
            )

        logger.debug(
            f"Operation completed: operation={operation} endpoint={endpoint} "
            f"elapsed={elapsed:.1f}s heartbeats={progress.heartbeat_count}"
        )


def emit_otel_progress(
    pct: float,
    phase: str = "",
    message: str = "",
    span: Any = None,
) -> None:
    """Emit a progress event to the current OTel span.

    Convenience function for emitting progress without full heartbeat context.
    Used for bridging PostgreSQL progress events to OTel.

    Args:
        pct: Progress percentage (0-100)
        phase: Current phase name
        message: Optional progress message
        span: OTel span (uses current if None)
    """
    if span is None:
        span = trace.get_current_span()

    if span is None or not hasattr(span, "add_event"):
        return

    attrs: dict[str, Any] = {
        "progress.pct": round(pct, 1),
    }
    if phase:
        attrs["progress.phase"] = phase
    if message:
        attrs["progress.message"] = message

    span.add_event("progress", attrs)


# Re-export for convenience
__all__ = [
    "heartbeat_context",
    "OperationProgress",
    "emit_otel_progress",
    "OperationTypes",
]
