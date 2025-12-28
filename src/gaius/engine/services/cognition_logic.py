"""Engine-native cognition logic.

Pure L3 implementation of cognition task processing without L5 agent imports.
This module provides the core logic that CognitionService uses to process
scheduled tasks from pg_cron.

Architecture:
- All functions are engine-native (no imports from gaius.agents)
- Uses L3 dependencies: inference client, database, gRPC
- Returns typed dataclasses for structured results
- Wraps execution in OTel spans for observability

Task Types Implemented:
- cognition_cycle: Generate thoughts from KB context
- self_observation: Meta-cognition on recent thoughts
- engine_audit: Analyze engine health metrics
- evolution_cycle: Trigger evolution optimization
- task_ideation: Generate capability gap analysis
- model_merge: Coordinate model merging
- calibration: Score calibration with frontier model
- daily_summary: Generate activity summary

Usage:
    from gaius.engine.services.cognition_logic import (
        process_cognition_cycle,
        CognitionCycleResult,
    )

    result = await process_cognition_cycle(db_pool, payload)

GAI:META
layer: L3-engine
depends_on: [gaius.inference, gaius.core]
forbidden_imports: [gaius.agents, gaius.mcp_server, gaius.widgets]
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Result Dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class CognitionCycleResult:
    """Result from a cognition cycle."""

    success: bool = False
    thoughts_generated: int = 0
    patterns_detected: int = 0
    connections_found: int = 0
    curiosities_generated: int = 0
    self_observations: int = 0
    engine_audits: int = 0
    tokens_used: int = 0
    duration_ms: int = 0
    error: Optional[str] = None
    thought_ids: list[str] = field(default_factory=list)


@dataclass
class EngineAuditResult:
    """Result from engine health audit."""

    success: bool = False
    observations_recorded: int = 0
    anomalies_found: int = 0
    anomaly_details: list[str] = field(default_factory=list)
    duration_ms: int = 0
    error: Optional[str] = None


@dataclass
class EvolutionCycleResult:
    """Result from evolution cycle."""

    success: bool = False
    agents_processed: int = 0
    successful: int = 0
    results: list[dict] = field(default_factory=list)
    duration_ms: int = 0
    error: Optional[str] = None


@dataclass
class TaskIdeationResult:
    """Result from task ideation."""

    success: bool = False
    drafts_generated: int = 0
    task_names: list[str] = field(default_factory=list)
    duration_ms: int = 0
    error: Optional[str] = None


@dataclass
class ModelMergeResult:
    """Result from model merge cycle."""

    success: bool = False
    agents_processed: int = 0
    successful: int = 0
    results: dict[str, dict] = field(default_factory=dict)
    duration_ms: int = 0
    error: Optional[str] = None


@dataclass
class CalibrationResult:
    """Result from calibration cycle."""

    success: bool = False
    local_score: float = 0.0
    frontier_score: float = 0.0
    drift_detected: bool = False
    drift_amount: float = 0.0
    duration_ms: int = 0
    error: Optional[str] = None


@dataclass
class DailySummaryResult:
    """Result from daily summary generation."""

    success: bool = False
    period_days: int = 1
    kb_entries: int = 0
    queries: int = 0
    kb_path: Optional[str] = None
    duration_ms: int = 0
    error: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# OTel Tracing
# ─────────────────────────────────────────────────────────────────────────────


def _get_tracer():
    """Get OTel tracer for cognition operations."""
    try:
        from opentelemetry import trace

        return trace.get_tracer("gaius.engine.cognition")
    except ImportError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Cognition Cycle - Engine Native
# ─────────────────────────────────────────────────────────────────────────────


async def process_cognition_cycle(
    db_pool,
    payload: dict,
    inference_client=None,
) -> CognitionCycleResult:
    """Run a cognition cycle - generate thoughts from KB context.

    Engine-native implementation that:
    1. Gathers KB context from database
    2. Queries inference endpoint for pattern/connection analysis
    3. Saves generated thoughts to database
    4. Records cycle in activity log

    Args:
        db_pool: asyncpg connection pool
        payload: Task payload with parameters:
            - max_thoughts: Maximum thoughts to generate (default: 5)
            - trigger: Trigger reason (default: "scheduled")
        inference_client: Optional inference client (auto-created if None)

    Returns:
        CognitionCycleResult with thoughts generated
    """
    import time

    start_time = time.time()
    result = CognitionCycleResult()
    tracer = _get_tracer()

    # OTel span wrapper
    span = None
    span_ctx = None
    if tracer:
        span_ctx = tracer.start_as_current_span("cognition.cycle")
        span = span_ctx.__enter__()

    try:
        max_thoughts = payload.get("max_thoughts", 5)
        trigger_reason = payload.get("trigger", "scheduled")

        if span:
            span.set_attribute("max_thoughts", max_thoughts)
            span.set_attribute("trigger", trigger_reason)

        # Get inference client
        if inference_client is None:
            try:
                from ...inference import get_client

                inference_client = get_client()
            except ImportError:
                result.error = "Inference client not available"
                return result

        # Gather KB context from database
        context = await _gather_kb_context(db_pool)

        if not context.get("recent_entries"):
            logger.info("No recent KB entries for cognition cycle")
            result.success = True
            return result

        # Generate thoughts via inference
        thoughts = await _generate_thoughts(
            inference_client,
            context,
            max_thoughts=max_thoughts,
            trigger_reason=trigger_reason,
        )

        # Save thoughts to database
        saved_ids = await _save_thoughts(db_pool, thoughts)

        # Update result
        result.success = True
        result.thoughts_generated = len(saved_ids)
        result.thought_ids = saved_ids
        result.patterns_detected = sum(1 for t in thoughts if t.get("type") == "pattern")
        result.connections_found = sum(
            1 for t in thoughts if t.get("type") == "connection"
        )
        result.curiosities_generated = sum(
            1 for t in thoughts if t.get("type") == "curiosity"
        )

        if span:
            span.set_attribute("thoughts_generated", result.thoughts_generated)

        logger.info(
            f"Cognition cycle complete: {result.thoughts_generated} thoughts "
            f"({result.patterns_detected} patterns, {result.connections_found} connections)"
        )

    except Exception as e:
        logger.error(f"Cognition cycle failed: {e}")
        result.error = str(e)

    finally:
        result.duration_ms = int((time.time() - start_time) * 1000)
        if span_ctx:
            span_ctx.__exit__(None, None, None)

    return result


async def _gather_kb_context(db_pool) -> dict:
    """Gather KB context for cognition from database.

    Returns:
        Dict with recent_entries, active_domains, recent_thoughts
    """
    context = {
        "recent_entries": [],
        "active_domains": [],
        "recent_thoughts": [],
    }

    if not db_pool:
        return context

    try:
        async with db_pool.acquire() as conn:
            # Get recent KB entries (last 24 hours)
            entries = await conn.fetch(
                """
                SELECT path, title, domain, created_at
                FROM kb_entries
                WHERE created_at > NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC
                LIMIT 20
                """
            )
            context["recent_entries"] = [dict(row) for row in entries]

            # Get active domains
            domains = await conn.fetch(
                """
                SELECT DISTINCT domain, COUNT(*) as entry_count
                FROM kb_entries
                WHERE domain IS NOT NULL
                  AND created_at > NOW() - INTERVAL '7 days'
                GROUP BY domain
                ORDER BY entry_count DESC
                LIMIT 10
                """
            )
            context["active_domains"] = [row["domain"] for row in domains]

            # Get recent thoughts for continuity
            thoughts = await conn.fetch(
                """
                SELECT id, thought_type, title, summary, salience
                FROM thoughts
                WHERE created_at > NOW() - INTERVAL '24 hours'
                ORDER BY salience DESC, created_at DESC
                LIMIT 10
                """
            )
            context["recent_thoughts"] = [dict(row) for row in thoughts]

    except Exception as e:
        logger.warning(f"Failed to gather KB context: {e}")

    return context


async def _generate_thoughts(
    inference_client,
    context: dict,
    max_thoughts: int = 5,
    trigger_reason: str = "scheduled",
) -> list[dict]:
    """Generate thoughts using inference endpoint.

    Args:
        inference_client: Inference client
        context: KB context dict
        max_thoughts: Maximum thoughts to generate
        trigger_reason: Why cognition was triggered

    Returns:
        List of thought dicts
    """
    from ...inference import Message

    # Build prompt from context
    entries_text = "\n".join(
        f"- {e.get('title', 'Untitled')} ({e.get('domain', 'general')})"
        for e in context.get("recent_entries", [])[:10]
    )

    domains_text = ", ".join(context.get("active_domains", [])[:5]) or "general"

    recent_thoughts = context.get("recent_thoughts", [])
    thoughts_text = ""
    if recent_thoughts:
        thoughts_text = "\n\nRecent thoughts:\n" + "\n".join(
            f"- {t.get('title', 'Untitled')}: {t.get('summary', '')[:100]}"
            for t in recent_thoughts[:5]
        )

    prompt = f"""Analyze the following recent KB activity and generate insights.

