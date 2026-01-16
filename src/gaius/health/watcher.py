"""Health Watch - Runtime observation of commands for fallbacks and stubs.

Executes commands while monitoring logs and telemetry for patterns
indicating incomplete implementations, fallbacks, or caught exceptions.

Architecture:
    Instead of parsing complex span hierarchies, we use "span events" as
    discrete facts that get emitted during execution. This is similar to
    CDR (Call Data Record) pattern matching - events over time with state.

    Facts are structured as:
        (timestamp, event_type, span_name, attributes)

    Patterns in heuristics can match against these facts using simple rules.

Usage:
    /health watch /evolve start
    /health watch /kb search "query"
"""

import asyncio
import io
import logging
import re
import time
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Pattern, TypedDict


class ObservationType(Enum):
    """Types of observable patterns."""

    STUB = "stub"
    FALLBACK = "fallback"
    LEGACY = "legacy"
    NOT_IMPLEMENTED = "not_implemented"
    EXCEPTION_CAUGHT = "exception_caught"
    SUCCESS = "success"
    NOOP = "noop"
    # OTel-specific types
    SPAN_EVENT = "span_event"
    SPAN_ATTRIBUTE = "span_attribute"


class LogPattern(TypedDict, total=False):
    """Type definition for log pattern dictionaries."""

    pattern: Pattern[str]
    type: ObservationType
    action: str


@dataclass
class SpanFact:
    """A discrete fact from OTel span execution.

    Inspired by CDR pattern matching where events have:
    - timestamp: when it occurred
    - event_type: what happened (span_start, span_end, event, attribute)
    - span_name: the operation name
    - attributes: key-value context

    This flattened representation makes pattern matching tractable
    without needing to traverse span hierarchies.
    """

    timestamp: float
    event_type: str  # span_start, span_end, event, attribute_set
    span_name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    parent_span: str | None = None

    def matches(self, pattern: "FactPattern") -> bool:
        """Check if this fact matches a pattern."""
        if pattern.event_type and pattern.event_type != self.event_type:
            return False
        if pattern.span_name and not re.search(pattern.span_name, self.span_name):
            return False
        if pattern.attribute_patterns:
            for key, value_pattern in pattern.attribute_patterns.items():
                if key not in self.attributes:
                    return False
                attr_value = str(self.attributes[key])
                if not re.search(value_pattern, attr_value):
                    return False
        return True


@dataclass
class FactPattern:
    """A pattern to match against SpanFacts.

    Simple pattern matching (not full RETE) but sufficient for
    detecting fallbacks, stubs, and incomplete implementations.
    """

    event_type: str | None = None  # Match specific event type
    span_name: str | None = None  # Regex to match span name
    attribute_patterns: dict[str, str] | None = None  # key -> regex patterns
    indicates: ObservationType = ObservationType.SPAN_EVENT
    description: str = ""


@dataclass
class Observation:
    """A single observed pattern during command execution."""

    type: ObservationType
    message: str
    source: str  # "log" or "stdout" or "telemetry" or "span"
    level: str  # logging level or "output" or "span_event"
    line: str  # the actual line matched or span description
    timestamp: float = field(default_factory=time.time)
    heuristic_id: str | None = None
    action: str | None = None  # suggested action
    span_fact: SpanFact | None = None  # original fact if from OTel


# Standard span patterns to watch for
SPAN_FACT_PATTERNS = [
    # Stub implementations indicated by span attributes
    FactPattern(
        event_type="attribute_set",
        attribute_patterns={"implementation.status": "stub"},
        indicates=ObservationType.STUB,
        description="Operation using stub implementation",
    ),
    # Fallback usage
    FactPattern(
        event_type="attribute_set",
        attribute_patterns={"fallback.used": "true|True"},
        indicates=ObservationType.FALLBACK,
        description="Operation fell back to alternate implementation",
    ),
    # Legacy code path
    FactPattern(
        event_type="event",
        attribute_patterns={"event.name": "legacy_fallback"},
        indicates=ObservationType.LEGACY,
        description="Legacy fallback code path executed",
    ),
    # Exception caught but continued
    FactPattern(
        event_type="event",
        attribute_patterns={"event.name": "exception_caught"},
        indicates=ObservationType.EXCEPTION_CAUGHT,
        description="Exception caught and handled (may hide issues)",
    ),
]


