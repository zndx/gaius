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
depends_on: [gaius.client, gaius.core]
forbidden_imports: [gaius.agents, gaius.mcp_server, gaius.widgets]
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4
from gaius.core.budgets import REASONING_MAX_TOKENS

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
    tokens_out: int = 0  # Output tokens from LLM thought generation
    duration_ms: int = 0
    error: Optional[str] = None
    thought_ids: list[str] = field(default_factory=list)
    kb_path: Optional[str] = None  # Zettelkasten file where thoughts were saved


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
# Proto-Typed Response Parsing
# Engine Federation Architecture: Tight coupling to proto schema for early drift detection
# ─────────────────────────────────────────────────────────────────────────────

from ..proto_types import CompleteResponseDTO, ProtoParseError


def _validate_complete_response(response: dict, context: str) -> tuple[str, int]:
    """Parse CompleteResponse into typed DTO, failing openly on schema drift.

    Engine Federation Architecture:
    This function uses CompleteResponseDTO for type-safe parsing. Field mismatches
    are detected at:
    1. Type checking time (ty/mypy) - IDE catches .text vs .content
    2. Parse time - ProtoParseError if required fields missing
    3. Runtime - accessing dto.text is explicit, not dict.get() with fallbacks

    Args:
        response: Dict from gRPC CompleteResponse (via MessageToDict)
        context: Description of where this response came from (for diagnostics)

    Returns:
        Tuple of (text_content, tokens_used) extracted from response

    Guru Codes:
        #PROTO.00000001.PARSEFAIL - Required field missing (strict mode)
        #COG.00000011.SCHEMADRIFT - Deprecated field names (lenient mode)
    """
    tracer = _get_tracer()

    try:
        # Try strict parsing first - this catches schema drift at parse time
        dto = CompleteResponseDTO.from_proto_dict(response)
        return dto.text, dto.tokens_used

    except ProtoParseError as e:
        # Schema drift detected - fail openly with OTel tracing
        logger.error(
            f"Proto schema mismatch (#{e.__class__.__name__}) in {context}: "
            f"Missing field '{e.field}'. Actual fields: {e.actual_fields}. "
            f"Falling back to lenient parsing. Guru: #PROTO.00000001.PARSEFAIL"
        )

        # Record in OTel span for alerting
        if tracer:
            try:
                from opentelemetry import trace

                span = trace.get_current_span()
                if span and span.is_recording():
                    span.add_event(
                        "proto_parse_error",
                        attributes={
                            "guru_code": "PROTO.00000001.PARSEFAIL",
                            "context": context,
                            "missing_field": e.field,
                            "actual_fields": str(e.actual_fields),
                            "message_type": e.message_type,
                        },
                    )
                    span.set_attribute("schema.drift_detected", True)
            except Exception as otel_err:
                logger.debug(f"Failed to record proto error in OTel: {otel_err}")

        # Fall back to lenient parsing (handles backwards compat)
        dto = CompleteResponseDTO.from_proto_dict_lenient(response, context)
        return dto.text, dto.tokens_used


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

        logger.info(f"Starting cognition cycle: max_thoughts={max_thoughts}, trigger={trigger_reason}")
        logger.info(f"db_pool available: {db_pool is not None}")

        if span:
            span.set_attribute("max_thoughts", max_thoughts)
            span.set_attribute("trigger", trigger_reason)

        # Get inference client
        if inference_client is None:
            try:
                from gaius.client import get_grpc_client

                inference_client = await get_grpc_client()
                logger.info(f"Inference client obtained: {type(inference_client).__name__}")
            except ImportError as e:
                logger.error(f"Failed to import inference client: {e}")
                result.error = "Inference client not available"
                return result

        # Gather KB context from database
        context = await _gather_kb_context(db_pool)
        logger.info(f"KB context gathered: {len(context.get('recent_entries', []))} entries, {len(context.get('active_domains', []))} domains, {len(context.get('recent_thoughts', []))} recent thoughts")

        if not context.get("recent_entries"):
            logger.info("No recent KB entries for cognition cycle")
            result.success = True
            return result

        # Generate thoughts via inference
        thoughts, tokens_out = await _generate_thoughts(
            inference_client,
            context,
            max_thoughts=max_thoughts,
            trigger_reason=trigger_reason,
        )

        # Save thoughts to database and zettelkasten
        saved_ids, kb_path = await _save_thoughts(db_pool, thoughts)

        # Update result
        result.success = True
        result.thoughts_generated = len(saved_ids)
        result.thought_ids = saved_ids
        result.kb_path = kb_path
        result.tokens_out = tokens_out
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
        import traceback
        logger.error(f"Cognition cycle failed: {e}")
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        result.error = str(e)

    finally:
        result.duration_ms = int((time.time() - start_time) * 1000)
        if span_ctx:
            span_ctx.__exit__(None, None, None)

    return result


