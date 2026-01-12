"""Typed Python dataclasses mirroring protobuf messages.

Engine Federation Architecture:
These types provide tight coupling to protobuf schema for cross-process
communication. Unlike MessageToDict which produces untyped dicts, these
classes catch schema drift at:

1. **Type checking time** - ty/mypy catches field name mismatches
2. **Parse time** - from_proto_dict() fails if required fields missing
3. **Runtime** - field access is explicit, not dict.get() with fallbacks

Usage:
    from gaius.engine.proto_types import CompleteResponseDTO

    # Parse gRPC response into typed object
    response_dict = MessageToDict(grpc_response, preserving_proto_field_name=True)
    dto = CompleteResponseDTO.from_proto_dict(response_dict)

    # Type-safe field access (IDE autocomplete, type checking)
    text = dto.text  # type: str
    tokens = dto.tokens_used  # type: int

GAI:META
layer: L3-engine
depends_on: []
purpose: Proto schema coupling for early drift detection
guru_code: COG.00000011.SCHEMADRIFT
"""

from dataclasses import dataclass
from typing import Any, Optional, TypeVar

T = TypeVar("T")


class ProtoParseError(Exception):
    """Raised when proto dict parsing fails due to schema mismatch.

    Guru Code: #PROTO.00000001.PARSEFAIL
    """

    def __init__(self, message_type: str, field: str, actual_fields: set[str]):
        self.message_type = message_type
        self.field = field
        self.actual_fields = actual_fields
        super().__init__(
            f"Proto schema mismatch (#PROTO.00000001.PARSEFAIL): "
            f"{message_type} missing required field '{field}'. "
            f"Actual fields: {actual_fields}. "
            f"Check if proto was regenerated without updating client."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler Messages
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CompleteResponseDTO:
    """Typed mirror of gaius.engine.CompleteResponse proto.

    Proto definition (gaius_service.proto):
        message CompleteResponse {
          string text = 1;
          int32 tokens_used = 2;
          float latency_ms = 3;
          string model = 4;
          string job_id = 5;
        }

    Field naming follows proto field names exactly for 1:1 mapping.
    """

    text: str
    tokens_used: int
    latency_ms: float
    model: str
    job_id: str

    @classmethod
    def from_proto_dict(cls, d: dict[str, Any]) -> "CompleteResponseDTO":
        """Parse proto dict into typed DTO, failing fast on schema mismatch.

        This is the critical coupling point - if the proto changes,
        this method will raise ProtoParseError at parse time.

        Args:
            d: Dict from MessageToDict(response, preserving_proto_field_name=True)

        Returns:
            Typed CompleteResponseDTO

        Raises:
            ProtoParseError: If required fields are missing (schema drift)
        """
        actual_fields = set(d.keys()) if d else set()

        # Required field: text (the LLM output)
        if "text" not in actual_fields:
            raise ProtoParseError("CompleteResponse", "text", actual_fields)

        return cls(
            text=d.get("text", ""),
            tokens_used=d.get("tokens_used", 0) or d.get("tokensUsed", 0),
            latency_ms=d.get("latency_ms", 0.0) or d.get("latencyMs", 0.0),
            model=d.get("model", ""),
            job_id=d.get("job_id", "") or d.get("jobId", ""),
        )

    @classmethod
    def from_proto_dict_lenient(
        cls, d: dict[str, Any], context: str = ""
    ) -> "CompleteResponseDTO":
        """Parse proto dict with lenient fallbacks for backwards compatibility.

        Use this during migration or when interacting with potentially
        outdated services. Logs warnings AND emits OTel span events for
        observability (fail-openly pattern).

        Args:
            d: Dict from MessageToDict
            context: Description for logging

        Returns:
            Best-effort CompleteResponseDTO
        """
        import logging

        logger = logging.getLogger(__name__)
        actual_fields = set(d.keys()) if d else set()

        # Try canonical field names first, fall back to alternatives
        text = d.get("text") or d.get("content", "")
        tokens_used = d.get("tokens_used") or d.get("tokensUsed") or d.get("output_tokens", 0)
        latency_ms = d.get("latency_ms") or d.get("latencyMs", 0.0)

        # Detect and warn about non-canonical field usage
        drift_details: list[dict[str, str]] = []
        if "text" not in actual_fields and "content" in actual_fields:
            drift_details.append({"expected": "text", "actual": "content"})
        if "tokens_used" not in actual_fields and "output_tokens" in actual_fields:
            drift_details.append({"expected": "tokens_used", "actual": "output_tokens"})

        if drift_details:
            warnings = [f"Using '{d['actual']}' instead of '{d['expected']}'" for d in drift_details]
            logger.warning(
                f"Proto field name drift in {context}: {'; '.join(warnings)}. "
                f"Fields: {actual_fields}. Guru: #COG.00000011.SCHEMADRIFT"
            )

            # Emit OTel span event for observability (fail-openly pattern)
            try:
                from opentelemetry import trace

                span = trace.get_current_span()
                if span and span.is_recording():
                    span.add_event(
                        "proto_schema_drift",
                        attributes={
                            "proto.message_type": "CompleteResponse",
                            "proto.context": context,
                            "proto.expected_fields": ",".join(d["expected"] for d in drift_details),
                            "proto.actual_fields": ",".join(d["actual"] for d in drift_details),
                            "proto.all_fields": ",".join(sorted(actual_fields)),
                            "guru_code": "COG.00000011.SCHEMADRIFT",
                        },
                    )
            except ImportError:
                pass  # OTel not available, logging is sufficient

        return cls(
            text=text,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            model=d.get("model", ""),
            job_id=d.get("job_id", "") or d.get("jobId", ""),
        )


@dataclass(frozen=True, slots=True)
class SubmitJobResponseDTO:
    """Typed mirror of gaius.engine.SubmitJobResponse proto."""

    job_id: str
    queued: bool
    estimated_wait_ms: int

    @classmethod
    def from_proto_dict(cls, d: dict[str, Any]) -> "SubmitJobResponseDTO":
        actual_fields = set(d.keys()) if d else set()
        if "job_id" not in actual_fields and "jobId" not in actual_fields:
            raise ProtoParseError("SubmitJobResponse", "job_id", actual_fields)

        return cls(
            job_id=d.get("job_id", "") or d.get("jobId", ""),
            queued=d.get("queued", False),
            estimated_wait_ms=d.get("estimated_wait_ms", 0) or d.get("estimatedWaitMs", 0),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator Messages
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class EndpointInfoDTO:
    """Typed mirror of gaius.engine.EndpointInfo proto."""

    name: str
    model: str
    status: str  # ProcessStatus enum as string
    port: int
    gpu_ids: list[int]
    pid: int

    @classmethod
    def from_proto_dict(cls, d: dict[str, Any]) -> "EndpointInfoDTO":
        return cls(
            name=d.get("name", ""),
            model=d.get("model", ""),
            status=d.get("status", "PROCESS_STATUS_UNSPECIFIED"),
            port=d.get("port", 0),
            gpu_ids=d.get("gpu_ids", []) or d.get("gpuIds", []),
            pid=d.get("pid", 0),
        )


@dataclass(frozen=True, slots=True)
class OrchestratorStatusDTO:
    """Typed mirror of gaius.engine.OrchestratorStatusResponse proto."""

    total_gpus: int
    available_gpus: int
    endpoints: list[EndpointInfoDTO]

    @classmethod
    def from_proto_dict(cls, d: dict[str, Any]) -> "OrchestratorStatusDTO":
        endpoints_raw = d.get("endpoints", [])
        endpoints = [EndpointInfoDTO.from_proto_dict(e) for e in endpoints_raw]
        return cls(
            total_gpus=d.get("total_gpus", 0) or d.get("totalGpus", 0),
            available_gpus=d.get("available_gpus", 0) or d.get("availableGpus", 0),
            endpoints=endpoints,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Cognition Messages
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TriggerCognitionResponseDTO:
    """Typed mirror of gaius.engine.TriggerCognitionResponse proto."""

    success: bool
    thoughts_generated: int
    patterns_detected: int
    connections_found: int
    tokens_used: int
    kb_path: str
    error: str

    @classmethod
    def from_proto_dict(cls, d: dict[str, Any]) -> "TriggerCognitionResponseDTO":
        return cls(
            success=d.get("success", False),
            thoughts_generated=d.get("thoughts_generated", 0) or d.get("thoughtsGenerated", 0),
            patterns_detected=d.get("patterns_detected", 0) or d.get("patternsDetected", 0),
            connections_found=d.get("connections_found", 0) or d.get("connectionsFound", 0),
            tokens_used=d.get("tokens_used", 0) or d.get("tokensUsed", 0),
            kb_path=d.get("kb_path", "") or d.get("kbPath", ""),
            error=d.get("error", ""),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Type-Safe Parsing Utilities
# ─────────────────────────────────────────────────────────────────────────────


def parse_complete_response(
    d: dict[str, Any],
    context: str = "",
    strict: bool = False,
) -> CompleteResponseDTO:
    """Parse CompleteResponse with configurable strictness.

    Engine Federation Architecture:
    This is the canonical entry point for parsing CompleteResponse
    across process boundaries. Use strict=True in production to
    catch drift early, strict=False during development/migration.

    Args:
        d: Dict from MessageToDict
        context: Description for error/warning messages
        strict: If True, raises ProtoParseError on any schema issue

    Returns:
        Typed CompleteResponseDTO
    """
    if strict:
        return CompleteResponseDTO.from_proto_dict(d)
    return CompleteResponseDTO.from_proto_dict_lenient(d, context)