class SpanFactCollector:
    """Collects span facts during command execution.

    This is a lightweight in-process collector that captures:
    - Span start/end events
    - Span attributes as they're set
    - Span events (add_event calls)

    Facts are stored in a flat list for pattern matching,
    avoiding the complexity of span tree traversal.
    """

    def __init__(self):
        self.facts: list[SpanFact] = []
        self._active_spans: dict[int, str] = {}  # span_id -> span_name

    def on_span_start(self, span_name: str, span_id: int, parent_id: int | None = None) -> None:
        """Record span start fact."""
        self._active_spans[span_id] = span_name
        self.facts.append(SpanFact(
            timestamp=time.time(),
            event_type="span_start",
            span_name=span_name,
            attributes={"span_id": span_id},
            parent_span=self._active_spans.get(parent_id) if parent_id else None,
        ))

    def on_span_end(self, span_id: int, status: str = "ok") -> None:
        """Record span end fact."""
        span_name = self._active_spans.get(span_id, "unknown")
        self.facts.append(SpanFact(
            timestamp=time.time(),
            event_type="span_end",
            span_name=span_name,
            attributes={"status": status},
        ))

    def on_attribute_set(self, span_id: int, key: str, value: Any) -> None:
        """Record attribute set fact."""
        span_name = self._active_spans.get(span_id, "unknown")
        self.facts.append(SpanFact(
            timestamp=time.time(),
            event_type="attribute_set",
            span_name=span_name,
            attributes={key: value},
        ))

    def on_event(self, span_id: int, event_name: str, attributes: dict | None = None) -> None:
        """Record span event fact."""
        span_name = self._active_spans.get(span_id, "unknown")
        attrs = {"event.name": event_name}
        if attributes:
            attrs.update(attributes)
        self.facts.append(SpanFact(
            timestamp=time.time(),
            event_type="event",
            span_name=span_name,
            attributes=attrs,
        ))

    def match_patterns(self, patterns: list[FactPattern]) -> list[tuple[SpanFact, FactPattern]]:
        """Match collected facts against patterns.

        Returns list of (fact, pattern) tuples for matches.
        """
        matches = []
        for fact in self.facts:
            for pattern in patterns:
                if fact.matches(pattern):
                    matches.append((fact, pattern))
        return matches

    def clear(self) -> None:
        """Clear collected facts."""
        self.facts = []
        self._active_spans = {}


class InstrumentedSpan:
    """Wrapper span that reports to SpanFactCollector.

    Wraps the real OTel span (or NoOpSpan) and intercepts
    attribute/event calls to emit facts.
    """

    def __init__(self, real_span: Any, collector: SpanFactCollector, span_name: str):
        self._real_span = real_span
        self._collector = collector
        self._span_name = span_name
        self._span_id = id(self)
        self._collector.on_span_start(span_name, self._span_id)

    def __enter__(self) -> "InstrumentedSpan":
        if hasattr(self._real_span, "__enter__"):
            self._real_span.__enter__()
        return self

    def __exit__(self, *args: Any) -> None:
        self._collector.on_span_end(self._span_id, "ok" if args[0] is None else "error")
        if hasattr(self._real_span, "__exit__"):
            self._real_span.__exit__(*args)

    def set_attribute(self, key: str, value: Any) -> None:
        """Set attribute and emit fact."""
        self._collector.on_attribute_set(self._span_id, key, value)
        if hasattr(self._real_span, "set_attribute"):
            self._real_span.set_attribute(key, value)

    def add_event(self, name: str, attributes: dict | None = None) -> None:
        """Add event and emit fact."""
        self._collector.on_event(self._span_id, name, attributes)
        if hasattr(self._real_span, "add_event"):
            self._real_span.add_event(name, attributes)

    def set_status(self, status: Any) -> None:
        if hasattr(self._real_span, "set_status"):
            self._real_span.set_status(status)

    def record_exception(self, exc: Exception) -> None:
        self._collector.on_event(self._span_id, "exception", {"exception.type": type(exc).__name__})
        if hasattr(self._real_span, "record_exception"):
            self._real_span.record_exception(exc)