async def _gather_kb_context(db_pool) -> dict:
    """Gather KB context for cognition from database.

    Uses content_items (RSS feed content) and activity_events (KB creates)
    as the source of recent content. The non-existent kb_entries table
    was a design concept that never materialized.

    Returns:
        Dict with recent_entries, active_domains, recent_thoughts
    """
    context = {
        "recent_entries": [],
        "active_domains": [],
        "recent_thoughts": [],
    }

    if not db_pool:
        raise RuntimeError(
            "Cognition cycle requires database connection but db_pool is None.\n"
            "Guru Meditation: #COG.00000019.NODBPOOL\n"
            "Check: Engine startup logs for database initialization"
        )

    try:
        async with db_pool.acquire() as conn:
            logger.debug("DB connection acquired for _gather_kb_context")
            # Get recent content items (RSS/feed content)
            # These have title, kb_path, and source info
            content_entries = await conn.fetch(
                """
                SELECT
                    ci.kb_path as path,
                    ci.title,
                    fs.name as domain,
                    ci.fetched_at as created_at
                FROM content_items ci
                LEFT JOIN feed_sources fs ON ci.source_id = fs.id
                WHERE ci.fetched_at > NOW() - INTERVAL '24 hours'
                  AND ci.kb_path IS NOT NULL
                ORDER BY ci.fetched_at DESC
                LIMIT 15
                """
            )

            # Get recent KB creates from activity log
            kb_creates = await conn.fetch(
                """
                SELECT
                    details->>'path' as path,
                    COALESCE(
                        details->>'title',
                        SPLIT_PART(details->>'path', '/', -1)
                    ) as title,
                    domain,
                    created_at
                FROM activity_events
                WHERE event_type = 'kb_create'
                  AND created_at > NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC
                LIMIT 5
                """
            )

            # Combine both sources
            all_entries = [dict(row) for row in content_entries]
            all_entries.extend([dict(row) for row in kb_creates])
            # Sort by created_at descending
            all_entries.sort(
                key=lambda e: e.get("created_at") or e.get("fetched_at", ""),
                reverse=True
            )
            context["recent_entries"] = all_entries[:20]

            # Get active domains from feed sources with recent content
            domains = await conn.fetch(
                """
                SELECT fs.name as domain, COUNT(*) as entry_count
                FROM content_items ci
                JOIN feed_sources fs ON ci.source_id = fs.id
                WHERE ci.fetched_at > NOW() - INTERVAL '7 days'
                GROUP BY fs.name
                ORDER BY entry_count DESC
                LIMIT 10
                """
            )
            context["active_domains"] = [row["domain"] for row in domains]

            # Get recent thoughts for continuity (correct table name)
            thoughts = await conn.fetch(
                """
                SELECT id, thought_type, title, summary, salience
                FROM cognition_thoughts
                WHERE created_at > NOW() - INTERVAL '24 hours'
                  AND status = 'active'
                ORDER BY salience DESC, created_at DESC
                LIMIT 10
                """
            )
            context["recent_thoughts"] = [dict(row) for row in thoughts]

    except Exception as e:
        # FAIL-FAST: a context-gather failure is a DB problem, not an empty
        # KB — degrading to "no recent entries" made DB faults look like
        # honest quiet and short-circuited the cycle as success.
        raise RuntimeError(
            f"Failed to gather KB context: {e}\n"
            "  Guru: #COG.00000036.CTXGATHER\n"
            "  Try: /health fix postgres"
        ) from e

    return context