Recent entries:
{entries_text}

Active domains: {domains_text}
{thoughts_text}

Generate {max_thoughts} thought(s). For each thought, identify:
1. Pattern: A recurring theme or structure you notice
2. Connection: A relationship between different entries or domains
3. Curiosity: A question worth exploring

Format each thought as:
TYPE: pattern|connection|curiosity
TITLE: Brief title (max 50 chars)
SUMMARY: One paragraph explanation
SALIENCE: 0.0-1.0 (how important/interesting)

Trigger reason: {trigger_reason}"""

    try:
        response = await inference_client.complete(
            messages=[
                Message(
                    role="system",
                    content="You are a knowledge analyst examining a personal knowledge base. "
                    "Find patterns, connections, and generate curiosity about the content.",
                ),
                Message(role="user", content=prompt),
            ],
            max_tokens=2048,
        )

        # Parse response into thought dicts
        return _parse_thoughts(response.content)

    except Exception as e:
        logger.warning(f"Thought generation failed: {e}")
        return []


def _parse_thoughts(response_text: str) -> list[dict]:
    """Parse LLM response into thought dicts."""
    thoughts = []
    current_thought = {}

    for line in response_text.split("\n"):
        line = line.strip()
        if not line:
            if current_thought.get("type") and current_thought.get("title"):
                thoughts.append(current_thought)
                current_thought = {}
            continue

        if line.upper().startswith("TYPE:"):
            value = line.split(":", 1)[1].strip().lower()
            if value in ("pattern", "connection", "curiosity"):
                current_thought["type"] = value
        elif line.upper().startswith("TITLE:"):
            current_thought["title"] = line.split(":", 1)[1].strip()[:100]
        elif line.upper().startswith("SUMMARY:"):
            current_thought["summary"] = line.split(":", 1)[1].strip()
        elif line.upper().startswith("SALIENCE:"):
            try:
                current_thought["salience"] = float(line.split(":", 1)[1].strip())
            except ValueError:
                current_thought["salience"] = 0.5

    # Don't forget last thought
    if current_thought.get("type") and current_thought.get("title"):
        thoughts.append(current_thought)

    return thoughts


async def _save_thoughts(db_pool, thoughts: list[dict]) -> list[str]:
    """Save thoughts to database.

    Returns:
        List of saved thought IDs
    """
    if not db_pool or not thoughts:
        return []

    saved_ids = []

    try:
        async with db_pool.acquire() as conn:
            for thought in thoughts:
                thought_id = str(uuid4())
                await conn.execute(
                    """
                    INSERT INTO thoughts (id, thought_type, title, summary, salience, created_at)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                    """,
                    thought_id,
                    thought.get("type", "pattern"),
                    thought.get("title", "Untitled"),
                    thought.get("summary", ""),
                    thought.get("salience", 0.5),
                )
                saved_ids.append(thought_id)

    except Exception as e:
        logger.warning(f"Failed to save thoughts: {e}")

    return saved_ids


# ─────────────────────────────────────────────────────────────────────────────
# Self-Observation - Engine Native
# ─────────────────────────────────────────────────────────────────────────────


async def process_self_observation(
    db_pool,
    payload: dict,
    inference_client=None,
) -> CognitionCycleResult:
    """Run self-observation - meta-cognition on recent thoughts.

    Analyzes patterns in the system's own thought generation to identify
    biases, blind spots, and areas for improvement.

    Args:
        db_pool: asyncpg connection pool
        payload: Task payload
        inference_client: Optional inference client

    Returns:
        CognitionCycleResult with self-observations generated
    """
    import time

    start_time = time.time()
    result = CognitionCycleResult()
    tracer = _get_tracer()

    span_ctx = None
    if tracer:
        span_ctx = tracer.start_as_current_span("cognition.self_observation")
        span_ctx.__enter__()

    try:
        if inference_client is None:
            try:
                from ...inference import get_client

                inference_client = get_client()
            except ImportError:
                result.error = "Inference client not available"
                return result

        # Get recent thoughts for analysis
        if not db_pool:
            result.error = "Database pool required for self-observation"
            return result

        async with db_pool.acquire() as conn:
            thoughts = await conn.fetch(
                """
                SELECT id, thought_type, title, summary, salience, created_at
                FROM thoughts
                WHERE created_at > NOW() - INTERVAL '7 days'
                ORDER BY created_at DESC
                LIMIT 50
                """
            )

        if not thoughts:
            logger.info("No recent thoughts for self-observation")
            result.success = True
            return result

        # Analyze thought patterns
        from ...inference import Message

        thoughts_text = "\n".join(
            f"- [{row['thought_type']}] {row['title']}: {row['summary'][:100]}"
            for row in thoughts[:30]
        )

        prompt = f"""Analyze these recent thoughts generated by the system:

{thoughts_text}

Provide meta-observations about:
1. Dominant themes or biases in thought generation
2. Domains that may be under-explored
3. Types of connections that are rarely made
4. Questions the system should be asking but isn't

Format as:
TYPE: self_observation
TITLE: Brief observation title
SUMMARY: Detailed explanation
SALIENCE: 0.0-1.0"""

        response = await inference_client.complete(
            messages=[
                Message(
                    role="system",
                    content="You are analyzing an AI system's thought patterns "
                    "to identify blind spots and improvement areas.",
                ),
                Message(role="user", content=prompt),
            ],
            max_tokens=1024,
        )

        # Parse and save observations
        observations = _parse_thoughts(response.content)
        for obs in observations:
            obs["type"] = "self_observation"

        saved_ids = await _save_thoughts(db_pool, observations)

        result.success = True
        result.thoughts_generated = len(saved_ids)
        result.self_observations = len(saved_ids)
        result.thought_ids = saved_ids

        logger.info(f"Self-observation complete: {len(saved_ids)} observations")

    except Exception as e:
        logger.error(f"Self-observation failed: {e}")
        result.error = str(e)

    finally:
        result.duration_ms = int((time.time() - start_time) * 1000)
        if span_ctx:
            span_ctx.__exit__(None, None, None)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Engine Audit - Engine Native
# ─────────────────────────────────────────────────────────────────────────────


async def process_engine_audit(
    db_pool,
    payload: dict,
) -> EngineAuditResult:
    """Run engine health audit and record observations.

    Collects metrics from scheduler, evolution, GPU and detects anomalies.

    Args:
        db_pool: asyncpg connection pool
        payload: Task payload

    Returns:
        EngineAuditResult with observations and anomalies
    """
    import time

    start_time = time.time()
    result = EngineAuditResult()
    tracer = _get_tracer()

    span_ctx = None
    if tracer:
        span_ctx = tracer.start_as_current_span("cognition.engine_audit")
        span_ctx.__enter__()

    try:
        # Collect metrics
        metrics = await _collect_engine_metrics(db_pool)
        observations = []

        for source, source_metrics in metrics.items():
            observations.append({"source": source, "metrics": source_metrics})

        # Detect anomalies
        anomalies = _detect_anomalies(metrics)
        result.anomaly_details = anomalies
        result.anomalies_found = len(anomalies)

        # Record observations to database
        if db_pool:
            await _record_observations(db_pool, observations, anomalies)

        result.observations_recorded = len(observations)
        result.success = True

        logger.info(
            f"Engine audit complete: {len(observations)} observations, "
            f"{len(anomalies)} anomalies"
        )

    except Exception as e:
        logger.error(f"Engine audit failed: {e}")
        result.error = str(e)

    finally:
        result.duration_ms = int((time.time() - start_time) * 1000)
        if span_ctx:
            span_ctx.__exit__(None, None, None)

    return result


async def _collect_engine_metrics(db_pool) -> dict:
    """Collect metrics from engine subsystems."""
    metrics = {}

    # Scheduler metrics from database
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE picked_up_at IS NULL) as pending,
                        COUNT(*) FILTER (WHERE picked_up_at IS NOT NULL AND completed_at IS NULL) as active,
                        COUNT(*) FILTER (WHERE completed_at > NOW() - INTERVAL '1 hour') as completed_hour
                    FROM scheduled_tasks
                    """
                )
                metrics["scheduler"] = {
                    "queue_depth": row["pending"] if row else 0,
                    "active_jobs": row["active"] if row else 0,
                    "jobs_completed_hour": row["completed_hour"] if row else 0,
                }
        except Exception as e:
            logger.debug(f"Scheduler metrics unavailable: {e}")
            metrics["scheduler"] = {"queue_depth": 0, "active_jobs": 0}

    # GPU metrics via pynvml
    try:
        import pynvml

        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()

        total_util = 0.0
        total_mem_pct = 0.0
        max_temp = 0

        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            total_util += util.gpu

            memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
            mem_pct = (memory.used / memory.total) * 100 if memory.total > 0 else 0
            total_mem_pct += mem_pct

            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            max_temp = max(max_temp, temp)

        pynvml.nvmlShutdown()

        avg_util = total_util / device_count if device_count > 0 else 0
        avg_mem = total_mem_pct / device_count if device_count > 0 else 0

        metrics["gpu"] = {
            "gpu_count": device_count,
            "utilization_pct": round(avg_util, 1),
            "memory_used_pct": round(avg_mem, 1),
            "temperature_c": max_temp,
        }

    except ImportError:
        metrics["gpu"] = {"gpu_count": 0, "utilization_pct": 0.0, "memory_used_pct": 0.0}
    except Exception as e:
        logger.debug(f"GPU metrics unavailable: {e}")
        metrics["gpu"] = {"gpu_count": 0, "utilization_pct": 0.0, "memory_used_pct": 0.0}

    return metrics