class InstrumentedTracer:
    """Tracer wrapper that creates InstrumentedSpans."""

    def __init__(self, real_tracer: Any, collector: SpanFactCollector):
        self._real_tracer = real_tracer
        self._collector = collector

    def start_as_current_span(self, name: str, **kwargs: Any):
        """Create an instrumented span."""
        from contextlib import contextmanager

        @contextmanager
        def _span_context():
            if hasattr(self._real_tracer, "start_as_current_span"):
                with self._real_tracer.start_as_current_span(name, **kwargs) as real_span:
                    yield InstrumentedSpan(real_span, self._collector, name)
            else:
                # NoOp tracer
                yield InstrumentedSpan(None, self._collector, name)

        return _span_context()


@dataclass
class WatchResult:
    """Result of watching a command execution."""

    command: str
    success: bool
    output: str
    error: str | None
    duration_ms: float
    observations: list[Observation] = field(default_factory=list)
    span_facts: list[SpanFact] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        """Check if any problematic patterns were observed."""
        problem_types = {
            ObservationType.STUB,
            ObservationType.FALLBACK,
            ObservationType.LEGACY,
            ObservationType.NOT_IMPLEMENTED,
            ObservationType.NOOP,
        }
        return any(obs.type in problem_types for obs in self.observations)

    def summary(self) -> dict:
        """Generate summary of observations by type."""
        summary = {}
        for obs in self.observations:
            key = obs.type.value
            if key not in summary:
                summary[key] = []
            summary[key].append(obs.message)
        return summary

    def span_summary(self) -> dict:
        """Generate summary of span facts."""
        if not self.span_facts:
            return {}

        summary = {
            "total_spans": len([f for f in self.span_facts if f.event_type == "span_start"]),
            "events": len([f for f in self.span_facts if f.event_type == "event"]),
            "attributes_set": len([f for f in self.span_facts if f.event_type == "attribute_set"]),
        }

        # Group by span name
        span_names = set(f.span_name for f in self.span_facts if f.span_name != "unknown")
        if span_names:
            summary["span_names"] = list(span_names)

        return summary


# Standard patterns to watch for in log output
# Note: Engine availability patterns removed - if engine is offline,
# the watcher (which runs in the engine) won't be watching anyway.
STANDARD_PATTERNS: list[LogPattern] = [
    # Stub implementations
    {
        "pattern": re.compile(r"\(stub\)|\bstub\b", re.IGNORECASE),
        "type": ObservationType.STUB,
        "action": "warn_incomplete",
    },
    # Not implemented
    {
        "pattern": re.compile(r"not (?:yet )?implemented", re.IGNORECASE),
        "type": ObservationType.NOT_IMPLEMENTED,
        "action": "warn_incomplete",
    },
    # Fallback patterns
    {
        "pattern": re.compile(r"(?:using|falling back to|fallback)", re.IGNORECASE),
        "type": ObservationType.FALLBACK,
        "action": "info_fallback",
    },
    # No-op patterns
    {
        "pattern": re.compile(r"\bno-?op\b", re.IGNORECASE),
        "type": ObservationType.NOOP,
        "action": "warn_noop",
    },
]