async def _generate_thoughts(
    inference_client,
    context: dict,
    max_thoughts: int = 5,
    trigger_reason: str = "scheduled",
) -> tuple[list[dict], int]:
    """Generate thoughts using inference endpoint.

    Args:
        inference_client: Inference client
        context: KB context dict
        max_thoughts: Maximum thoughts to generate
        trigger_reason: Why cognition was triggered

    Returns:
        Tuple of (list of thought dicts, output tokens used)
    """
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
            f"- {t.get('title', 'Untitled')}: {(t.get('summary') or '')[:100]}"
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
        logger.info(f"Generating thoughts with prompt length: {len(prompt)}")
        logger.debug(f"Cognition prompt:\n{prompt[:500]}...")

        response = await inference_client.call(
            service="Scheduler",
            action="complete",
            params={
                "prompt": prompt,
                "system_prompt": "You are a knowledge analyst examining a personal knowledge base. "
                    "Find patterns, connections, and generate curiosity about the content.",
                "agent": "thinking",
                # xhigh thinking at ~8 tok/s regularly ate a 2048 budget
                # entirely inside <think> (no answer text, 2026-08-31);
                # 4096 was eaten too (2026-09-02 THINKBURN — third
                # starvation of the day; traces run longer post-rebuild).
                # 8192 gives the answer room; the client deadline scales.
                "max_tokens": REASONING_MAX_TOKENS,
            },
        )

        # Validate and extract response fields with schema drift detection
        response_content, tokens_out = _validate_complete_response(
            response, context="_generate_thoughts"
        )
        logger.info(f"LLM response length: {len(response_content)}, tokens_out: {tokens_out}")
        if response_content:
            # Log first 500 chars to help debug parsing issues
            logger.info(f"LLM response preview:\n{response_content[:500]}...")
        else:
            # FAIL-FAST: an empty answer after real token spend means the
            # thinking budget swallowed the completion — parsing "" into
            # zero thoughts would be another silent success-with-nothing.
            raise RuntimeError(
                f"Thinking consumed the budget with no answer text "
                f"(tokens_out={tokens_out}).\n"
                "  Guru: #COG.00000037.THINKBURN\n"
                "  Raise max_tokens for this call — xhigh reasoning needs headroom."
            )

        # Parse response into thought dicts
        thoughts = _parse_thoughts(response_content)
        logger.info(f"Parsed {len(thoughts)} thoughts from response")

        return thoughts, tokens_out

    except Exception as e:
        # FAIL-FAST: generation is the cycle's entire purpose — a failure
        # here must surface as a failed cycle, never as success-with-zero.
        # (The old fail-open `return [], 0` masked a 30s-deadline timeout
        # as 16 days of "successful" empty cycles, 2026-08-15..31.)
        logger.error(f"Thought generation failed (#COG.00000010.LLMPATTERN): {e}")

        # Record error in OTel span if available
        tracer = _get_tracer()
        if tracer:
            try:
                from opentelemetry import trace
                from opentelemetry.trace import Status, StatusCode

                span = trace.get_current_span()
                if span and span.is_recording():
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.set_attribute("error.type", type(e).__name__)
                    span.set_attribute("error.message", str(e))
                    span.set_attribute("guru_code", "COG.00000010.LLMPATTERN")
            except Exception as otel_err:
                logger.debug(f"Failed to record error in OTel span: {otel_err}")

        raise


