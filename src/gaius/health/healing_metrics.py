"""OpenTelemetry metrics for self-healing system.

Provides counters, gauges, and histograms for monitoring:
- Healing attempt counts by tier/endpoint/action
- Success/failure rates
- Escalation patterns
- Cooldown status
- FMEA RPN scores

Usage:
    from gaius.health.healing_metrics import (
        record_healing_attempt,
        record_healing_escalation,
        record_cooldown,
    )

    # After an attempt
    record_healing_attempt(
        tier=0,
        endpoint="reasoning",
        action="SOFT_RESET",
        success=True,
        duration_ms=1500,
    )
"""

from typing import Any

# Lazy-initialized metrics
_healing_attempts: Any = None
_healing_success: Any = None
_healing_failure: Any = None
_healing_escalations: Any = None
_healing_duration: Any = None
_healing_in_progress: Any = None
_healing_cooldown: Any = None
_global_failures: Any = None
_fmea_rpn_score: Any = None
_fmea_occurrence_count: Any = None
_fmea_success_rate: Any = None


def _get_meter() -> Any:
    """Get OpenTelemetry meter."""
    from ..core.telemetry import get_meter
    return get_meter()


def _ensure_instruments() -> dict[str, Any]:
    """Create metrics instruments if not already created."""
    global _healing_attempts, _healing_success, _healing_failure
    global _healing_escalations, _healing_duration, _healing_in_progress
    global _healing_cooldown, _global_failures
    global _fmea_rpn_score, _fmea_occurrence_count, _fmea_success_rate

    if _healing_attempts is not None:
        return {
            "attempts": _healing_attempts,
            "success": _healing_success,
            "failure": _healing_failure,
            "escalations": _healing_escalations,
            "duration": _healing_duration,
            "in_progress": _healing_in_progress,
            "cooldown": _healing_cooldown,
            "global_failures": _global_failures,
            "fmea_rpn": _fmea_rpn_score,
            "fmea_occurrence": _fmea_occurrence_count,
            "fmea_success_rate": _fmea_success_rate,
        }

    meter = _get_meter()

    # Counters
    _healing_attempts = meter.create_counter(
        "gaius.healing.attempts_total",
        description="Total healing attempts",
        unit="1",
    )

    _healing_success = meter.create_counter(
        "gaius.healing.success_total",
        description="Successful healing attempts",
        unit="1",
    )

    _healing_failure = meter.create_counter(
        "gaius.healing.failure_total",
        description="Failed healing attempts",
        unit="1",
    )

    _healing_escalations = meter.create_counter(
        "gaius.healing.escalations_total",
        description="Tier escalations",
        unit="1",
    )

    # Histogram for duration
    _healing_duration = meter.create_histogram(
        "gaius.healing.duration_ms",
        description="Healing attempt duration in milliseconds",
        unit="ms",
    )

    # Gauges (using up_down_counter for approximation)
    _healing_in_progress = meter.create_up_down_counter(
        "gaius.healing.in_progress",
        description="Healing attempts currently in progress",
        unit="1",
    )

    _healing_cooldown = meter.create_up_down_counter(
        "gaius.healing.cooldown_active",
        description="Endpoints currently in cooldown",
        unit="1",
    )

    _global_failures = meter.create_up_down_counter(
        "gaius.healing.global_failures",
        description="Global failure count toward circuit breaker",
        unit="1",
    )

    # FMEA metrics
    _fmea_rpn_score = meter.create_histogram(
        "gaius.fmea.rpn_score",
        description="RPN scores for failure modes",
        unit="1",
    )

    _fmea_occurrence_count = meter.create_counter(
        "gaius.fmea.occurrence_total",
        description="Failure mode occurrences",
        unit="1",
    )

    _fmea_success_rate = meter.create_histogram(
        "gaius.fmea.success_rate",
        description="Healing success rate by failure mode",
        unit="%",
    )

    return {
        "attempts": _healing_attempts,
        "success": _healing_success,
        "failure": _healing_failure,
        "escalations": _healing_escalations,
        "duration": _healing_duration,
        "in_progress": _healing_in_progress,
        "cooldown": _healing_cooldown,
        "global_failures": _global_failures,
        "fmea_rpn": _fmea_rpn_score,
        "fmea_occurrence": _fmea_occurrence_count,
        "fmea_success_rate": _fmea_success_rate,
    }


def record_healing_attempt(
    tier: int,
    endpoint: str,
    action: str,
    success: bool,
    duration_ms: int,
    failure_mode_id: str | None = None,
) -> None:
    """Record a healing attempt with all relevant metrics.

    Args:
        tier: Healing tier (0, 1, or 2)
        endpoint: Affected endpoint name
        action: Action taken (e.g., "SOFT_RESET", "clear_cuda_cache")
        success: Whether the attempt succeeded
        duration_ms: Duration in milliseconds
        failure_mode_id: Optional FMEA failure mode ID
    """
    instruments = _ensure_instruments()

    attrs = {
        "tier": str(tier),
        "endpoint": endpoint,
        "action": action,
    }
    if failure_mode_id:
        attrs["failure_mode_id"] = failure_mode_id

    # Record attempt count
    instruments["attempts"].add(1, attrs)

    # Record success or failure
    if success:
        instruments["success"].add(1, attrs)
    else:
        instruments["failure"].add(1, attrs)

    # Record duration
    instruments["duration"].record(duration_ms, attrs)