class LogCapture(logging.Handler):
    """Logging handler that captures log records for analysis."""

    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.setLevel(logging.DEBUG)

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class CommandWatcher:
    """Watches command execution for observable patterns.

    Collects observations from three sources:
    1. Log messages (pattern matching on log output)
    2. stdout/stderr (pattern matching on command output)
    3. OTel span facts (attribute/event pattern matching)
    """

    def __init__(
        self,
        patterns: list[LogPattern] | None = None,
        span_patterns: list[FactPattern] | None = None,
    ):
        """Initialize watcher with patterns to watch for.

        Args:
            patterns: Custom log patterns to match. If None, uses STANDARD_PATTERNS.
            span_patterns: Custom span fact patterns. If None, uses SPAN_FACT_PATTERNS.
        """
        self.patterns: list[LogPattern] = patterns or STANDARD_PATTERNS
        self.span_patterns = span_patterns or SPAN_FACT_PATTERNS
        self.observations: list[Observation] = []
        self.span_collector = SpanFactCollector()

    def analyze_line(self, line: str, source: str, level: str = "info") -> list[Observation]:
        """Analyze a single line for patterns.

        Args:
            line: The line to analyze
            source: Where the line came from (log, stdout, stderr)
            level: Log level or "output"

        Returns:
            List of observations found in this line
        """
        observations = []

        for pattern_def in self.patterns:
            pattern = pattern_def["pattern"]
            match = pattern.search(line)
            if match:
                obs_type: ObservationType = pattern_def["type"]
                obs_action: str | None = pattern_def.get("action")
                obs = Observation(
                    type=obs_type,
                    message=match.group(0),
                    source=source,
                    level=level,
                    line=line.strip(),
                    action=obs_action,
                )
                observations.append(obs)
                self.observations.append(obs)

        return observations

    def analyze_log_records(self, records: list[logging.LogRecord]) -> list[Observation]:
        """Analyze captured log records.

        Args:
            records: Log records to analyze

        Returns:
            List of observations found
        """
        all_observations = []
        for record in records:
            msg = record.getMessage()
            level = record.levelname.lower()
            observations = self.analyze_line(msg, "log", level)
            all_observations.extend(observations)
        return all_observations

    def analyze_output(self, output: str, source: str = "stdout") -> list[Observation]:
        """Analyze command output for patterns.

        Args:
            output: Output string to analyze
            source: stdout or stderr

        Returns:
            List of observations found
        """
        all_observations = []
        for line in output.split("\n"):
            if line.strip():
                observations = self.analyze_line(line, source, "output")
                all_observations.extend(observations)
        return all_observations

    def analyze_span_facts(self) -> list[Observation]:
        """Analyze collected span facts against patterns.

        Returns:
            List of observations from span fact matches
        """
        observations = []
        matches = self.span_collector.match_patterns(self.span_patterns)

        for fact, pattern in matches:
            obs = Observation(
                type=pattern.indicates,
                message=pattern.description or f"{pattern.indicates.value} detected",
                source="span",
                level="span_event",
                line=f"{fact.span_name}: {fact.attributes}",
                timestamp=fact.timestamp,
                action=f"check_{pattern.indicates.value}",
                span_fact=fact,
            )
            observations.append(obs)
            self.observations.append(obs)

        return observations

    def get_instrumented_tracer(self) -> InstrumentedTracer:
        """Get a tracer that reports to this watcher's collector."""
        from ..core.telemetry import get_tracer
        return InstrumentedTracer(get_tracer(), self.span_collector)

    async def watch_command(
        self,
        command_fn: Callable,
        command_str: str,
    ) -> WatchResult:
        """Execute a command while watching for patterns.

        Args:
            command_fn: Async function to execute
            command_str: String representation of command for logging

        Returns:
            WatchResult with output and observations
        """
        # Set up log capture
        log_capture = LogCapture()
        root_logger = logging.getLogger()
        original_level = root_logger.level
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(log_capture)

        # Clear span collector
        self.span_collector.clear()

        # Capture stdout/stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        start_time = time.time()
        error = None
        output = ""

        try:
            # Execute with output capture
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                result = await command_fn()

            output = stdout_capture.getvalue()
            error = stderr_capture.getvalue() or None

            success = True
        except Exception as e:
            success = False
            error = str(e)
            output = stdout_capture.getvalue()

        finally:
            # Restore logging
            root_logger.removeHandler(log_capture)
            root_logger.setLevel(original_level)

        duration_ms = (time.time() - start_time) * 1000

        # Clear previous observations
        self.observations = []

        # Analyze captured logs
        self.analyze_log_records(log_capture.records)

        # Analyze stdout/stderr
        if output:
            self.analyze_output(output, "stdout")
        if error:
            self.analyze_output(error, "stderr")

        # Analyze span facts
        self.analyze_span_facts()

        return WatchResult(
            command=command_str,
            success=success,
            output=output,
            error=error,
            duration_ms=duration_ms,
            observations=list(self.observations),
            span_facts=list(self.span_collector.facts),
        )