def _parse_thoughts(response_text: str) -> list[dict]:
    """Parse LLM response into thought dicts with adaptive format detection.

    Supports multiple LLM output formats:
    - Strict format: TYPE: / TITLE: / SUMMARY: / SALIENCE:
    - Numbered lists: 1. TYPE: / 2. TITLE: etc.
    - Markdown: **TYPE:** / ### TITLE: etc.
    - JSON array of thought objects

    Uses dynamic programming approach: try fast strict parsing first,
    fall back to format detection and transformation.
    """
    import re

    if not response_text or not response_text.strip():
        logger.warning("Empty response text provided to parser")
        return []

    # Log full response for debugging
    logger.info(f"Parser input ({len(response_text)} chars):\n{response_text[:1000]}{'...' if len(response_text) > 1000 else ''}")

    # Phase 1: Try strict parsing (fastest path)
    thoughts = _parse_thoughts_strict(response_text)
    if thoughts:
        logger.debug(f"Strict parsing succeeded: {len(thoughts)} thoughts")
        return thoughts

    # Phase 2: Detect format and apply transformer
    format_type = _detect_response_format(response_text)
    logger.info(f"Detected LLM response format: {format_type}")

    if format_type == "json":
        thoughts = _parse_thoughts_json(response_text)
    elif format_type == "numbered":
        thoughts = _parse_thoughts_numbered(response_text)
    elif format_type == "markdown":
        thoughts = _parse_thoughts_markdown(response_text)
    elif format_type == "prose":
        thoughts = _parse_thoughts_prose(response_text)
    else:
        # Unknown format - log for analysis
        logger.warning(
            f"Unknown LLM response format. First 300 chars:\n{response_text[:300]}"
        )
        thoughts = []

    if not thoughts:
        # Log detailed format mismatch for heuristic collection
        logger.warning(
            f"#COG.00000020.LLMPATTERN - Format mismatch. "
            f"Detected: {format_type}, response length: {len(response_text)}"
        )

    return thoughts


def _parse_thoughts_strict(response_text: str) -> list[dict]:
    """Parse strict TYPE:/TITLE:/SUMMARY:/SALIENCE: format.

    Handles:
    - Leading/trailing whitespace on lines
    - TYPE values containing pipes (e.g., 'pattern|connection') - takes first valid value
    - Multi-line SUMMARY (concatenates until next field or blank line)
    """
    thoughts = []
    current_thought = {}
    collecting_summary = False
    summary_lines = []

    def _extract_type(value: str) -> str | None:
        """Extract first valid type from value (handles 'pattern|connection|curiosity')."""
        value = value.lower().strip()
        valid_types = ("pattern", "connection", "curiosity", "self_observation")
        # Check for pipe-separated values
        if "|" in value:
            for part in value.split("|"):
                part = part.strip()
                if part in valid_types:
                    return part
        # Check direct match
        if value in valid_types:
            return value
        return None

    for line in response_text.split("\n"):
        line = line.strip()

        # Check if we hit a new field - this ends summary collection
        is_field_line = any(line.upper().startswith(f) for f in ("TYPE:", "TITLE:", "SUMMARY:", "SALIENCE:"))

        if collecting_summary and (is_field_line or not line):
            # Save collected summary
            if summary_lines:
                current_thought["summary"] = " ".join(summary_lines)
                summary_lines = []
            collecting_summary = False

        if not line:
            if current_thought.get("type") and current_thought.get("title"):
                thoughts.append(current_thought)
                current_thought = {}
            continue

        if line.upper().startswith("TYPE:"):
            value = line.split(":", 1)[1].strip()
            extracted_type = _extract_type(value)
            if extracted_type:
                current_thought["type"] = extracted_type
        elif line.upper().startswith("TITLE:"):
            current_thought["title"] = line.split(":", 1)[1].strip()[:100]
        elif line.upper().startswith("SUMMARY:"):
            # Start collecting summary (may span multiple lines)
            first_line = line.split(":", 1)[1].strip()
            if first_line:
                summary_lines = [first_line]
            else:
                summary_lines = []
            collecting_summary = True
        elif line.upper().startswith("SALIENCE:"):
            try:
                value = line.split(":", 1)[1].strip()
                # Handle "0.8" or just "8" (normalize to 0-1)
                salience = float(value)
                if salience > 1.0:
                    salience = salience / 10.0  # Normalize if > 1
                current_thought["salience"] = min(1.0, max(0.0, salience))
            except ValueError:
                current_thought["salience"] = 0.5
        elif collecting_summary:
            # Continue collecting multi-line summary
            summary_lines.append(line)

    # Handle any remaining summary
    if summary_lines:
        current_thought["summary"] = " ".join(summary_lines)

    # Don't forget last thought
    if current_thought.get("type") and current_thought.get("title"):
        thoughts.append(current_thought)

    return thoughts