def record_healing_escalation(
    endpoint: str,
    from_tier: int,
    to_tier: int,
    reason: str = "",
) -> None:
    """Record a tier escalation event.

    Args:
        endpoint: Affected endpoint name
        from_tier: Source tier
        to_tier: Target tier
        reason: Reason for escalation
    """
    instruments = _ensure_instruments()

    attrs = {
        "endpoint": endpoint,
        "from_tier": str(from_tier),
        "to_tier": str(to_tier),
    }
    if reason:
        attrs["reason"] = reason

    instruments["escalations"].add(1, attrs)


def record_healing_start(endpoint: str, tier: int) -> None:
    """Record that healing has started for an endpoint.

    Args:
        endpoint: Endpoint being healed
        tier: Current healing tier
    """
    instruments = _ensure_instruments()
    instruments["in_progress"].add(1, {"endpoint": endpoint, "tier": str(tier)})


def record_healing_end(endpoint: str, tier: int) -> None:
    """Record that healing has ended for an endpoint.

    Args:
        endpoint: Endpoint that was healed
        tier: Final healing tier
    """
    instruments = _ensure_instruments()
    instruments["in_progress"].add(-1, {"endpoint": endpoint, "tier": str(tier)})


def record_cooldown(endpoint: str, active: bool, cooldown_seconds: int = 0) -> None:
    """Record cooldown status change.

    Args:
        endpoint: Affected endpoint
        active: Whether cooldown is now active
        cooldown_seconds: Cooldown duration
    """
    instruments = _ensure_instruments()
    delta = 1 if active else -1
    instruments["cooldown"].add(delta, {"endpoint": endpoint})


def record_circuit_breaker(failures: int, tripped: bool) -> None:
    """Record global circuit breaker state.

    Args:
        failures: Current failure count
        tripped: Whether circuit breaker is tripped
    """
    instruments = _ensure_instruments()
    # This sets the gauge to the current failure count
    # We use delta calculation for up_down_counter
    instruments["global_failures"].add(
        1 if failures > 0 else -1,
        {"tripped": str(tripped).lower()},
    )


def record_fmea_rpn(
    failure_mode_id: str,
    endpoint: str,
    rpn: int,
    severity: int,
    occurrence: int,
    detection: int,
) -> None:
    """Record FMEA RPN score.

    Args:
        failure_mode_id: FMEA failure mode ID
        endpoint: Affected endpoint
        rpn: Calculated RPN score
        severity: S factor (1-10)
        occurrence: O factor (1-10)
        detection: D factor (1-10)
    """
    instruments = _ensure_instruments()

    attrs = {
        "failure_mode_id": failure_mode_id,
        "endpoint": endpoint,
    }

    instruments["fmea_rpn"].record(rpn, attrs)


def record_fmea_occurrence(
    failure_mode_id: str,
    endpoint: str | None = None,
) -> None:
    """Record a failure mode occurrence.

    Args:
        failure_mode_id: FMEA failure mode ID
        endpoint: Optional affected endpoint
    """
    instruments = _ensure_instruments()

    attrs = {"failure_mode_id": failure_mode_id}
    if endpoint:
        attrs["endpoint"] = endpoint

    instruments["fmea_occurrence"].add(1, attrs)


def record_fmea_success_rate(
    failure_mode_id: str,
    tier: int,
    success_rate: float,
) -> None:
    """Record FMEA success rate for a failure mode at a tier.

    Args:
        failure_mode_id: FMEA failure mode ID
        tier: Healing tier
        success_rate: Success rate percentage (0-100)
    """
    instruments = _ensure_instruments()

    instruments["fmea_success_rate"].record(
        success_rate,
        {"failure_mode_id": failure_mode_id, "tier": str(tier)},
    )


# Convenience function for batch recording from events
def record_from_healing_event(event_type: str, event_data: dict) -> None:
    """Record metrics from a healing event dict.

    Args:
        event_type: Type of event (attempt_succeeded, attempt_failed, etc.)
        event_data: Event data with endpoint, tier, payload, etc.
    """
    endpoint = event_data.get("endpoint", "unknown")
    tier = event_data.get("tier", 0)
    payload = event_data.get("payload", {})

    if event_type == "attempt_succeeded":
        record_healing_attempt(
            tier=tier,
            endpoint=endpoint,
            action=payload.get("action", "unknown"),
            success=True,
            duration_ms=payload.get("duration_ms", 0),
            failure_mode_id=event_data.get("failure_mode_id"),
        )
        record_healing_end(endpoint, tier)

    elif event_type == "attempt_failed":
        record_healing_attempt(
            tier=tier,
            endpoint=endpoint,
            action=payload.get("action", "unknown"),
            success=False,
            duration_ms=payload.get("duration_ms", 0),
            failure_mode_id=event_data.get("failure_mode_id"),
        )

    elif event_type == "attempt_started":
        record_healing_start(endpoint, tier)

    elif event_type in ("tier_entered", "tier_exhausted"):
        from_tier = payload.get("from_tier")
        to_tier = payload.get("to_tier", tier)
        if from_tier is not None:
            record_healing_escalation(
                endpoint=endpoint,
                from_tier=from_tier,
                to_tier=to_tier,
                reason=payload.get("reason", ""),
            )

    elif event_type == "cooldown_started":
        record_cooldown(
            endpoint=endpoint,
            active=True,
            cooldown_seconds=payload.get("cooldown_seconds", 0),
        )

    elif event_type == "cooldown_cleared":
        record_cooldown(endpoint=endpoint, active=False)

    elif event_type == "circuit_breaker_tripped":
        record_circuit_breaker(
            failures=payload.get("failure_count", 0),
            tripped=True,
        )

    elif event_type == "circuit_breaker_reset":
        record_circuit_breaker(failures=0, tripped=False)