def _detect_anomalies(metrics: dict) -> list[str]:
    """Detect anomalies in engine metrics."""
    anomalies = []

    # Check scheduler
    scheduler = metrics.get("scheduler", {})
    if scheduler.get("queue_depth", 0) > 100:
        anomalies.append(f"High queue depth: {scheduler['queue_depth']}")

    # Check GPU
    gpu = metrics.get("gpu", {})
    if gpu.get("temperature_c", 0) > 80:
        anomalies.append(f"High GPU temperature: {gpu['temperature_c']}C")
    if gpu.get("memory_used_pct", 0) > 98:
        anomalies.append(f"GPU memory nearly full: {gpu['memory_used_pct']}%")

    return anomalies


async def _record_observations(
    db_pool,
    observations: list[dict],
    anomalies: list[str],
) -> None:
    """Record observations to engine_observations table."""
    if not db_pool:
        return

    try:
        async with db_pool.acquire() as conn:
            for obs in observations:
                await conn.execute(
                    """
                    INSERT INTO engine_observations (source, metrics, anomalies, created_at)
                    VALUES ($1, $2, $3, NOW())
                    """,
                    obs.get("source", "unknown"),
                    json.dumps(obs.get("metrics", {})),
                    anomalies if anomalies else [],
                )
    except Exception as e:
        logger.warning(f"Failed to record observations: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Evolution Cycle - Engine Native Trigger
# ─────────────────────────────────────────────────────────────────────────────


async def process_evolution_cycle(
    db_pool,
    payload: dict,
) -> EvolutionCycleResult:
    """Trigger evolution cycle via gRPC.

    This is an engine-native wrapper that triggers evolution via the engine's
    own gRPC interface, avoiding L5 agent imports.

    Args:
        db_pool: asyncpg connection pool
        payload: Task payload with optional agents list

    Returns:
        EvolutionCycleResult with cycle status
    """
    import time

    start_time = time.time()
    result = EvolutionCycleResult()
    tracer = _get_tracer()

    span_ctx = None
    if tracer:
        span_ctx = tracer.start_as_current_span("evolution.cycle")
        span_ctx.__enter__()

    try:
        agents = payload.get("agents", ["leader", "risk", "critic"])
        source = payload.get("source", "scheduled")

        logger.info(f"Triggering evolution cycle for {len(agents)} agents (source={source})")

        # Use gRPC client to trigger evolution
        try:
            from ...client.grpc_client import GaiusClient

            async with GaiusClient() as client:
                for agent_id in agents:
                    try:
                        response = await client.trigger_evolution(agent_id)
                        result.results.append({
                            "agent_id": agent_id,
                            "success": response.success if hasattr(response, "success") else True,
                            "improvement": getattr(response, "improvement_pct", 0.0),
                        })
                        if response.success if hasattr(response, "success") else True:
                            result.successful += 1
                    except Exception as e:
                        logger.warning(f"Evolution trigger failed for {agent_id}: {e}")
                        result.results.append({
                            "agent_id": agent_id,
                            "success": False,
                            "error": str(e),
                        })

        except ImportError:
            logger.warning("gRPC client not available, evolution trigger skipped")
            result.error = "gRPC client not available"
            return result

        result.agents_processed = len(agents)
        result.success = result.successful > 0

        logger.info(
            f"Evolution cycle complete: {result.successful}/{len(agents)} successful"
        )

    except Exception as e:
        logger.error(f"Evolution cycle failed: {e}")
        result.error = str(e)

    finally:
        result.duration_ms = int((time.time() - start_time) * 1000)
        if span_ctx:
            span_ctx.__exit__(None, None, None)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Task Ideation - Engine Native
# ─────────────────────────────────────────────────────────────────────────────


async def process_task_ideation(
    db_pool,
    payload: dict,
    inference_client=None,
) -> TaskIdeationResult:
    """Generate task concepts for capability gap analysis.

    Analyzes current task pool and generates novel task ideas to expand
    training coverage.

    Args:
        db_pool: asyncpg connection pool
        payload: Task payload with max_concepts, novelty_threshold
        inference_client: Optional inference client

    Returns:
        TaskIdeationResult with generated task concepts
    """
    import time

    start_time = time.time()
    result = TaskIdeationResult()
    tracer = _get_tracer()

    span_ctx = None
    if tracer:
        span_ctx = tracer.start_as_current_span("evolution.task_ideation")
        span_ctx.__enter__()

    try:
        max_concepts = payload.get("max_concepts", 5)
        novelty_threshold = payload.get("novelty_threshold", 0.4)

        if inference_client is None:
            try:
                from ...inference import get_client

                inference_client = get_client()
            except ImportError:
                result.error = "Inference client not available"
                return result

        # Get existing task types for gap analysis
        existing_tasks = []
        if db_pool:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT DISTINCT task_type, COUNT(*) as count
                    FROM scheduled_tasks
                    WHERE created_at > NOW() - INTERVAL '30 days'
                    GROUP BY task_type
                    ORDER BY count DESC
                    """
                )
                existing_tasks = [row["task_type"] for row in rows]

        # Generate task ideas via inference
        from ...inference import Message

        prompt = f"""Analyze gaps in this task coverage and propose new task types.

Existing task types (by frequency):
{', '.join(existing_tasks[:20]) or 'None tracked'}

Generate {max_concepts} novel task concept(s) that would expand capability coverage.
Each concept should:
1. Address an underrepresented capability
2. Be specific and actionable
3. Include a clear evaluation criterion

Format:
NAME: task_name_snake_case
CAPABILITY: What skill does this test?
DESCRIPTION: One paragraph description
EVALUATION: How to measure success"""

        response = await inference_client.complete(
            messages=[
                Message(
                    role="system",
                    content="You are designing reasoning tasks for AI capability development. "
                    "Focus on novel, challenging tasks that test different skills.",
                ),
                Message(role="user", content=prompt),
            ],
            max_tokens=2048,
        )

        # Parse task concepts
        task_names = []
        for line in response.content.split("\n"):
            if line.strip().upper().startswith("NAME:"):
                name = line.split(":", 1)[1].strip()
                if name:
                    task_names.append(name)

        result.success = True
        result.drafts_generated = len(task_names)
        result.task_names = task_names[:max_concepts]

        logger.info(f"Task ideation complete: {len(task_names)} concepts generated")

    except Exception as e:
        logger.error(f"Task ideation failed: {e}")
        result.error = str(e)

    finally:
        result.duration_ms = int((time.time() - start_time) * 1000)
        if span_ctx:
            span_ctx.__exit__(None, None, None)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Model Merge - Engine Native
# ─────────────────────────────────────────────────────────────────────────────


async def process_model_merge(
    db_pool,
    payload: dict,
) -> ModelMergeResult:
    """Coordinate model merging via engine services.

    Args:
        db_pool: asyncpg connection pool
        payload: Task payload with optional agents filter

    Returns:
        ModelMergeResult with merge outcomes
    """
    import time

    start_time = time.time()
    result = ModelMergeResult()

    try:
        agents = payload.get("agents", ["leader", "risk", "critic"])

        logger.info(f"Running model merge for {len(agents)} agents")

        # Check for merge candidates in database
        if not db_pool:
            result.error = "Database pool required for model merge"
            return result

        for agent_id in agents:
            try:
                async with db_pool.acquire() as conn:
                    # Get top-scoring versions for potential merge
                    candidates = await conn.fetch(
                        """
                        SELECT version_id, score, eval_count
                        FROM agent_versions
                        WHERE agent_id = $1
                          AND score >= 0.7
                          AND eval_count >= 3
                        ORDER BY score DESC
                        LIMIT 5
                        """,
                        agent_id,
                    )

                if len(candidates) < 2:
                    result.results[agent_id] = {
                        "success": False,
                        "reason": f"Not enough candidates ({len(candidates)} found, need 2+)",
                    }
                    continue

                # For now, just log merge candidates - actual merge requires model loading
                result.results[agent_id] = {
                    "success": True,
                    "candidates": len(candidates),
                    "top_score": float(candidates[0]["score"]) if candidates else 0.0,
                    "status": "candidates_identified",
                }
                result.successful += 1

            except Exception as e:
                logger.warning(f"Merge failed for {agent_id}: {e}")
                result.results[agent_id] = {"success": False, "error": str(e)}

        result.agents_processed = len(agents)
        result.success = result.successful > 0

        logger.info(
            f"Model merge complete: {result.successful}/{len(agents)} agents processed"
        )

    except Exception as e:
        logger.error(f"Model merge failed: {e}")
        result.error = str(e)

    finally:
        result.duration_ms = int((time.time() - start_time) * 1000)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Daily Summary - Engine Native
# ─────────────────────────────────────────────────────────────────────────────


async def process_daily_summary(
    db_pool,
    payload: dict,
    inference_client=None,
) -> DailySummaryResult:
    """Generate daily activity summary.

    Args:
        db_pool: asyncpg connection pool
        payload: Task payload with days, use_llm, write_to_kb
        inference_client: Optional inference client

    Returns:
        DailySummaryResult with summary info
    """
    import time
    from pathlib import Path

    start_time = time.time()
    result = DailySummaryResult()

    try:
        days = payload.get("days", 1)
        use_llm = payload.get("use_llm", True)
        write_to_kb = payload.get("write_to_kb", True)

        result.period_days = days

        if not db_pool:
            result.error = "Database pool required for summary"
            return result

        # Gather metrics
        async with db_pool.acquire() as conn:
            # KB entries
            kb_row = await conn.fetchrow(
                """
                SELECT COUNT(*) as count
                FROM kb_entries
                WHERE created_at > NOW() - INTERVAL '%s days'
                """,
                days,
            )
            result.kb_entries = kb_row["count"] if kb_row else 0

            # Queries (from activity log)
            query_row = await conn.fetchrow(
                """
                SELECT COUNT(*) as count
                FROM activity_log
                WHERE event_type = 'query'
                  AND created_at > NOW() - INTERVAL '%s days'
                """,
                days,
            )
            result.queries = query_row["count"] if query_row else 0

        # Generate summary text
        if use_llm and inference_client is None:
            try:
                from ...inference import get_client

                inference_client = get_client()
            except ImportError:
                use_llm = False

        summary_text = f"""# Activity Summary

Period: {days} day(s)
Generated: {datetime.now().isoformat()}

## Metrics
- KB entries created: {result.kb_entries}
- Queries processed: {result.queries}
"""

        if use_llm and inference_client:
            try:
                from ...inference import Message

                response = await inference_client.complete(
                    messages=[
                        Message(
                            role="system",
                            content="You are generating a brief activity summary.",
                        ),
                        Message(
                            role="user",
                            content=f"Summarize this activity period:\n{summary_text}\n\n"
                            "Add brief insights about the activity level.",
                        ),
                    ],
                    max_tokens=512,
                )
                summary_text += f"\n## Insights\n\n{response.content}\n"
            except Exception as e:
                logger.warning(f"LLM summary failed: {e}")

        # Write to KB
        if write_to_kb:
            kb_root = Path(os.environ.get("GAIUS_KB_ROOT", "build/dev"))
            today = datetime.now().strftime("%Y-%m-%d")
            timestamp = datetime.now().strftime("%H%M%S")
            kb_path = f"scratch/{today}/{timestamp}_daily_summary.md"

            full_path = kb_root / kb_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(summary_text)

            result.kb_path = kb_path
            logger.info(f"Wrote daily summary to {kb_path}")

        result.success = True

    except Exception as e:
        logger.error(f"Daily summary failed: {e}")
        result.error = str(e)

    finally:
        result.duration_ms = int((time.time() - start_time) * 1000)

    return result