def _detect_response_format(response_text: str) -> str:
    """Detect the format of LLM response using pattern matching."""
    import re

    text = response_text.strip()

    # Check for JSON
    if text.startswith("[") or text.startswith("{"):
        try:
            json.loads(text)
            return "json"
        except json.JSONDecodeError:
            pass

    # Check for numbered list format: "1. TYPE:" or "1) TYPE:" or "1. Pattern:"
    if re.search(r"^\d+[\.\)]\s*(?:TYPE|Type|type|Pattern|Connection|Curiosity|Observation):", text, re.MULTILINE):
        return "numbered"

    # Check for markdown format: "**TYPE:**" or "### Type:" or "- **Type:**"
    if re.search(r"(?:\*\*|###?\s*|^-\s*\*\*)\s*(?:TYPE|Type|type):", text, re.MULTILINE):
        return "markdown"

    # Check for strict format (may have been malformed)
    if re.search(r"^(?:TYPE|Type|type)\s*:", text, re.MULTILINE):
        return "strict"

    # Prose format - contains thought-like content without structured fields
    if any(word in text.lower() for word in ["pattern", "connection", "curiosity", "observation"]):
        return "prose"

    return "unknown"


def _parse_thoughts_json(response_text: str) -> list[dict]:
    """Parse JSON-formatted thought response."""
    import re

    text = response_text.strip()

    # Extract JSON from possible markdown code block
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if json_match:
        text = json_match.group(1).strip()

    try:
        data = json.loads(text)

        # Handle array of thoughts
        if isinstance(data, list):
            thoughts = []
            for item in data:
                thought = _normalize_thought_dict(item)
                if thought:
                    thoughts.append(thought)
            return thoughts

        # Handle single thought object
        if isinstance(data, dict):
            thought = _normalize_thought_dict(data)
            return [thought] if thought else []

    except json.JSONDecodeError as e:
        logger.debug(f"JSON parsing failed: {e}")

    return []


def _normalize_thought_dict(item: dict) -> dict | None:
    """Normalize a thought dict from various key formats."""
    if not isinstance(item, dict):
        return None

    # Map various key names to canonical form
    type_keys = ["type", "TYPE", "Type", "thought_type", "category"]
    title_keys = ["title", "TITLE", "Title", "name"]
    summary_keys = ["summary", "SUMMARY", "Summary", "description", "content"]
    salience_keys = ["salience", "SALIENCE", "Salience", "importance", "score"]

    thought = {}

    for key in type_keys:
        if key in item:
            value = str(item[key]).lower()
            if value in ("pattern", "connection", "curiosity", "self_observation"):
                thought["type"] = value
                break

    for key in title_keys:
        if key in item:
            thought["title"] = str(item[key])[:100]
            break

    for key in summary_keys:
        if key in item:
            thought["summary"] = str(item[key])
            break

    for key in salience_keys:
        if key in item:
            try:
                thought["salience"] = float(item[key])
            except (ValueError, TypeError):
                thought["salience"] = 0.5
            break

    if thought.get("type") and thought.get("title"):
        thought.setdefault("salience", 0.5)
        thought.setdefault("summary", "")
        return thought

    return None