def format_watch_result(result: WatchResult) -> dict:
    """Format WatchResult for JSON output.

    Args:
        result: WatchResult to format

    Returns:
        Dictionary suitable for JSON serialization
    """
    observations_by_type = {}
    for obs in result.observations:
        type_key = obs.type.value
        if type_key not in observations_by_type:
            observations_by_type[type_key] = []
        observations_by_type[type_key].append({
            "message": obs.message,
            "source": obs.source,
            "level": obs.level,
            "line": obs.line[:200] + "..." if len(obs.line) > 200 else obs.line,
            "action": obs.action,
        })

    # Determine overall status
    if not result.success:
        status = "error"
    elif result.has_issues:
        status = "warn"
    else:
        status = "pass"

    # Format span facts if any
    span_info = None
    if result.span_facts:
        span_info = {
            "fact_count": len(result.span_facts),
            "summary": result.span_summary(),
            # Include a sample of interesting facts (events and attributes)
            "sample_facts": [
                {
                    "event_type": f.event_type,
                    "span_name": f.span_name,
                    "attributes": {k: str(v)[:100] for k, v in f.attributes.items()},
                }
                for f in result.span_facts
                if f.event_type in ("event", "attribute_set")
            ][:10],  # Limit to 10 samples
        }

    return {
        "command": result.command,
        "status": status,
        "success": result.success,
        "duration_ms": round(result.duration_ms, 2),
        "has_issues": result.has_issues,
        "observation_count": len(result.observations),
        "observations": observations_by_type,
        "spans": span_info,
        "output_preview": result.output[:500] if result.output else None,
        "error": result.error,
        "summary": result.summary(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Instrumentation Helpers
# ─────────────────────────────────────────────────────────────────────────────
# These helpers let code emit span events that /health watch can detect.
# They work with both real OTel spans and the NoOpSpan fallback.


def emit_stub_event(span: Any, operation: str, reason: str = "") -> None:
    """Emit a span event indicating stub implementation.

    Usage in code:
        with tracer.start_as_current_span("evolution.start") as span:
            emit_stub_event(span, "StartEvolution", "gRPC endpoint not wired")
            return {"started": True}  # stub response
    """
    if hasattr(span, "add_event"):
        span.add_event("stub_implementation", {
            "operation": operation,
            "reason": reason,
        })
    if hasattr(span, "set_attribute"):
        span.set_attribute("implementation.status", "stub")


def emit_fallback_event(
    span: Any,
    operation: str,
    fallback_to: str,
    reason: str = "",
) -> None:
    """Emit a span event indicating fallback was used.

    Usage in code:
        with tracer.start_as_current_span("scheduler.submit") as span:
            if not engine_available:
                emit_fallback_event(span, "submit", "direct_scheduler", "engine unreachable")
                return direct_scheduler.submit(job)
    """
    if hasattr(span, "add_event"):
        span.add_event("fallback_used", {
            "operation": operation,
            "fallback_to": fallback_to,
            "reason": reason,
        })
    if hasattr(span, "set_attribute"):
        span.set_attribute("fallback.used", True)
        span.set_attribute("fallback.target", fallback_to)
        span.set_attribute("fallback.reason", reason)


def emit_exception_caught(span: Any, exc: Exception, continued: bool = True) -> None:
    """Emit span event for caught exception that was handled.

    Usage in code:
        with tracer.start_as_current_span("kb.search") as span:
            try:
                return vector_search(query)
            except QdrantError as e:
                emit_exception_caught(span, e, continued=True)
                return fallback_text_search(query)
    """
    if hasattr(span, "add_event"):
        span.add_event("exception_caught", {
            "exception.type": type(exc).__name__,
            "exception.message": str(exc)[:200],
            "continued": continued,
        })
    if hasattr(span, "set_attribute"):
        span.set_attribute("error.handled", True)
        span.set_attribute("error.type", type(exc).__name__)