def _parse_thoughts_numbered(response_text: str) -> list[dict]:
    """Parse numbered list format.

    Handles multiple variations:
    - "1. TYPE: pattern\\n   TITLE: ..." (explicit fields)
    - "1. Pattern: Emphasis on..." (type-as-header format)
    - "1. title\\n   Connection: description" (inline type label)
    """
    import re

    thoughts = []
    current_thought = {}
    collecting_content = False
    content_lines = []

    # Type keywords that can appear as labels
    type_keywords = ("pattern", "connection", "curiosity", "observation", "self_observation")

    def _finish_thought():
        nonlocal current_thought, content_lines, collecting_content
        if content_lines:
            current_thought["summary"] = " ".join(content_lines)
            content_lines = []
        if current_thought.get("type") and current_thought.get("title"):
            thoughts.append(current_thought)
        current_thought = {}
        collecting_content = False

    for line in response_text.split("\n"):
        line = line.strip()

        # Empty line can end a thought
        if not line:
            _finish_thought()
            continue

        # Check for numbered entry: "1. " or "1) " or "- "
        num_match = re.match(r"^([\d]+[\.\)]|\-)\s*(.*)$", line)
        if num_match:
            # Save previous thought if any
            _finish_thought()

            rest = num_match.group(2)

            # Check for type-as-header format: "1. Pattern: Title goes here"
            type_header_match = re.match(r"^(Pattern|Connection|Curiosity|Observation):\s*(.*)$", rest, re.IGNORECASE)
            if type_header_match:
                thought_type = type_header_match.group(1).lower()
                if thought_type == "observation":
                    thought_type = "self_observation"
                current_thought["type"] = thought_type
                current_thought["title"] = type_header_match.group(2)[:100]
                collecting_content = True
                continue

            # Check for explicit TYPE: field
            if rest.upper().startswith("TYPE:"):
                value = rest.split(":", 1)[1].strip().lower()
                if value in type_keywords:
                    current_thought["type"] = value
                continue

            # Otherwise it might be just a title
            current_thought["title"] = rest[:100]
            collecting_content = True
            continue

        # Non-numbered continuation line
        cleaned = line

        # Check for explicit field markers
        if cleaned.upper().startswith("TYPE:"):
            value = cleaned.split(":", 1)[1].strip().lower()
            if value in type_keywords:
                current_thought["type"] = value
        elif cleaned.upper().startswith("TITLE:"):
            current_thought["title"] = cleaned.split(":", 1)[1].strip()[:100]
        elif cleaned.upper().startswith("SUMMARY:"):
            current_thought["summary"] = cleaned.split(":", 1)[1].strip()
        elif cleaned.upper().startswith("SALIENCE:"):
            try:
                current_thought["salience"] = float(cleaned.split(":", 1)[1].strip())
            except ValueError:
                current_thought["salience"] = 0.5
        elif cleaned.upper().startswith("CONNECTION:"):
            # Inline type label - this is content with type embedded
            if not current_thought.get("type"):
                current_thought["type"] = "connection"
            content_lines.append(cleaned.split(":", 1)[1].strip())
        elif cleaned.upper().startswith("CURIOSITY:"):
            if not current_thought.get("type"):
                current_thought["type"] = "curiosity"
            content_lines.append(cleaned.split(":", 1)[1].strip())
        elif collecting_content:
            # Collect as summary content
            content_lines.append(cleaned)

    # Don't forget the last thought
    _finish_thought()

    return thoughts


def _parse_thoughts_markdown(response_text: str) -> list[dict]:
    """Parse markdown-formatted thoughts like '**TYPE:** pattern'."""
    import re

    thoughts = []
    current_thought = {}

    for line in response_text.split("\n"):
        line = line.strip()
        if not line:
            if current_thought.get("type") and current_thought.get("title"):
                thoughts.append(current_thought)
                current_thought = {}
            continue

        # Strip markdown formatting: **, *, ###, -
        cleaned = re.sub(r"\*\*|\*|^#+\s*|^[-*]\s*", "", line)

        # Try strict parsing on cleaned line
        if cleaned.upper().startswith("TYPE:"):
            value = cleaned.split(":", 1)[1].strip().lower()
            if value in ("pattern", "connection", "curiosity", "self_observation"):
                current_thought["type"] = value
        elif cleaned.upper().startswith("TITLE:"):
            current_thought["title"] = cleaned.split(":", 1)[1].strip()[:100]
        elif cleaned.upper().startswith("SUMMARY:"):
            current_thought["summary"] = cleaned.split(":", 1)[1].strip()
        elif cleaned.upper().startswith("SALIENCE:"):
            try:
                current_thought["salience"] = float(cleaned.split(":", 1)[1].strip())
            except ValueError:
                current_thought["salience"] = 0.5

    if current_thought.get("type") and current_thought.get("title"):
        thoughts.append(current_thought)

    return thoughts


def _parse_thoughts_prose(response_text: str) -> list[dict]:
    """Extract thoughts from prose/natural language response.

    This is a best-effort fallback that tries to identify thought-like
    content from unstructured text. Less reliable than structured formats.
    """
    import re

    thoughts = []

    # Look for paragraph-like blocks that mention thought types
    paragraphs = re.split(r"\n\n+", response_text)

    for para in paragraphs:
        para = para.strip()
        if len(para) < 20:
            continue

        thought = {}
        para_lower = para.lower()

        # Detect type from content
        if "pattern" in para_lower:
            thought["type"] = "pattern"
        elif "connection" in para_lower:
            thought["type"] = "connection"
        elif "curious" in para_lower or "question" in para_lower:
            thought["type"] = "curiosity"
        else:
            continue

        # First sentence as title
        sentences = re.split(r"[.!?]", para)
        if sentences:
            thought["title"] = sentences[0].strip()[:100]

        # Rest as summary
        thought["summary"] = para
        thought["salience"] = 0.5

        if thought.get("title"):
            thoughts.append(thought)

    return thoughts


async def _save_thoughts(db_pool, thoughts: list[dict]) -> tuple[list[str], str | None]:
    """Save thoughts to database and a single zettelkasten file per cycle.

    All thoughts from a single cognition cycle are saved to one zettelkasten
    note to avoid cluttering the scratch directory with many small files.

    Returns:
        Tuple of (list of saved thought IDs, kb_path to zettelkasten file)
    """
    if not db_pool or not thoughts:
        return [], None

    saved_ids = []

    # First save all thoughts to the zettelkasten (one file for all)
    kb_path = _save_thoughts_as_zettel(thoughts)

    try:
        async with db_pool.acquire() as conn:
            for thought in thoughts:
                thought_id = str(uuid4())
                thought_type = thought.get("type", "pattern")
                title = thought.get("title", "Untitled")
                # content is NOT NULL, summary is optional
                # Parser puts main text in "summary" key, which maps to "content" column
                content = thought.get("summary") or thought.get("content") or thought.get("title", "No content")
                salience = thought.get("salience", 0.5)

                # Save to database with shared kb_path
                await conn.execute(
                    """
                    INSERT INTO cognition_thoughts (id, thought_type, title, content, salience, created_at, note_path)
                    VALUES ($1, $2, $3, $4, $5, NOW(), $6)
                    """,
                    thought_id,
                    thought_type,
                    title,
                    content,
                    salience,
                    kb_path,  # All thoughts in this cycle share the same note
                )

                saved_ids.append(thought_id)

    except Exception as e:
        raise RuntimeError(
            f"Failed to save thoughts to database: {e}\n"
            "Guru Meditation: #COG.00000001.DBSAVE\n"
            "Check: /health postgres"
        ) from e

    return saved_ids, kb_path


def _save_thoughts_as_zettel(thoughts: list[dict]) -> str | None:
    """Save all thoughts from a cognition cycle as a single zettelkasten note.

    Creates one note per cognition cycle containing all generated thoughts,
    with bidirectional prev/next linking to previous cognition cycles.

    Returns:
        Relative path to created note, or None if save failed
    """
    if not thoughts:
        return None

    try:
        from gaius.core.project_notes import find_previous_project_note, _update_next_link

        kb_root = Path(os.environ.get("GAIUS_KB_ROOT", "build/dev"))
        note_type = "thoughts_cycle"

        # Find previous cognition cycle note
        prev_note = find_previous_project_note(kb_root, note_type)

        # Create today's scratch directory
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H%M%S")
        scratch_dir = kb_root / "scratch" / date_str
        scratch_dir.mkdir(parents=True, exist_ok=True)

        # Build prev: link
        prev_link = ""
        if prev_note:
            try:
                prev_rel = prev_note.relative_to(kb_root)
                prev_link = f"[[{prev_rel}]]"
            except ValueError:
                prev_link = f"[[{prev_note.stem}]]"

        # Count thought types
        type_counts = {}
        for t in thoughts:
            ttype = t.get("type", "pattern")
            type_counts[ttype] = type_counts.get(ttype, 0) + 1
        type_summary = ", ".join(f"{v} {k}" for k, v in sorted(type_counts.items()))

        # Build note content with all thoughts
        note_lines = [
            "[[current/agents/cognition]]",
            f"prev: {prev_link}",
            "next:",
            "",
            f"# Cognition Cycle - {now.strftime('%H:%M:%S')}",
            "",
            "---",
            f"created: {now.isoformat()}",
            f"thoughts: {len(thoughts)}",
            f"types: {type_summary}",
            "---",
            "",
        ]

        # Add each thought as a section
        for i, thought in enumerate(thoughts, 1):
            thought_type = thought.get("type", "pattern")
            title = thought.get("title", "Untitled")
            content = thought.get("summary") or thought.get("content") or thought.get("title", "No content")
            salience = thought.get("salience", 0.5)

            note_lines.extend([
                f"## {i}. {title}",
                "",
                f"**Type:** {thought_type} | **Salience:** {salience:.2f}",
                "",
                content,
                "",
            ])

        note_lines.extend([
            "---",
            "",
            "*This note is part of the knowledge base. Edit, link, or dismiss as you wish.*",
        ])

        note_content = "\n".join(note_lines)

        # Write the note
        note_path = scratch_dir / f"{time_str}_{note_type}.md"
        note_path.write_text(note_content)

        # Update previous note's next: field
        if prev_note and prev_note.exists():
            _update_next_link(prev_note, kb_root, note_path)

        rel_path = str(note_path.relative_to(kb_root))
        logger.info(f"Saved {len(thoughts)} thoughts to zettelkasten: {rel_path}")
        return rel_path

    except Exception as e:
        logger.warning(
            f"Failed to save thoughts as zettelkasten note: {e}\n"
            "Guru Meditation: #COG.00000015.KBWRITE\n"
            "Check: KB scratch directory is writable"
        )
        return None


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
                from gaius.client import get_grpc_client

                inference_client = await get_grpc_client()
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

        response = await inference_client.call(
            service="Scheduler",
            action="complete",
            params={
                "prompt": prompt,
                "system_prompt": "You are analyzing an AI system's thought patterns "
                    "to identify blind spots and improvement areas.",
                "agent": "thinking",
                "max_tokens": REASONING_MAX_TOKENS,
            },
        )

        # Validate and extract response fields with schema drift detection
        response_content, _ = _validate_complete_response(
            response, context="process_self_observation"
        )
        observations = _parse_thoughts(response_content)
        for obs in observations:
            obs["type"] = "self_observation"

        saved_ids, kb_path = await _save_thoughts(db_pool, observations)

        result.success = True
        result.thoughts_generated = len(saved_ids)
        result.self_observations = len(saved_ids)
        result.thought_ids = saved_ids
        result.kb_path = kb_path

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
                        # Use call() dispatch instead of direct method
                        response = await client.call(
                            "Evolution", "trigger", {"agent_id": agent_id}
                        )
                        success = response.get("success", True)
                        result.results.append({
                            "agent_id": agent_id,
                            "success": success,
                            "improvement": response.get("improvement_pct", 0.0),
                        })
                        if success:
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
                from gaius.client import get_grpc_client

                inference_client = await get_grpc_client()
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

        response = await inference_client.call(
            service="Scheduler",
            action="complete",
            params={
                "prompt": prompt,
                "system_prompt": "You are designing reasoning tasks for AI capability development. "
                    "Focus on novel, challenging tasks that test different skills.",
                "agent": "thinking",
                # xhigh thinking at ~8 tok/s regularly ate a 2048 budget
                # entirely inside <think> (no answer text, 2026-08-31);
                # 4096 was eaten too (2026-09-02 THINKBURN — third
                # starvation of the day; traces run longer post-rebuild).
                # 8192 gives the answer room; the client deadline scales.
                "max_tokens": REASONING_MAX_TOKENS,
            },
        )

        # Validate and extract response fields with schema drift detection
        response_content, _ = _validate_complete_response(
            response, context="process_task_ideation"
        )
        task_names = []
        for line in response_content.split("\n"):
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
                from gaius.client import get_grpc_client

                inference_client = await get_grpc_client()
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
                response = await inference_client.call(
                    service="Scheduler",
                    action="complete",
                    params={
                        "prompt": f"Summarize this activity period:\n{summary_text}\n\n"
                            "Add brief insights about the activity level.",
                        "system_prompt": "You are generating a brief activity summary.",
                        "agent": "thinking",
                        "max_tokens": REASONING_MAX_TOKENS,
                    },
                )
                # Validate and extract response fields with schema drift detection
                insights_text, _ = _validate_complete_response(
                    response, context="process_daily_summary"
                )
                summary_text += f"\n## Insights\n\n{insights_text}\n"
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
