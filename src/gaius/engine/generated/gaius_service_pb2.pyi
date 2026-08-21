from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ProcessStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    PROCESS_STATUS_UNSPECIFIED: _ClassVar[ProcessStatus]
    PROCESS_STATUS_STOPPED: _ClassVar[ProcessStatus]
    PROCESS_STATUS_STARTING: _ClassVar[ProcessStatus]
    PROCESS_STATUS_HEALTHY: _ClassVar[ProcessStatus]
    PROCESS_STATUS_UNHEALTHY: _ClassVar[ProcessStatus]
    PROCESS_STATUS_STOPPING: _ClassVar[ProcessStatus]
    PROCESS_STATUS_FAILED: _ClassVar[ProcessStatus]
    PROCESS_STATUS_PENDING: _ClassVar[ProcessStatus]

class CheckStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CHECK_STATUS_UNSPECIFIED: _ClassVar[CheckStatus]
    CHECK_STATUS_PASS: _ClassVar[CheckStatus]
    CHECK_STATUS_WARN: _ClassVar[CheckStatus]
    CHECK_STATUS_FAIL: _ClassVar[CheckStatus]
    CHECK_STATUS_SKIP: _ClassVar[CheckStatus]

class IncidentStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    INCIDENT_STATUS_UNSPECIFIED: _ClassVar[IncidentStatus]
    INCIDENT_STATUS_ACTIVE: _ClassVar[IncidentStatus]
    INCIDENT_STATUS_HEALING: _ClassVar[IncidentStatus]
    INCIDENT_STATUS_RECOVERING: _ClassVar[IncidentStatus]
    INCIDENT_STATUS_RESOLVED: _ClassVar[IncidentStatus]
    INCIDENT_STATUS_MANUAL_REQUIRED: _ClassVar[IncidentStatus]

class RemediationTier(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    REMEDIATION_TIER_UNSPECIFIED: _ClassVar[RemediationTier]
    REMEDIATION_TIER_0: _ClassVar[RemediationTier]
    REMEDIATION_TIER_1: _ClassVar[RemediationTier]
    REMEDIATION_TIER_2: _ClassVar[RemediationTier]
    REMEDIATION_TIER_3: _ClassVar[RemediationTier]

class IncidentTransition(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    INCIDENT_TRANSITION_UNSPECIFIED: _ClassVar[IncidentTransition]
    INCIDENT_TRANSITION_ACTIVE_TO_HEALING: _ClassVar[IncidentTransition]
    INCIDENT_TRANSITION_ACTIVE_TO_RECOVERING: _ClassVar[IncidentTransition]
    INCIDENT_TRANSITION_HEALING_TO_RECOVERING: _ClassVar[IncidentTransition]
    INCIDENT_TRANSITION_HEALING_TO_MANUAL: _ClassVar[IncidentTransition]
    INCIDENT_TRANSITION_RECOVERING_TO_RESOLVED: _ClassVar[IncidentTransition]
    INCIDENT_TRANSITION_RECOVERING_TO_ACTIVE: _ClassVar[IncidentTransition]

class PhaseChangeType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    PHASE_CHANGE_UNSPECIFIED: _ClassVar[PhaseChangeType]
    PHASE_CHANGE_COLNOMIC_LOAD: _ClassVar[PhaseChangeType]
    PHASE_CHANGE_INSTRUCT_RESTORE: _ClassVar[PhaseChangeType]
    PHASE_CHANGE_REASONING_LOAD: _ClassVar[PhaseChangeType]
    PHASE_CHANGE_BASELINE_RESTORE: _ClassVar[PhaseChangeType]

class PhaseChangeStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    PHASE_STATUS_UNSPECIFIED: _ClassVar[PhaseChangeStatus]
    PHASE_STATUS_PENDING: _ClassVar[PhaseChangeStatus]
    PHASE_STATUS_IN_PROGRESS: _ClassVar[PhaseChangeStatus]
    PHASE_STATUS_CONVERGED: _ClassVar[PhaseChangeStatus]
    PHASE_STATUS_FAILED: _ClassVar[PhaseChangeStatus]

class WorkloadType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    WORKLOAD_INIT: _ClassVar[WorkloadType]
    WORKLOAD_SWARM: _ClassVar[WorkloadType]
    WORKLOAD_INFERENCE: _ClassVar[WorkloadType]
    WORKLOAD_EMBEDDING: _ClassVar[WorkloadType]
    WORKLOAD_EVOLUTION: _ClassVar[WorkloadType]
    WORKLOAD_RENDERING: _ClassVar[WorkloadType]

class AmbientPhase(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    AMBIENT_PHASE_UNSPECIFIED: _ClassVar[AmbientPhase]
    AMBIENT_PHASE_BASELINE_HEALTH: _ClassVar[AmbientPhase]
    AMBIENT_PHASE_BASELINE_WORKLOAD: _ClassVar[AmbientPhase]
    AMBIENT_PHASE_REASONING_EVICTION: _ClassVar[AmbientPhase]
    AMBIENT_PHASE_REASONING_WORKLOAD: _ClassVar[AmbientPhase]
    AMBIENT_PHASE_BASELINE_RESTORATION: _ClassVar[AmbientPhase]
    AMBIENT_PHASE_COMPLETE: _ClassVar[AmbientPhase]
    AMBIENT_PHASE_ERROR: _ClassVar[AmbientPhase]
    AMBIENT_PHASE_FETCH_CONTENT: _ClassVar[AmbientPhase]
    AMBIENT_PHASE_SUMMARIZATION: _ClassVar[AmbientPhase]
    AMBIENT_PHASE_BUFFER_ANALYSIS: _ClassVar[AmbientPhase]

class RenderPhase(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    RENDER_PHASE_UNSPECIFIED: _ClassVar[RenderPhase]
    RENDER_PHASE_QUEUED: _ClassVar[RenderPhase]
    RENDER_PHASE_ALLOCATING: _ClassVar[RenderPhase]
    RENDER_PHASE_RENDERING: _ClassVar[RenderPhase]
    RENDER_PHASE_UPLOADING: _ClassVar[RenderPhase]
    RENDER_PHASE_COMPLETE: _ClassVar[RenderPhase]
    RENDER_PHASE_FAILED: _ClassVar[RenderPhase]
    RENDER_PHASE_BATCH_COMPLETE: _ClassVar[RenderPhase]
PROCESS_STATUS_UNSPECIFIED: ProcessStatus
PROCESS_STATUS_STOPPED: ProcessStatus
PROCESS_STATUS_STARTING: ProcessStatus
PROCESS_STATUS_HEALTHY: ProcessStatus
PROCESS_STATUS_UNHEALTHY: ProcessStatus
PROCESS_STATUS_STOPPING: ProcessStatus
PROCESS_STATUS_FAILED: ProcessStatus
PROCESS_STATUS_PENDING: ProcessStatus
CHECK_STATUS_UNSPECIFIED: CheckStatus
CHECK_STATUS_PASS: CheckStatus
CHECK_STATUS_WARN: CheckStatus
CHECK_STATUS_FAIL: CheckStatus
CHECK_STATUS_SKIP: CheckStatus
INCIDENT_STATUS_UNSPECIFIED: IncidentStatus
INCIDENT_STATUS_ACTIVE: IncidentStatus
INCIDENT_STATUS_HEALING: IncidentStatus
INCIDENT_STATUS_RECOVERING: IncidentStatus
INCIDENT_STATUS_RESOLVED: IncidentStatus
INCIDENT_STATUS_MANUAL_REQUIRED: IncidentStatus
REMEDIATION_TIER_UNSPECIFIED: RemediationTier
REMEDIATION_TIER_0: RemediationTier
REMEDIATION_TIER_1: RemediationTier
REMEDIATION_TIER_2: RemediationTier
REMEDIATION_TIER_3: RemediationTier
INCIDENT_TRANSITION_UNSPECIFIED: IncidentTransition
INCIDENT_TRANSITION_ACTIVE_TO_HEALING: IncidentTransition
INCIDENT_TRANSITION_ACTIVE_TO_RECOVERING: IncidentTransition
INCIDENT_TRANSITION_HEALING_TO_RECOVERING: IncidentTransition
INCIDENT_TRANSITION_HEALING_TO_MANUAL: IncidentTransition
INCIDENT_TRANSITION_RECOVERING_TO_RESOLVED: IncidentTransition
INCIDENT_TRANSITION_RECOVERING_TO_ACTIVE: IncidentTransition
PHASE_CHANGE_UNSPECIFIED: PhaseChangeType
PHASE_CHANGE_COLNOMIC_LOAD: PhaseChangeType
PHASE_CHANGE_INSTRUCT_RESTORE: PhaseChangeType
PHASE_CHANGE_REASONING_LOAD: PhaseChangeType
PHASE_CHANGE_BASELINE_RESTORE: PhaseChangeType
PHASE_STATUS_UNSPECIFIED: PhaseChangeStatus
PHASE_STATUS_PENDING: PhaseChangeStatus
PHASE_STATUS_IN_PROGRESS: PhaseChangeStatus
PHASE_STATUS_CONVERGED: PhaseChangeStatus
PHASE_STATUS_FAILED: PhaseChangeStatus
WORKLOAD_INIT: WorkloadType
WORKLOAD_SWARM: WorkloadType
WORKLOAD_INFERENCE: WorkloadType
WORKLOAD_EMBEDDING: WorkloadType
WORKLOAD_EVOLUTION: WorkloadType
WORKLOAD_RENDERING: WorkloadType
AMBIENT_PHASE_UNSPECIFIED: AmbientPhase
AMBIENT_PHASE_BASELINE_HEALTH: AmbientPhase
AMBIENT_PHASE_BASELINE_WORKLOAD: AmbientPhase
AMBIENT_PHASE_REASONING_EVICTION: AmbientPhase
AMBIENT_PHASE_REASONING_WORKLOAD: AmbientPhase
AMBIENT_PHASE_BASELINE_RESTORATION: AmbientPhase
AMBIENT_PHASE_COMPLETE: AmbientPhase
AMBIENT_PHASE_ERROR: AmbientPhase
AMBIENT_PHASE_FETCH_CONTENT: AmbientPhase
AMBIENT_PHASE_SUMMARIZATION: AmbientPhase
AMBIENT_PHASE_BUFFER_ANALYSIS: AmbientPhase
RENDER_PHASE_UNSPECIFIED: RenderPhase
RENDER_PHASE_QUEUED: RenderPhase
RENDER_PHASE_ALLOCATING: RenderPhase
RENDER_PHASE_RENDERING: RenderPhase
RENDER_PHASE_UPLOADING: RenderPhase
RENDER_PHASE_COMPLETE: RenderPhase
RENDER_PHASE_FAILED: RenderPhase
RENDER_PHASE_BATCH_COMPLETE: RenderPhase

class FailureModeMapping(_message.Message):
    __slots__ = ("fmea_id", "heuristic_path", "check_name_pattern", "endpoint_pattern")
    FMEA_ID_FIELD_NUMBER: _ClassVar[int]
    HEURISTIC_PATH_FIELD_NUMBER: _ClassVar[int]
    CHECK_NAME_PATTERN_FIELD_NUMBER: _ClassVar[int]
    ENDPOINT_PATTERN_FIELD_NUMBER: _ClassVar[int]
    fmea_id: str
    heuristic_path: str
    check_name_pattern: str
    endpoint_pattern: str
    def __init__(self, fmea_id: _Optional[str] = ..., heuristic_path: _Optional[str] = ..., check_name_pattern: _Optional[str] = ..., endpoint_pattern: _Optional[str] = ...) -> None: ...

class FailureModeRegistry(_message.Message):
    __slots__ = ("mappings",)
    MAPPINGS_FIELD_NUMBER: _ClassVar[int]
    mappings: _containers.RepeatedCompositeFieldContainer[FailureModeMapping]
    def __init__(self, mappings: _Optional[_Iterable[_Union[FailureModeMapping, _Mapping]]] = ...) -> None: ...

class OrchestratorStatusResponse(_message.Message):
    __slots__ = ("total_gpus", "available_gpus", "allocations", "endpoints")
    TOTAL_GPUS_FIELD_NUMBER: _ClassVar[int]
    AVAILABLE_GPUS_FIELD_NUMBER: _ClassVar[int]
    ALLOCATIONS_FIELD_NUMBER: _ClassVar[int]
    ENDPOINTS_FIELD_NUMBER: _ClassVar[int]
    total_gpus: int
    available_gpus: int
    allocations: _containers.RepeatedCompositeFieldContainer[GPUAllocation]
    endpoints: _containers.RepeatedCompositeFieldContainer[EndpointInfo]
    def __init__(self, total_gpus: _Optional[int] = ..., available_gpus: _Optional[int] = ..., allocations: _Optional[_Iterable[_Union[GPUAllocation, _Mapping]]] = ..., endpoints: _Optional[_Iterable[_Union[EndpointInfo, _Mapping]]] = ...) -> None: ...

class GPUAllocation(_message.Message):
    __slots__ = ("agent_alias", "model", "gpu_ids", "vram_reserved_gb")
    AGENT_ALIAS_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    GPU_IDS_FIELD_NUMBER: _ClassVar[int]
    VRAM_RESERVED_GB_FIELD_NUMBER: _ClassVar[int]
    agent_alias: str
    model: str
    gpu_ids: _containers.RepeatedScalarFieldContainer[int]
    vram_reserved_gb: float
    def __init__(self, agent_alias: _Optional[str] = ..., model: _Optional[str] = ..., gpu_ids: _Optional[_Iterable[int]] = ..., vram_reserved_gb: _Optional[float] = ...) -> None: ...

class EndpointInfo(_message.Message):
    __slots__ = ("name", "model", "status", "gpu_ids", "port")
    NAME_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    GPU_IDS_FIELD_NUMBER: _ClassVar[int]
    PORT_FIELD_NUMBER: _ClassVar[int]
    name: str
    model: str
    status: ProcessStatus
    gpu_ids: _containers.RepeatedScalarFieldContainer[int]
    port: int
    def __init__(self, name: _Optional[str] = ..., model: _Optional[str] = ..., status: _Optional[_Union[ProcessStatus, str]] = ..., gpu_ids: _Optional[_Iterable[int]] = ..., port: _Optional[int] = ...) -> None: ...

class StartEndpointRequest(_message.Message):
    __slots__ = ("endpoint_name",)
    ENDPOINT_NAME_FIELD_NUMBER: _ClassVar[int]
    endpoint_name: str
    def __init__(self, endpoint_name: _Optional[str] = ...) -> None: ...

class StopEndpointRequest(_message.Message):
    __slots__ = ("endpoint_name", "force")
    ENDPOINT_NAME_FIELD_NUMBER: _ClassVar[int]
    FORCE_FIELD_NUMBER: _ClassVar[int]
    endpoint_name: str
    force: bool
    def __init__(self, endpoint_name: _Optional[str] = ..., force: bool = ...) -> None: ...

class RestartEndpointRequest(_message.Message):
    __slots__ = ("endpoint_name",)
    ENDPOINT_NAME_FIELD_NUMBER: _ClassVar[int]
    endpoint_name: str
    def __init__(self, endpoint_name: _Optional[str] = ...) -> None: ...

class CleanStartRequest(_message.Message):
    __slots__ = ("endpoints",)
    ENDPOINTS_FIELD_NUMBER: _ClassVar[int]
    endpoints: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, endpoints: _Optional[_Iterable[str]] = ...) -> None: ...

class CleanStartResponse(_message.Message):
    __slots__ = ("success", "message", "processes_killed", "endpoints_started")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    PROCESSES_KILLED_FIELD_NUMBER: _ClassVar[int]
    ENDPOINTS_STARTED_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    processes_killed: int
    endpoints_started: int
    def __init__(self, success: bool = ..., message: _Optional[str] = ..., processes_killed: _Optional[int] = ..., endpoints_started: _Optional[int] = ...) -> None: ...

class PhaseChangeRequest(_message.Message):
    __slots__ = ("change_type", "target_endpoint", "await_healthy", "timeout_s")
    CHANGE_TYPE_FIELD_NUMBER: _ClassVar[int]
    TARGET_ENDPOINT_FIELD_NUMBER: _ClassVar[int]
    AWAIT_HEALTHY_FIELD_NUMBER: _ClassVar[int]
    TIMEOUT_S_FIELD_NUMBER: _ClassVar[int]
    change_type: str
    target_endpoint: str
    await_healthy: bool
    timeout_s: float
    def __init__(self, change_type: _Optional[str] = ..., target_endpoint: _Optional[str] = ..., await_healthy: bool = ..., timeout_s: _Optional[float] = ...) -> None: ...

class PhaseChangeResponse(_message.Message):
    __slots__ = ("converged", "status", "duration_ms", "change_type", "target_endpoint", "error_message", "otel_trace_id")
    CONVERGED_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    CHANGE_TYPE_FIELD_NUMBER: _ClassVar[int]
    TARGET_ENDPOINT_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    OTEL_TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    converged: bool
    status: str
    duration_ms: int
    change_type: str
    target_endpoint: str
    error_message: str
    otel_trace_id: str
    def __init__(self, converged: bool = ..., status: _Optional[str] = ..., duration_ms: _Optional[int] = ..., change_type: _Optional[str] = ..., target_endpoint: _Optional[str] = ..., error_message: _Optional[str] = ..., otel_trace_id: _Optional[str] = ...) -> None: ...

class PhaseChangeProfile(_message.Message):
    __slots__ = ("change_type", "sample_count", "total_duration_ms", "min_duration_ms", "max_duration_ms", "avg_duration_ms", "failures", "failure_rate", "has_statistical_power")
    CHANGE_TYPE_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_COUNT_FIELD_NUMBER: _ClassVar[int]
    TOTAL_DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    MIN_DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    MAX_DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    AVG_DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    FAILURES_FIELD_NUMBER: _ClassVar[int]
    FAILURE_RATE_FIELD_NUMBER: _ClassVar[int]
    HAS_STATISTICAL_POWER_FIELD_NUMBER: _ClassVar[int]
    change_type: str
    sample_count: int
    total_duration_ms: int
    min_duration_ms: int
    max_duration_ms: int
    avg_duration_ms: float
    failures: int
    failure_rate: float
    has_statistical_power: bool
    def __init__(self, change_type: _Optional[str] = ..., sample_count: _Optional[int] = ..., total_duration_ms: _Optional[int] = ..., min_duration_ms: _Optional[int] = ..., max_duration_ms: _Optional[int] = ..., avg_duration_ms: _Optional[float] = ..., failures: _Optional[int] = ..., failure_rate: _Optional[float] = ..., has_statistical_power: bool = ...) -> None: ...

class PhaseChangeProfilesResponse(_message.Message):
    __slots__ = ("profiles",)
    PROFILES_FIELD_NUMBER: _ClassVar[int]
    profiles: _containers.RepeatedCompositeFieldContainer[PhaseChangeProfile]
    def __init__(self, profiles: _Optional[_Iterable[_Union[PhaseChangeProfile, _Mapping]]] = ...) -> None: ...

class ActivePhaseChange(_message.Message):
    __slots__ = ("change_type", "status", "target_endpoint", "progress_pct", "started_at", "otel_trace_id")
    CHANGE_TYPE_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    TARGET_ENDPOINT_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_PCT_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    OTEL_TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    change_type: str
    status: str
    target_endpoint: str
    progress_pct: int
    started_at: str
    otel_trace_id: str
    def __init__(self, change_type: _Optional[str] = ..., status: _Optional[str] = ..., target_endpoint: _Optional[str] = ..., progress_pct: _Optional[int] = ..., started_at: _Optional[str] = ..., otel_trace_id: _Optional[str] = ...) -> None: ...

class ActivePhaseChangesResponse(_message.Message):
    __slots__ = ("changes",)
    CHANGES_FIELD_NUMBER: _ClassVar[int]
    changes: _containers.RepeatedCompositeFieldContainer[ActivePhaseChange]
    def __init__(self, changes: _Optional[_Iterable[_Union[ActivePhaseChange, _Mapping]]] = ...) -> None: ...

class EndpointResponse(_message.Message):
    __slots__ = ("success", "message")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    def __init__(self, success: bool = ..., message: _Optional[str] = ...) -> None: ...

class EnsureEndpointResponse(_message.Message):
    __slots__ = ("healthy", "status", "port", "gpu_ids", "message")
    HEALTHY_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    PORT_FIELD_NUMBER: _ClassVar[int]
    GPU_IDS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    healthy: bool
    status: str
    port: int
    gpu_ids: _containers.RepeatedScalarFieldContainer[int]
    message: str
    def __init__(self, healthy: bool = ..., status: _Optional[str] = ..., port: _Optional[int] = ..., gpu_ids: _Optional[_Iterable[int]] = ..., message: _Optional[str] = ...) -> None: ...

class CompleteRequest(_message.Message):
    __slots__ = ("agent_alias", "prompt", "system_prompt", "max_tokens", "temperature", "priority", "technique", "timezone", "clock_json")
    AGENT_ALIAS_FIELD_NUMBER: _ClassVar[int]
    PROMPT_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_PROMPT_FIELD_NUMBER: _ClassVar[int]
    MAX_TOKENS_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_FIELD_NUMBER: _ClassVar[int]
    PRIORITY_FIELD_NUMBER: _ClassVar[int]
    TECHNIQUE_FIELD_NUMBER: _ClassVar[int]
    TIMEZONE_FIELD_NUMBER: _ClassVar[int]
    CLOCK_JSON_FIELD_NUMBER: _ClassVar[int]
    agent_alias: str
    prompt: str
    system_prompt: str
    max_tokens: int
    temperature: float
    priority: str
    technique: str
    timezone: str
    clock_json: str
    def __init__(self, agent_alias: _Optional[str] = ..., prompt: _Optional[str] = ..., system_prompt: _Optional[str] = ..., max_tokens: _Optional[int] = ..., temperature: _Optional[float] = ..., priority: _Optional[str] = ..., technique: _Optional[str] = ..., timezone: _Optional[str] = ..., clock_json: _Optional[str] = ...) -> None: ...

class CompleteResponse(_message.Message):
    __slots__ = ("text", "tokens_used", "latency_ms", "model", "job_id")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    TOKENS_USED_FIELD_NUMBER: _ClassVar[int]
    LATENCY_MS_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    text: str
    tokens_used: int
    latency_ms: float
    model: str
    job_id: str
    def __init__(self, text: _Optional[str] = ..., tokens_used: _Optional[int] = ..., latency_ms: _Optional[float] = ..., model: _Optional[str] = ..., job_id: _Optional[str] = ...) -> None: ...

class SubmitJobRequest(_message.Message):
    __slots__ = ("agent_alias", "prompt", "system_prompt", "max_tokens", "temperature", "priority")
    AGENT_ALIAS_FIELD_NUMBER: _ClassVar[int]
    PROMPT_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_PROMPT_FIELD_NUMBER: _ClassVar[int]
    MAX_TOKENS_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_FIELD_NUMBER: _ClassVar[int]
    PRIORITY_FIELD_NUMBER: _ClassVar[int]
    ASYNC_FIELD_NUMBER: _ClassVar[int]
    agent_alias: str
    prompt: str
    system_prompt: str
    max_tokens: int
    temperature: float
    priority: str
    def __init__(self, agent_alias: _Optional[str] = ..., prompt: _Optional[str] = ..., system_prompt: _Optional[str] = ..., max_tokens: _Optional[int] = ..., temperature: _Optional[float] = ..., priority: _Optional[str] = ..., **kwargs) -> None: ...

class SubmitJobResponse(_message.Message):
    __slots__ = ("job_id", "status")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    status: str
    def __init__(self, job_id: _Optional[str] = ..., status: _Optional[str] = ...) -> None: ...

class GetJobResultRequest(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...

class GetJobResultResponse(_message.Message):
    __slots__ = ("job_id", "status", "text", "tokens_used", "latency_ms", "error")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    TOKENS_USED_FIELD_NUMBER: _ClassVar[int]
    LATENCY_MS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    status: str
    text: str
    tokens_used: int
    latency_ms: float
    error: str
    def __init__(self, job_id: _Optional[str] = ..., status: _Optional[str] = ..., text: _Optional[str] = ..., tokens_used: _Optional[int] = ..., latency_ms: _Optional[float] = ..., error: _Optional[str] = ...) -> None: ...

class SchedulerStatusResponse(_message.Message):
    __slots__ = ("queue_depth", "active_jobs", "avg_latency_ms", "jobs_by_priority")
    class JobsByPriorityEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    QUEUE_DEPTH_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_JOBS_FIELD_NUMBER: _ClassVar[int]
    AVG_LATENCY_MS_FIELD_NUMBER: _ClassVar[int]
    JOBS_BY_PRIORITY_FIELD_NUMBER: _ClassVar[int]
    queue_depth: int
    active_jobs: int
    avg_latency_ms: float
    jobs_by_priority: _containers.ScalarMap[str, int]
    def __init__(self, queue_depth: _Optional[int] = ..., active_jobs: _Optional[int] = ..., avg_latency_ms: _Optional[float] = ..., jobs_by_priority: _Optional[_Mapping[str, int]] = ...) -> None: ...

class XAIBudgetResponse(_message.Message):
    __slots__ = ("daily_used", "daily_limit", "weekly_used", "weekly_limit", "reset_at")
    DAILY_USED_FIELD_NUMBER: _ClassVar[int]
    DAILY_LIMIT_FIELD_NUMBER: _ClassVar[int]
    WEEKLY_USED_FIELD_NUMBER: _ClassVar[int]
    WEEKLY_LIMIT_FIELD_NUMBER: _ClassVar[int]
    RESET_AT_FIELD_NUMBER: _ClassVar[int]
    daily_used: int
    daily_limit: int
    weekly_used: int
    weekly_limit: int
    reset_at: str
    def __init__(self, daily_used: _Optional[int] = ..., daily_limit: _Optional[int] = ..., weekly_used: _Optional[int] = ..., weekly_limit: _Optional[int] = ..., reset_at: _Optional[str] = ...) -> None: ...

class SwarmStreamRequest(_message.Message):
    __slots__ = ("domain", "context", "roles", "clt")
    DOMAIN_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    ROLES_FIELD_NUMBER: _ClassVar[int]
    CLT_FIELD_NUMBER: _ClassVar[int]
    domain: str
    context: str
    roles: _containers.RepeatedScalarFieldContainer[str]
    clt: bool
    def __init__(self, domain: _Optional[str] = ..., context: _Optional[str] = ..., roles: _Optional[_Iterable[str]] = ..., clt: bool = ...) -> None: ...

class SwarmEvent(_message.Message):
    __slots__ = ("type", "timestamp_ms", "agent", "progress", "message", "data")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        QUEUED: _ClassVar[SwarmEvent.Type]
        WAITING_FOR_BACKENDS: _ClassVar[SwarmEvent.Type]
        STARTED: _ClassVar[SwarmEvent.Type]
        AGENT_STARTED: _ClassVar[SwarmEvent.Type]
        AGENT_COMPLETED: _ClassVar[SwarmEvent.Type]
        AGENT_FAILED: _ClassVar[SwarmEvent.Type]
        SYNTHESIS: _ClassVar[SwarmEvent.Type]
        COMPLETED: _ClassVar[SwarmEvent.Type]
        FAILED: _ClassVar[SwarmEvent.Type]
    QUEUED: SwarmEvent.Type
    WAITING_FOR_BACKENDS: SwarmEvent.Type
    STARTED: SwarmEvent.Type
    AGENT_STARTED: SwarmEvent.Type
    AGENT_COMPLETED: SwarmEvent.Type
    AGENT_FAILED: SwarmEvent.Type
    SYNTHESIS: SwarmEvent.Type
    COMPLETED: SwarmEvent.Type
    FAILED: SwarmEvent.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    AGENT_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    type: SwarmEvent.Type
    timestamp_ms: int
    agent: str
    progress: float
    message: str
    data: bytes
    def __init__(self, type: _Optional[_Union[SwarmEvent.Type, str]] = ..., timestamp_ms: _Optional[int] = ..., agent: _Optional[str] = ..., progress: _Optional[float] = ..., message: _Optional[str] = ..., data: _Optional[bytes] = ...) -> None: ...

class SwarmResult(_message.Message):
    __slots__ = ("results", "saved_path", "total_agents", "completed_agents", "failed_agents", "total_duration_ms")
    class ResultsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: bytes
        def __init__(self, key: _Optional[str] = ..., value: _Optional[bytes] = ...) -> None: ...
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    SAVED_PATH_FIELD_NUMBER: _ClassVar[int]
    TOTAL_AGENTS_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_AGENTS_FIELD_NUMBER: _ClassVar[int]
    FAILED_AGENTS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    results: _containers.ScalarMap[str, bytes]
    saved_path: str
    total_agents: int
    completed_agents: int
    failed_agents: int
    total_duration_ms: int
    def __init__(self, results: _Optional[_Mapping[str, bytes]] = ..., saved_path: _Optional[str] = ..., total_agents: _Optional[int] = ..., completed_agents: _Optional[int] = ..., failed_agents: _Optional[int] = ..., total_duration_ms: _Optional[int] = ...) -> None: ...

class EvolutionStatusResponse(_message.Message):
    __slots__ = ("running", "cycles_completed", "total_improvement_pct", "current_agent", "next_agent", "mode", "last_cycle_timestamp_ms")
    RUNNING_FIELD_NUMBER: _ClassVar[int]
    CYCLES_COMPLETED_FIELD_NUMBER: _ClassVar[int]
    TOTAL_IMPROVEMENT_PCT_FIELD_NUMBER: _ClassVar[int]
    CURRENT_AGENT_FIELD_NUMBER: _ClassVar[int]
    NEXT_AGENT_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    LAST_CYCLE_TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    running: bool
    cycles_completed: int
    total_improvement_pct: float
    current_agent: str
    next_agent: str
    mode: str
    last_cycle_timestamp_ms: int
    def __init__(self, running: bool = ..., cycles_completed: _Optional[int] = ..., total_improvement_pct: _Optional[float] = ..., current_agent: _Optional[str] = ..., next_agent: _Optional[str] = ..., mode: _Optional[str] = ..., last_cycle_timestamp_ms: _Optional[int] = ...) -> None: ...

class TriggerEvolutionRequest(_message.Message):
    __slots__ = ("agent_id",)
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    agent_id: str
    def __init__(self, agent_id: _Optional[str] = ...) -> None: ...

class EvolutionCycleResponse(_message.Message):
    __slots__ = ("success", "improvement_pct", "duration_ms", "agent_id", "version_id")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    IMPROVEMENT_PCT_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_ID_FIELD_NUMBER: _ClassVar[int]
    success: bool
    improvement_pct: float
    duration_ms: int
    agent_id: str
    version_id: str
    def __init__(self, success: bool = ..., improvement_pct: _Optional[float] = ..., duration_ms: _Optional[int] = ..., agent_id: _Optional[str] = ..., version_id: _Optional[str] = ...) -> None: ...

class CognitionStatusResponse(_message.Message):
    __slots__ = ("running", "cycles_completed", "last_cycle_timestamp_ms", "current_task")
    RUNNING_FIELD_NUMBER: _ClassVar[int]
    CYCLES_COMPLETED_FIELD_NUMBER: _ClassVar[int]
    LAST_CYCLE_TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_TASK_FIELD_NUMBER: _ClassVar[int]
    running: bool
    cycles_completed: int
    last_cycle_timestamp_ms: int
    current_task: str
    def __init__(self, running: bool = ..., cycles_completed: _Optional[int] = ..., last_cycle_timestamp_ms: _Optional[int] = ..., current_task: _Optional[str] = ...) -> None: ...

class ThoughtMessage(_message.Message):
    __slots__ = ("id", "thought_type", "title", "summary", "salience", "generation", "timestamp_ms", "note_path")
    ID_FIELD_NUMBER: _ClassVar[int]
    THOUGHT_TYPE_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    SALIENCE_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    NOTE_PATH_FIELD_NUMBER: _ClassVar[int]
    id: str
    thought_type: str
    title: str
    summary: str
    salience: float
    generation: int
    timestamp_ms: int
    note_path: str
    def __init__(self, id: _Optional[str] = ..., thought_type: _Optional[str] = ..., title: _Optional[str] = ..., summary: _Optional[str] = ..., salience: _Optional[float] = ..., generation: _Optional[int] = ..., timestamp_ms: _Optional[int] = ..., note_path: _Optional[str] = ...) -> None: ...

class GetRecentThoughtsRequest(_message.Message):
    __slots__ = ("limit",)
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    limit: int
    def __init__(self, limit: _Optional[int] = ...) -> None: ...

class GetRecentThoughtsResponse(_message.Message):
    __slots__ = ("thoughts",)
    THOUGHTS_FIELD_NUMBER: _ClassVar[int]
    thoughts: _containers.RepeatedCompositeFieldContainer[ThoughtMessage]
    def __init__(self, thoughts: _Optional[_Iterable[_Union[ThoughtMessage, _Mapping]]] = ...) -> None: ...

class TriggerCognitionRequest(_message.Message):
    __slots__ = ("max_thoughts", "trigger_reason")
    MAX_THOUGHTS_FIELD_NUMBER: _ClassVar[int]
    TRIGGER_REASON_FIELD_NUMBER: _ClassVar[int]
    max_thoughts: int
    trigger_reason: str
    def __init__(self, max_thoughts: _Optional[int] = ..., trigger_reason: _Optional[str] = ...) -> None: ...

class TriggerCognitionResponse(_message.Message):
    __slots__ = ("success", "thoughts_generated", "patterns_detected", "connections_found", "curiosities_generated", "duration_ms", "error", "self_observations", "kb_path", "tokens_out")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    THOUGHTS_GENERATED_FIELD_NUMBER: _ClassVar[int]
    PATTERNS_DETECTED_FIELD_NUMBER: _ClassVar[int]
    CONNECTIONS_FOUND_FIELD_NUMBER: _ClassVar[int]
    CURIOSITIES_GENERATED_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    SELF_OBSERVATIONS_FIELD_NUMBER: _ClassVar[int]
    KB_PATH_FIELD_NUMBER: _ClassVar[int]
    TOKENS_OUT_FIELD_NUMBER: _ClassVar[int]
    success: bool
    thoughts_generated: int
    patterns_detected: int
    connections_found: int
    curiosities_generated: int
    duration_ms: int
    error: str
    self_observations: int
    kb_path: str
    tokens_out: int
    def __init__(self, success: bool = ..., thoughts_generated: _Optional[int] = ..., patterns_detected: _Optional[int] = ..., connections_found: _Optional[int] = ..., curiosities_generated: _Optional[int] = ..., duration_ms: _Optional[int] = ..., error: _Optional[str] = ..., self_observations: _Optional[int] = ..., kb_path: _Optional[str] = ..., tokens_out: _Optional[int] = ...) -> None: ...

class SelfObservationRequest(_message.Message):
    __slots__ = ("max_observations",)
    MAX_OBSERVATIONS_FIELD_NUMBER: _ClassVar[int]
    max_observations: int
    def __init__(self, max_observations: _Optional[int] = ...) -> None: ...

class SelfObservationResponse(_message.Message):
    __slots__ = ("success", "observations_generated", "duration_ms", "error", "observation_ids")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    OBSERVATIONS_GENERATED_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    OBSERVATION_IDS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    observations_generated: int
    duration_ms: int
    error: str
    observation_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, success: bool = ..., observations_generated: _Optional[int] = ..., duration_ms: _Optional[int] = ..., error: _Optional[str] = ..., observation_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class EngineAuditRequest(_message.Message):
    __slots__ = ("include_metrics",)
    INCLUDE_METRICS_FIELD_NUMBER: _ClassVar[int]
    include_metrics: bool
    def __init__(self, include_metrics: bool = ...) -> None: ...

class EngineAuditResponse(_message.Message):
    __slots__ = ("success", "observations_recorded", "anomalies_found", "duration_ms", "error", "anomaly_details")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    OBSERVATIONS_RECORDED_FIELD_NUMBER: _ClassVar[int]
    ANOMALIES_FOUND_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    ANOMALY_DETAILS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    observations_recorded: int
    anomalies_found: int
    duration_ms: int
    error: str
    anomaly_details: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, success: bool = ..., observations_recorded: _Optional[int] = ..., anomalies_found: _Optional[int] = ..., duration_ms: _Optional[int] = ..., error: _Optional[str] = ..., anomaly_details: _Optional[_Iterable[str]] = ...) -> None: ...

class CognitionActivityResponse(_message.Message):
    __slots__ = ("cognition_running", "cycles_completed", "last_cycle_timestamp_ms", "current_task", "thoughts_today", "active_thoughts")
    COGNITION_RUNNING_FIELD_NUMBER: _ClassVar[int]
    CYCLES_COMPLETED_FIELD_NUMBER: _ClassVar[int]
    LAST_CYCLE_TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_TASK_FIELD_NUMBER: _ClassVar[int]
    THOUGHTS_TODAY_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_THOUGHTS_FIELD_NUMBER: _ClassVar[int]
    cognition_running: bool
    cycles_completed: int
    last_cycle_timestamp_ms: int
    current_task: str
    thoughts_today: int
    active_thoughts: int
    def __init__(self, cognition_running: bool = ..., cycles_completed: _Optional[int] = ..., last_cycle_timestamp_ms: _Optional[int] = ..., current_task: _Optional[str] = ..., thoughts_today: _Optional[int] = ..., active_thoughts: _Optional[int] = ...) -> None: ...

class CognitionSurfaceRequest(_message.Message):
    __slots__ = ("window_days", "thought_limit", "stream")
    WINDOW_DAYS_FIELD_NUMBER: _ClassVar[int]
    THOUGHT_LIMIT_FIELD_NUMBER: _ClassVar[int]
    STREAM_FIELD_NUMBER: _ClassVar[int]
    window_days: int
    thought_limit: int
    stream: str
    def __init__(self, window_days: _Optional[int] = ..., thought_limit: _Optional[int] = ..., stream: _Optional[str] = ...) -> None: ...

class CognitionDayBucket(_message.Message):
    __slots__ = ("date", "thoughts", "cycles")
    DATE_FIELD_NUMBER: _ClassVar[int]
    THOUGHTS_FIELD_NUMBER: _ClassVar[int]
    CYCLES_FIELD_NUMBER: _ClassVar[int]
    date: str
    thoughts: int
    cycles: int
    def __init__(self, date: _Optional[str] = ..., thoughts: _Optional[int] = ..., cycles: _Optional[int] = ...) -> None: ...

class CognitionHourCell(_message.Message):
    __slots__ = ("weekday", "hour", "thoughts")
    WEEKDAY_FIELD_NUMBER: _ClassVar[int]
    HOUR_FIELD_NUMBER: _ClassVar[int]
    THOUGHTS_FIELD_NUMBER: _ClassVar[int]
    weekday: int
    hour: int
    thoughts: int
    def __init__(self, weekday: _Optional[int] = ..., hour: _Optional[int] = ..., thoughts: _Optional[int] = ...) -> None: ...

class CognitionStreamCount(_message.Message):
    __slots__ = ("id", "thoughts")
    ID_FIELD_NUMBER: _ClassVar[int]
    THOUGHTS_FIELD_NUMBER: _ClassVar[int]
    id: str
    thoughts: int
    def __init__(self, id: _Optional[str] = ..., thoughts: _Optional[int] = ...) -> None: ...

class CognitionSurfaceResponse(_message.Message):
    __slots__ = ("running", "cycles_completed", "cycles_in_window", "last_cycle_timestamp_ms", "current_task", "thoughts", "streams", "active_days", "thoughts_per_cycle", "concentration_stream", "concentration_pct", "reserve_tokens", "project", "unit", "recent", "top", "days", "hours", "stream_counts", "error")
    RUNNING_FIELD_NUMBER: _ClassVar[int]
    CYCLES_COMPLETED_FIELD_NUMBER: _ClassVar[int]
    CYCLES_IN_WINDOW_FIELD_NUMBER: _ClassVar[int]
    LAST_CYCLE_TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_TASK_FIELD_NUMBER: _ClassVar[int]
    THOUGHTS_FIELD_NUMBER: _ClassVar[int]
    STREAMS_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_DAYS_FIELD_NUMBER: _ClassVar[int]
    THOUGHTS_PER_CYCLE_FIELD_NUMBER: _ClassVar[int]
    CONCENTRATION_STREAM_FIELD_NUMBER: _ClassVar[int]
    CONCENTRATION_PCT_FIELD_NUMBER: _ClassVar[int]
    RESERVE_TOKENS_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    UNIT_FIELD_NUMBER: _ClassVar[int]
    RECENT_FIELD_NUMBER: _ClassVar[int]
    TOP_FIELD_NUMBER: _ClassVar[int]
    DAYS_FIELD_NUMBER: _ClassVar[int]
    HOURS_FIELD_NUMBER: _ClassVar[int]
    STREAM_COUNTS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    running: bool
    cycles_completed: int
    cycles_in_window: int
    last_cycle_timestamp_ms: int
    current_task: str
    thoughts: int
    streams: int
    active_days: int
    thoughts_per_cycle: float
    concentration_stream: str
    concentration_pct: float
    reserve_tokens: int
    project: str
    unit: str
    recent: _containers.RepeatedCompositeFieldContainer[ThoughtMessage]
    top: _containers.RepeatedCompositeFieldContainer[ThoughtMessage]
    days: _containers.RepeatedCompositeFieldContainer[CognitionDayBucket]
    hours: _containers.RepeatedCompositeFieldContainer[CognitionHourCell]
    stream_counts: _containers.RepeatedCompositeFieldContainer[CognitionStreamCount]
    error: str
    def __init__(self, running: bool = ..., cycles_completed: _Optional[int] = ..., cycles_in_window: _Optional[int] = ..., last_cycle_timestamp_ms: _Optional[int] = ..., current_task: _Optional[str] = ..., thoughts: _Optional[int] = ..., streams: _Optional[int] = ..., active_days: _Optional[int] = ..., thoughts_per_cycle: _Optional[float] = ..., concentration_stream: _Optional[str] = ..., concentration_pct: _Optional[float] = ..., reserve_tokens: _Optional[int] = ..., project: _Optional[str] = ..., unit: _Optional[str] = ..., recent: _Optional[_Iterable[_Union[ThoughtMessage, _Mapping]]] = ..., top: _Optional[_Iterable[_Union[ThoughtMessage, _Mapping]]] = ..., days: _Optional[_Iterable[_Union[CognitionDayBucket, _Mapping]]] = ..., hours: _Optional[_Iterable[_Union[CognitionHourCell, _Mapping]]] = ..., stream_counts: _Optional[_Iterable[_Union[CognitionStreamCount, _Mapping]]] = ..., error: _Optional[str] = ...) -> None: ...

class CognitionStreamRequest(_message.Message):
    __slots__ = ("buffer_size", "event_types")
    BUFFER_SIZE_FIELD_NUMBER: _ClassVar[int]
    EVENT_TYPES_FIELD_NUMBER: _ClassVar[int]
    buffer_size: int
    event_types: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, buffer_size: _Optional[int] = ..., event_types: _Optional[_Iterable[str]] = ...) -> None: ...

class CognitionEvent(_message.Message):
    __slots__ = ("type", "timestamp_ms", "thought_id", "thought_type", "title", "summary", "salience", "generation", "cycle_id", "thoughts_in_cycle", "error")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        CYCLE_START: _ClassVar[CognitionEvent.Type]
        THOUGHT: _ClassVar[CognitionEvent.Type]
        PATTERN: _ClassVar[CognitionEvent.Type]
        CONNECTION: _ClassVar[CognitionEvent.Type]
        CURIOSITY: _ClassVar[CognitionEvent.Type]
        SELF_OBSERVATION: _ClassVar[CognitionEvent.Type]
        ENGINE_AUDIT: _ClassVar[CognitionEvent.Type]
        CYCLE_END: _ClassVar[CognitionEvent.Type]
        ERROR: _ClassVar[CognitionEvent.Type]
    CYCLE_START: CognitionEvent.Type
    THOUGHT: CognitionEvent.Type
    PATTERN: CognitionEvent.Type
    CONNECTION: CognitionEvent.Type
    CURIOSITY: CognitionEvent.Type
    SELF_OBSERVATION: CognitionEvent.Type
    ENGINE_AUDIT: CognitionEvent.Type
    CYCLE_END: CognitionEvent.Type
    ERROR: CognitionEvent.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    THOUGHT_ID_FIELD_NUMBER: _ClassVar[int]
    THOUGHT_TYPE_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    SALIENCE_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    CYCLE_ID_FIELD_NUMBER: _ClassVar[int]
    THOUGHTS_IN_CYCLE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    type: CognitionEvent.Type
    timestamp_ms: int
    thought_id: str
    thought_type: str
    title: str
    summary: str
    salience: float
    generation: int
    cycle_id: str
    thoughts_in_cycle: int
    error: str
    def __init__(self, type: _Optional[_Union[CognitionEvent.Type, str]] = ..., timestamp_ms: _Optional[int] = ..., thought_id: _Optional[str] = ..., thought_type: _Optional[str] = ..., title: _Optional[str] = ..., summary: _Optional[str] = ..., salience: _Optional[float] = ..., generation: _Optional[int] = ..., cycle_id: _Optional[str] = ..., thoughts_in_cycle: _Optional[int] = ..., error: _Optional[str] = ...) -> None: ...

class EvolutionStreamRequest(_message.Message):
    __slots__ = ("agent_filter", "buffer_size")
    AGENT_FILTER_FIELD_NUMBER: _ClassVar[int]
    BUFFER_SIZE_FIELD_NUMBER: _ClassVar[int]
    agent_filter: str
    buffer_size: int
    def __init__(self, agent_filter: _Optional[str] = ..., buffer_size: _Optional[int] = ...) -> None: ...

class EvolutionEvent(_message.Message):
    __slots__ = ("type", "timestamp_ms", "agent_id", "version_id", "score", "improvement_pct", "details", "cycle_number", "merge_id", "error")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        CYCLE_START: _ClassVar[EvolutionEvent.Type]
        EVALUATION_START: _ClassVar[EvolutionEvent.Type]
        EVALUATION_DONE: _ClassVar[EvolutionEvent.Type]
        PROMOTION: _ClassVar[EvolutionEvent.Type]
        ROLLBACK: _ClassVar[EvolutionEvent.Type]
        MERGE_START: _ClassVar[EvolutionEvent.Type]
        MERGE_DONE: _ClassVar[EvolutionEvent.Type]
        TASK_IDEATION: _ClassVar[EvolutionEvent.Type]
        CALIBRATION: _ClassVar[EvolutionEvent.Type]
        CYCLE_END: _ClassVar[EvolutionEvent.Type]
        ERROR: _ClassVar[EvolutionEvent.Type]
    CYCLE_START: EvolutionEvent.Type
    EVALUATION_START: EvolutionEvent.Type
    EVALUATION_DONE: EvolutionEvent.Type
    PROMOTION: EvolutionEvent.Type
    ROLLBACK: EvolutionEvent.Type
    MERGE_START: EvolutionEvent.Type
    MERGE_DONE: EvolutionEvent.Type
    TASK_IDEATION: EvolutionEvent.Type
    CALIBRATION: EvolutionEvent.Type
    CYCLE_END: EvolutionEvent.Type
    ERROR: EvolutionEvent.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_ID_FIELD_NUMBER: _ClassVar[int]
    SCORE_FIELD_NUMBER: _ClassVar[int]
    IMPROVEMENT_PCT_FIELD_NUMBER: _ClassVar[int]
    DETAILS_FIELD_NUMBER: _ClassVar[int]
    CYCLE_NUMBER_FIELD_NUMBER: _ClassVar[int]
    MERGE_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    type: EvolutionEvent.Type
    timestamp_ms: int
    agent_id: str
    version_id: str
    score: float
    improvement_pct: float
    details: str
    cycle_number: int
    merge_id: str
    error: str
    def __init__(self, type: _Optional[_Union[EvolutionEvent.Type, str]] = ..., timestamp_ms: _Optional[int] = ..., agent_id: _Optional[str] = ..., version_id: _Optional[str] = ..., score: _Optional[float] = ..., improvement_pct: _Optional[float] = ..., details: _Optional[str] = ..., cycle_number: _Optional[int] = ..., merge_id: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class ActivityStreamRequest(_message.Message):
    __slots__ = ("buffer_size", "domains")
    BUFFER_SIZE_FIELD_NUMBER: _ClassVar[int]
    DOMAINS_FIELD_NUMBER: _ClassVar[int]
    buffer_size: int
    domains: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, buffer_size: _Optional[int] = ..., domains: _Optional[_Iterable[str]] = ...) -> None: ...

class ActivityEvent(_message.Message):
    __slots__ = ("event_type", "timestamp_ms", "source", "domain", "title", "summary", "data")
    EVENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    DOMAIN_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    event_type: str
    timestamp_ms: int
    source: str
    domain: str
    title: str
    summary: str
    data: bytes
    def __init__(self, event_type: _Optional[str] = ..., timestamp_ms: _Optional[int] = ..., source: _Optional[str] = ..., domain: _Optional[str] = ..., title: _Optional[str] = ..., summary: _Optional[str] = ..., data: _Optional[bytes] = ...) -> None: ...

class BeginWorkloadRequest(_message.Message):
    __slots__ = ("workload_id", "workload_type", "required_capabilities", "priority", "estimated_duration_s", "estimated_memory_mb", "preemptible")
    WORKLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    WORKLOAD_TYPE_FIELD_NUMBER: _ClassVar[int]
    REQUIRED_CAPABILITIES_FIELD_NUMBER: _ClassVar[int]
    PRIORITY_FIELD_NUMBER: _ClassVar[int]
    ESTIMATED_DURATION_S_FIELD_NUMBER: _ClassVar[int]
    ESTIMATED_MEMORY_MB_FIELD_NUMBER: _ClassVar[int]
    PREEMPTIBLE_FIELD_NUMBER: _ClassVar[int]
    workload_id: str
    workload_type: WorkloadType
    required_capabilities: _containers.RepeatedScalarFieldContainer[str]
    priority: str
    estimated_duration_s: int
    estimated_memory_mb: int
    preemptible: bool
    def __init__(self, workload_id: _Optional[str] = ..., workload_type: _Optional[_Union[WorkloadType, str]] = ..., required_capabilities: _Optional[_Iterable[str]] = ..., priority: _Optional[str] = ..., estimated_duration_s: _Optional[int] = ..., estimated_memory_mb: _Optional[int] = ..., preemptible: bool = ...) -> None: ...

class EndpointAllocationInfo(_message.Message):
    __slots__ = ("endpoint_name", "capability", "port", "healthy", "model_id")
    ENDPOINT_NAME_FIELD_NUMBER: _ClassVar[int]
    CAPABILITY_FIELD_NUMBER: _ClassVar[int]
    PORT_FIELD_NUMBER: _ClassVar[int]
    HEALTHY_FIELD_NUMBER: _ClassVar[int]
    MODEL_ID_FIELD_NUMBER: _ClassVar[int]
    endpoint_name: str
    capability: str
    port: int
    healthy: bool
    model_id: str
    def __init__(self, endpoint_name: _Optional[str] = ..., capability: _Optional[str] = ..., port: _Optional[int] = ..., healthy: bool = ..., model_id: _Optional[str] = ...) -> None: ...

class BeginWorkloadResponse(_message.Message):
    __slots__ = ("success", "workload_id", "allocated_endpoints", "evicted_endpoints", "restore_plan", "error", "wait_time_ms")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    WORKLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    ALLOCATED_ENDPOINTS_FIELD_NUMBER: _ClassVar[int]
    EVICTED_ENDPOINTS_FIELD_NUMBER: _ClassVar[int]
    RESTORE_PLAN_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    WAIT_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    workload_id: str
    allocated_endpoints: _containers.RepeatedCompositeFieldContainer[EndpointAllocationInfo]
    evicted_endpoints: _containers.RepeatedScalarFieldContainer[str]
    restore_plan: _containers.RepeatedScalarFieldContainer[str]
    error: str
    wait_time_ms: int
    def __init__(self, success: bool = ..., workload_id: _Optional[str] = ..., allocated_endpoints: _Optional[_Iterable[_Union[EndpointAllocationInfo, _Mapping]]] = ..., evicted_endpoints: _Optional[_Iterable[str]] = ..., restore_plan: _Optional[_Iterable[str]] = ..., error: _Optional[str] = ..., wait_time_ms: _Optional[int] = ...) -> None: ...

class CompleteWorkloadRequest(_message.Message):
    __slots__ = ("workload_id",)
    WORKLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    workload_id: str
    def __init__(self, workload_id: _Optional[str] = ...) -> None: ...

class ActiveWorkloadInfo(_message.Message):
    __slots__ = ("workload_id", "workload_type", "priority", "capabilities", "elapsed_s", "estimated_duration_s", "is_overdue", "endpoints")
    WORKLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    WORKLOAD_TYPE_FIELD_NUMBER: _ClassVar[int]
    PRIORITY_FIELD_NUMBER: _ClassVar[int]
    CAPABILITIES_FIELD_NUMBER: _ClassVar[int]
    ELAPSED_S_FIELD_NUMBER: _ClassVar[int]
    ESTIMATED_DURATION_S_FIELD_NUMBER: _ClassVar[int]
    IS_OVERDUE_FIELD_NUMBER: _ClassVar[int]
    ENDPOINTS_FIELD_NUMBER: _ClassVar[int]
    workload_id: str
    workload_type: str
    priority: str
    capabilities: _containers.RepeatedScalarFieldContainer[str]
    elapsed_s: float
    estimated_duration_s: int
    is_overdue: bool
    endpoints: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, workload_id: _Optional[str] = ..., workload_type: _Optional[str] = ..., priority: _Optional[str] = ..., capabilities: _Optional[_Iterable[str]] = ..., elapsed_s: _Optional[float] = ..., estimated_duration_s: _Optional[int] = ..., is_overdue: bool = ..., endpoints: _Optional[_Iterable[str]] = ...) -> None: ...

class GetActiveWorkloadsResponse(_message.Message):
    __slots__ = ("workloads",)
    WORKLOADS_FIELD_NUMBER: _ClassVar[int]
    workloads: _containers.RepeatedCompositeFieldContainer[ActiveWorkloadInfo]
    def __init__(self, workloads: _Optional[_Iterable[_Union[ActiveWorkloadInfo, _Mapping]]] = ...) -> None: ...

class EmbedTextsRequest(_message.Message):
    __slots__ = ("texts", "model", "workload_id")
    TEXTS_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    WORKLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    texts: _containers.RepeatedScalarFieldContainer[str]
    model: str
    workload_id: str
    def __init__(self, texts: _Optional[_Iterable[str]] = ..., model: _Optional[str] = ..., workload_id: _Optional[str] = ...) -> None: ...

class EmbeddingVector(_message.Message):
    __slots__ = ("values",)
    VALUES_FIELD_NUMBER: _ClassVar[int]
    values: _containers.RepeatedScalarFieldContainer[float]
    def __init__(self, values: _Optional[_Iterable[float]] = ...) -> None: ...

class EmbedTextsResponse(_message.Message):
    __slots__ = ("embeddings", "model_used", "latency_ms")
    EMBEDDINGS_FIELD_NUMBER: _ClassVar[int]
    MODEL_USED_FIELD_NUMBER: _ClassVar[int]
    LATENCY_MS_FIELD_NUMBER: _ClassVar[int]
    embeddings: _containers.RepeatedCompositeFieldContainer[EmbeddingVector]
    model_used: str
    latency_ms: int
    def __init__(self, embeddings: _Optional[_Iterable[_Union[EmbeddingVector, _Mapping]]] = ..., model_used: _Optional[str] = ..., latency_ms: _Optional[int] = ...) -> None: ...

class SemanticSearchRequest(_message.Message):
    __slots__ = ("query", "collection", "limit", "min_score", "use_maxsim", "content_type")
    QUERY_FIELD_NUMBER: _ClassVar[int]
    COLLECTION_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    MIN_SCORE_FIELD_NUMBER: _ClassVar[int]
    USE_MAXSIM_FIELD_NUMBER: _ClassVar[int]
    CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    query: str
    collection: str
    limit: int
    min_score: float
    use_maxsim: bool
    content_type: str
    def __init__(self, query: _Optional[str] = ..., collection: _Optional[str] = ..., limit: _Optional[int] = ..., min_score: _Optional[float] = ..., use_maxsim: bool = ..., content_type: _Optional[str] = ...) -> None: ...

class SearchResult(_message.Message):
    __slots__ = ("path", "title", "score", "snippet", "chunk_id", "content_type")
    PATH_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    SCORE_FIELD_NUMBER: _ClassVar[int]
    SNIPPET_FIELD_NUMBER: _ClassVar[int]
    CHUNK_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    path: str
    title: str
    score: float
    snippet: str
    chunk_id: str
    content_type: str
    def __init__(self, path: _Optional[str] = ..., title: _Optional[str] = ..., score: _Optional[float] = ..., snippet: _Optional[str] = ..., chunk_id: _Optional[str] = ..., content_type: _Optional[str] = ...) -> None: ...

class SemanticSearchResponse(_message.Message):
    __slots__ = ("results", "total", "collection", "embedding_model", "latency_ms")
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    COLLECTION_FIELD_NUMBER: _ClassVar[int]
    EMBEDDING_MODEL_FIELD_NUMBER: _ClassVar[int]
    LATENCY_MS_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[SearchResult]
    total: int
    collection: str
    embedding_model: str
    latency_ms: int
    def __init__(self, results: _Optional[_Iterable[_Union[SearchResult, _Mapping]]] = ..., total: _Optional[int] = ..., collection: _Optional[str] = ..., embedding_model: _Optional[str] = ..., latency_ms: _Optional[int] = ...) -> None: ...

class SemanticSearchEvent(_message.Message):
    __slots__ = ("phase", "message", "progress_pct", "timestamp_ms", "response", "error", "guru_code")
    class Phase(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        PHASE_UNSPECIFIED: _ClassVar[SemanticSearchEvent.Phase]
        REQUESTING_GPU: _ClassVar[SemanticSearchEvent.Phase]
        EVICTING_ENDPOINTS: _ClassVar[SemanticSearchEvent.Phase]
        LOADING_MODEL: _ClassVar[SemanticSearchEvent.Phase]
        SEARCHING: _ClassVar[SemanticSearchEvent.Phase]
        COMPLETE: _ClassVar[SemanticSearchEvent.Phase]
        ERROR: _ClassVar[SemanticSearchEvent.Phase]
    PHASE_UNSPECIFIED: SemanticSearchEvent.Phase
    REQUESTING_GPU: SemanticSearchEvent.Phase
    EVICTING_ENDPOINTS: SemanticSearchEvent.Phase
    LOADING_MODEL: SemanticSearchEvent.Phase
    SEARCHING: SemanticSearchEvent.Phase
    COMPLETE: SemanticSearchEvent.Phase
    ERROR: SemanticSearchEvent.Phase
    PHASE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_PCT_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    RESPONSE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    GURU_CODE_FIELD_NUMBER: _ClassVar[int]
    phase: SemanticSearchEvent.Phase
    message: str
    progress_pct: int
    timestamp_ms: int
    response: SemanticSearchResponse
    error: str
    guru_code: str
    def __init__(self, phase: _Optional[_Union[SemanticSearchEvent.Phase, str]] = ..., message: _Optional[str] = ..., progress_pct: _Optional[int] = ..., timestamp_ms: _Optional[int] = ..., response: _Optional[_Union[SemanticSearchResponse, _Mapping]] = ..., error: _Optional[str] = ..., guru_code: _Optional[str] = ...) -> None: ...

class SearchFlowRequest(_message.Message):
    __slots__ = ("query", "skip_grok", "bm25_limit", "vector_limit", "web_limit")
    QUERY_FIELD_NUMBER: _ClassVar[int]
    SKIP_GROK_FIELD_NUMBER: _ClassVar[int]
    BM25_LIMIT_FIELD_NUMBER: _ClassVar[int]
    VECTOR_LIMIT_FIELD_NUMBER: _ClassVar[int]
    WEB_LIMIT_FIELD_NUMBER: _ClassVar[int]
    query: str
    skip_grok: bool
    bm25_limit: int
    vector_limit: int
    web_limit: int
    def __init__(self, query: _Optional[str] = ..., skip_grok: bool = ..., bm25_limit: _Optional[int] = ..., vector_limit: _Optional[int] = ..., web_limit: _Optional[int] = ...) -> None: ...

class WebSearchResult(_message.Message):
    __slots__ = ("title", "url", "snippet", "source")
    TITLE_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    SNIPPET_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    title: str
    url: str
    snippet: str
    source: str
    def __init__(self, title: _Optional[str] = ..., url: _Optional[str] = ..., snippet: _Optional[str] = ..., source: _Optional[str] = ...) -> None: ...

class SearchFlowResult(_message.Message):
    __slots__ = ("bm25_results", "vector_results", "web_results", "local_synthesis", "local_model", "local_latency_ms", "grok_synthesis", "grok_latency_ms", "kb_path")
    BM25_RESULTS_FIELD_NUMBER: _ClassVar[int]
    VECTOR_RESULTS_FIELD_NUMBER: _ClassVar[int]
    WEB_RESULTS_FIELD_NUMBER: _ClassVar[int]
    LOCAL_SYNTHESIS_FIELD_NUMBER: _ClassVar[int]
    LOCAL_MODEL_FIELD_NUMBER: _ClassVar[int]
    LOCAL_LATENCY_MS_FIELD_NUMBER: _ClassVar[int]
    GROK_SYNTHESIS_FIELD_NUMBER: _ClassVar[int]
    GROK_LATENCY_MS_FIELD_NUMBER: _ClassVar[int]
    KB_PATH_FIELD_NUMBER: _ClassVar[int]
    bm25_results: _containers.RepeatedCompositeFieldContainer[SearchResult]
    vector_results: _containers.RepeatedCompositeFieldContainer[SearchResult]
    web_results: _containers.RepeatedCompositeFieldContainer[WebSearchResult]
    local_synthesis: str
    local_model: str
    local_latency_ms: int
    grok_synthesis: str
    grok_latency_ms: int
    kb_path: str
    def __init__(self, bm25_results: _Optional[_Iterable[_Union[SearchResult, _Mapping]]] = ..., vector_results: _Optional[_Iterable[_Union[SearchResult, _Mapping]]] = ..., web_results: _Optional[_Iterable[_Union[WebSearchResult, _Mapping]]] = ..., local_synthesis: _Optional[str] = ..., local_model: _Optional[str] = ..., local_latency_ms: _Optional[int] = ..., grok_synthesis: _Optional[str] = ..., grok_latency_ms: _Optional[int] = ..., kb_path: _Optional[str] = ...) -> None: ...

class SearchFlowEvent(_message.Message):
    __slots__ = ("type", "timestamp_ms", "progress", "message", "result", "error", "guru_code")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        TYPE_UNSPECIFIED: _ClassVar[SearchFlowEvent.Type]
        QUEUED: _ClassVar[SearchFlowEvent.Type]
        BM25_STARTED: _ClassVar[SearchFlowEvent.Type]
        BM25_COMPLETED: _ClassVar[SearchFlowEvent.Type]
        VECTOR_STARTED: _ClassVar[SearchFlowEvent.Type]
        VECTOR_EVICTING: _ClassVar[SearchFlowEvent.Type]
        VECTOR_LOADING: _ClassVar[SearchFlowEvent.Type]
        VECTOR_COMPLETED: _ClassVar[SearchFlowEvent.Type]
        WEB_STARTED: _ClassVar[SearchFlowEvent.Type]
        WEB_COMPLETED: _ClassVar[SearchFlowEvent.Type]
        INSTRUCT_RESTORING: _ClassVar[SearchFlowEvent.Type]
        INSTRUCT_READY: _ClassVar[SearchFlowEvent.Type]
        LOCAL_SYNTHESIS_STARTED: _ClassVar[SearchFlowEvent.Type]
        LOCAL_SYNTHESIS_COMPLETED: _ClassVar[SearchFlowEvent.Type]
        GROK_SYNTHESIS_STARTED: _ClassVar[SearchFlowEvent.Type]
        GROK_SYNTHESIS_COMPLETED: _ClassVar[SearchFlowEvent.Type]
        SYNTHESIS_MERGED: _ClassVar[SearchFlowEvent.Type]
        KB_WRITE: _ClassVar[SearchFlowEvent.Type]
        COMPLETED: _ClassVar[SearchFlowEvent.Type]
        FAILED: _ClassVar[SearchFlowEvent.Type]
    TYPE_UNSPECIFIED: SearchFlowEvent.Type
    QUEUED: SearchFlowEvent.Type
    BM25_STARTED: SearchFlowEvent.Type
    BM25_COMPLETED: SearchFlowEvent.Type
    VECTOR_STARTED: SearchFlowEvent.Type
    VECTOR_EVICTING: SearchFlowEvent.Type
    VECTOR_LOADING: SearchFlowEvent.Type
    VECTOR_COMPLETED: SearchFlowEvent.Type
    WEB_STARTED: SearchFlowEvent.Type
    WEB_COMPLETED: SearchFlowEvent.Type
    INSTRUCT_RESTORING: SearchFlowEvent.Type
    INSTRUCT_READY: SearchFlowEvent.Type
    LOCAL_SYNTHESIS_STARTED: SearchFlowEvent.Type
    LOCAL_SYNTHESIS_COMPLETED: SearchFlowEvent.Type
    GROK_SYNTHESIS_STARTED: SearchFlowEvent.Type
    GROK_SYNTHESIS_COMPLETED: SearchFlowEvent.Type
    SYNTHESIS_MERGED: SearchFlowEvent.Type
    KB_WRITE: SearchFlowEvent.Type
    COMPLETED: SearchFlowEvent.Type
    FAILED: SearchFlowEvent.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    GURU_CODE_FIELD_NUMBER: _ClassVar[int]
    type: SearchFlowEvent.Type
    timestamp_ms: int
    progress: float
    message: str
    result: SearchFlowResult
    error: str
    guru_code: str
    def __init__(self, type: _Optional[_Union[SearchFlowEvent.Type, str]] = ..., timestamp_ms: _Optional[int] = ..., progress: _Optional[float] = ..., message: _Optional[str] = ..., result: _Optional[_Union[SearchFlowResult, _Mapping]] = ..., error: _Optional[str] = ..., guru_code: _Optional[str] = ...) -> None: ...

class ResearchFlowRequest(_message.Message):
    __slots__ = ("query", "max_passes", "drift_threshold", "bm25_limit", "vector_limit", "web_limit")
    QUERY_FIELD_NUMBER: _ClassVar[int]
    MAX_PASSES_FIELD_NUMBER: _ClassVar[int]
    DRIFT_THRESHOLD_FIELD_NUMBER: _ClassVar[int]
    BM25_LIMIT_FIELD_NUMBER: _ClassVar[int]
    VECTOR_LIMIT_FIELD_NUMBER: _ClassVar[int]
    WEB_LIMIT_FIELD_NUMBER: _ClassVar[int]
    query: str
    max_passes: int
    drift_threshold: float
    bm25_limit: int
    vector_limit: int
    web_limit: int
    def __init__(self, query: _Optional[str] = ..., max_passes: _Optional[int] = ..., drift_threshold: _Optional[float] = ..., bm25_limit: _Optional[int] = ..., vector_limit: _Optional[int] = ..., web_limit: _Optional[int] = ...) -> None: ...

class RewardComponents(_message.Message):
    __slots__ = ("coherence", "coverage", "novelty", "total")
    COHERENCE_FIELD_NUMBER: _ClassVar[int]
    COVERAGE_FIELD_NUMBER: _ClassVar[int]
    NOVELTY_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    coherence: float
    coverage: float
    novelty: float
    total: float
    def __init__(self, coherence: _Optional[float] = ..., coverage: _Optional[float] = ..., novelty: _Optional[float] = ..., total: _Optional[float] = ...) -> None: ...

class ResearchPassResult(_message.Message):
    __slots__ = ("pass_number", "q_value", "reward", "sources_count", "duration_ms", "synthesis_excerpt")
    PASS_NUMBER_FIELD_NUMBER: _ClassVar[int]
    Q_VALUE_FIELD_NUMBER: _ClassVar[int]
    REWARD_FIELD_NUMBER: _ClassVar[int]
    SOURCES_COUNT_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    SYNTHESIS_EXCERPT_FIELD_NUMBER: _ClassVar[int]
    pass_number: int
    q_value: float
    reward: RewardComponents
    sources_count: int
    duration_ms: int
    synthesis_excerpt: str
    def __init__(self, pass_number: _Optional[int] = ..., q_value: _Optional[float] = ..., reward: _Optional[_Union[RewardComponents, _Mapping]] = ..., sources_count: _Optional[int] = ..., duration_ms: _Optional[int] = ..., synthesis_excerpt: _Optional[str] = ...) -> None: ...

class ResearchMemoryRef(_message.Message):
    __slots__ = ("session_id", "query", "q_value", "kb_path")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    QUERY_FIELD_NUMBER: _ClassVar[int]
    Q_VALUE_FIELD_NUMBER: _ClassVar[int]
    KB_PATH_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    query: str
    q_value: float
    kb_path: str
    def __init__(self, session_id: _Optional[str] = ..., query: _Optional[str] = ..., q_value: _Optional[float] = ..., kb_path: _Optional[str] = ...) -> None: ...

class ResearchFlowResult(_message.Message):
    __slots__ = ("session_id", "query", "total_passes", "convergence_reason", "best_q_value", "memories_used", "passes", "final_synthesis", "kb_path", "agent_perspectives")
    class AgentPerspectivesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    QUERY_FIELD_NUMBER: _ClassVar[int]
    TOTAL_PASSES_FIELD_NUMBER: _ClassVar[int]
    CONVERGENCE_REASON_FIELD_NUMBER: _ClassVar[int]
    BEST_Q_VALUE_FIELD_NUMBER: _ClassVar[int]
    MEMORIES_USED_FIELD_NUMBER: _ClassVar[int]
    PASSES_FIELD_NUMBER: _ClassVar[int]
    FINAL_SYNTHESIS_FIELD_NUMBER: _ClassVar[int]
    KB_PATH_FIELD_NUMBER: _ClassVar[int]
    AGENT_PERSPECTIVES_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    query: str
    total_passes: int
    convergence_reason: str
    best_q_value: float
    memories_used: _containers.RepeatedCompositeFieldContainer[ResearchMemoryRef]
    passes: _containers.RepeatedCompositeFieldContainer[ResearchPassResult]
    final_synthesis: str
    kb_path: str
    agent_perspectives: _containers.ScalarMap[str, str]
    def __init__(self, session_id: _Optional[str] = ..., query: _Optional[str] = ..., total_passes: _Optional[int] = ..., convergence_reason: _Optional[str] = ..., best_q_value: _Optional[float] = ..., memories_used: _Optional[_Iterable[_Union[ResearchMemoryRef, _Mapping]]] = ..., passes: _Optional[_Iterable[_Union[ResearchPassResult, _Mapping]]] = ..., final_synthesis: _Optional[str] = ..., kb_path: _Optional[str] = ..., agent_perspectives: _Optional[_Mapping[str, str]] = ...) -> None: ...

class ResearchFlowEvent(_message.Message):
    __slots__ = ("type", "timestamp_ms", "progress", "message", "pass_number", "current_q_value", "result", "error", "guru_code")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        TYPE_UNSPECIFIED: _ClassVar[ResearchFlowEvent.Type]
        QUEUED: _ClassVar[ResearchFlowEvent.Type]
        MEMORIES_RETRIEVING: _ClassVar[ResearchFlowEvent.Type]
        MEMORIES_RETRIEVED: _ClassVar[ResearchFlowEvent.Type]
        PASS_STARTED: _ClassVar[ResearchFlowEvent.Type]
        PASS_SEARCH: _ClassVar[ResearchFlowEvent.Type]
        PASS_SWARM: _ClassVar[ResearchFlowEvent.Type]
        PASS_GROK: _ClassVar[ResearchFlowEvent.Type]
        PASS_EVALUATE: _ClassVar[ResearchFlowEvent.Type]
        PASS_QUPDATE: _ClassVar[ResearchFlowEvent.Type]
        PASS_COMPLETED: _ClassVar[ResearchFlowEvent.Type]
        CONVERGED: _ClassVar[ResearchFlowEvent.Type]
        FINAL_SYNTHESIS: _ClassVar[ResearchFlowEvent.Type]
        KB_WRITE: _ClassVar[ResearchFlowEvent.Type]
        COMPLETED: _ClassVar[ResearchFlowEvent.Type]
        FAILED: _ClassVar[ResearchFlowEvent.Type]
    TYPE_UNSPECIFIED: ResearchFlowEvent.Type
    QUEUED: ResearchFlowEvent.Type
    MEMORIES_RETRIEVING: ResearchFlowEvent.Type
    MEMORIES_RETRIEVED: ResearchFlowEvent.Type
    PASS_STARTED: ResearchFlowEvent.Type
    PASS_SEARCH: ResearchFlowEvent.Type
    PASS_SWARM: ResearchFlowEvent.Type
    PASS_GROK: ResearchFlowEvent.Type
    PASS_EVALUATE: ResearchFlowEvent.Type
    PASS_QUPDATE: ResearchFlowEvent.Type
    PASS_COMPLETED: ResearchFlowEvent.Type
    CONVERGED: ResearchFlowEvent.Type
    FINAL_SYNTHESIS: ResearchFlowEvent.Type
    KB_WRITE: ResearchFlowEvent.Type
    COMPLETED: ResearchFlowEvent.Type
    FAILED: ResearchFlowEvent.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    PASS_NUMBER_FIELD_NUMBER: _ClassVar[int]
    CURRENT_Q_VALUE_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    GURU_CODE_FIELD_NUMBER: _ClassVar[int]
    type: ResearchFlowEvent.Type
    timestamp_ms: int
    progress: float
    message: str
    pass_number: int
    current_q_value: float
    result: ResearchFlowResult
    error: str
    guru_code: str
    def __init__(self, type: _Optional[_Union[ResearchFlowEvent.Type, str]] = ..., timestamp_ms: _Optional[int] = ..., progress: _Optional[float] = ..., message: _Optional[str] = ..., pass_number: _Optional[int] = ..., current_q_value: _Optional[float] = ..., result: _Optional[_Union[ResearchFlowResult, _Mapping]] = ..., error: _Optional[str] = ..., guru_code: _Optional[str] = ...) -> None: ...

class ResearchFlowStatusResponse(_message.Message):
    __slots__ = ("running", "query", "pass_number", "progress", "phase", "elapsed_s", "events_count", "stop_requested")
    RUNNING_FIELD_NUMBER: _ClassVar[int]
    QUERY_FIELD_NUMBER: _ClassVar[int]
    PASS_NUMBER_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    PHASE_FIELD_NUMBER: _ClassVar[int]
    ELAPSED_S_FIELD_NUMBER: _ClassVar[int]
    EVENTS_COUNT_FIELD_NUMBER: _ClassVar[int]
    STOP_REQUESTED_FIELD_NUMBER: _ClassVar[int]
    running: bool
    query: str
    pass_number: int
    progress: float
    phase: str
    elapsed_s: float
    events_count: int
    stop_requested: bool
    def __init__(self, running: bool = ..., query: _Optional[str] = ..., pass_number: _Optional[int] = ..., progress: _Optional[float] = ..., phase: _Optional[str] = ..., elapsed_s: _Optional[float] = ..., events_count: _Optional[int] = ..., stop_requested: bool = ...) -> None: ...

class ResearchFlowStopResponse(_message.Message):
    __slots__ = ("success", "message", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    error: str
    def __init__(self, success: bool = ..., message: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class HealthStreamRequest(_message.Message):
    __slots__ = ("interval_ms",)
    INTERVAL_MS_FIELD_NUMBER: _ClassVar[int]
    interval_ms: int
    def __init__(self, interval_ms: _Optional[int] = ...) -> None: ...

class HealthMetrics(_message.Message):
    __slots__ = ("timestamp_ms", "gpus", "endpoints", "queue_depth", "evolution_running", "system_memory_used_gb", "system_memory_total_gb")
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    GPUS_FIELD_NUMBER: _ClassVar[int]
    ENDPOINTS_FIELD_NUMBER: _ClassVar[int]
    QUEUE_DEPTH_FIELD_NUMBER: _ClassVar[int]
    EVOLUTION_RUNNING_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_MEMORY_USED_GB_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_MEMORY_TOTAL_GB_FIELD_NUMBER: _ClassVar[int]
    timestamp_ms: int
    gpus: _containers.RepeatedCompositeFieldContainer[GPUMetrics]
    endpoints: _containers.RepeatedCompositeFieldContainer[EndpointHealth]
    queue_depth: int
    evolution_running: bool
    system_memory_used_gb: float
    system_memory_total_gb: float
    def __init__(self, timestamp_ms: _Optional[int] = ..., gpus: _Optional[_Iterable[_Union[GPUMetrics, _Mapping]]] = ..., endpoints: _Optional[_Iterable[_Union[EndpointHealth, _Mapping]]] = ..., queue_depth: _Optional[int] = ..., evolution_running: bool = ..., system_memory_used_gb: _Optional[float] = ..., system_memory_total_gb: _Optional[float] = ...) -> None: ...

class GPUMetrics(_message.Message):
    __slots__ = ("gpu_id", "utilization", "memory_used_gb", "memory_total_gb", "temperature_c", "power_watts")
    GPU_ID_FIELD_NUMBER: _ClassVar[int]
    UTILIZATION_FIELD_NUMBER: _ClassVar[int]
    MEMORY_USED_GB_FIELD_NUMBER: _ClassVar[int]
    MEMORY_TOTAL_GB_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_C_FIELD_NUMBER: _ClassVar[int]
    POWER_WATTS_FIELD_NUMBER: _ClassVar[int]
    gpu_id: int
    utilization: float
    memory_used_gb: float
    memory_total_gb: float
    temperature_c: int
    power_watts: int
    def __init__(self, gpu_id: _Optional[int] = ..., utilization: _Optional[float] = ..., memory_used_gb: _Optional[float] = ..., memory_total_gb: _Optional[float] = ..., temperature_c: _Optional[int] = ..., power_watts: _Optional[int] = ...) -> None: ...

class EndpointHealth(_message.Message):
    __slots__ = ("name", "model", "healthy", "requests_served", "avg_latency_ms", "last_request_timestamp_ms")
    NAME_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    HEALTHY_FIELD_NUMBER: _ClassVar[int]
    REQUESTS_SERVED_FIELD_NUMBER: _ClassVar[int]
    AVG_LATENCY_MS_FIELD_NUMBER: _ClassVar[int]
    LAST_REQUEST_TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    name: str
    model: str
    healthy: bool
    requests_served: int
    avg_latency_ms: float
    last_request_timestamp_ms: int
    def __init__(self, name: _Optional[str] = ..., model: _Optional[str] = ..., healthy: bool = ..., requests_served: _Optional[int] = ..., avg_latency_ms: _Optional[float] = ..., last_request_timestamp_ms: _Optional[int] = ...) -> None: ...

class EventStreamRequest(_message.Message):
    __slots__ = ("event_types",)
    EVENT_TYPES_FIELD_NUMBER: _ClassVar[int]
    event_types: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, event_types: _Optional[_Iterable[str]] = ...) -> None: ...

class Event(_message.Message):
    __slots__ = ("event_type", "timestamp_ms", "service", "data")
    EVENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    SERVICE_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    event_type: str
    timestamp_ms: int
    service: str
    data: bytes
    def __init__(self, event_type: _Optional[str] = ..., timestamp_ms: _Optional[int] = ..., service: _Optional[str] = ..., data: _Optional[bytes] = ...) -> None: ...

class InitCommand(_message.Message):
    __slots__ = ("type", "client_id", "endpoint", "payload")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        SUBSCRIBE: _ClassVar[InitCommand.Type]
        HEALTH: _ClassVar[InitCommand.Type]
        STATUS: _ClassVar[InitCommand.Type]
        CANCEL: _ClassVar[InitCommand.Type]
        SKIP: _ClassVar[InitCommand.Type]
        PAUSE: _ClassVar[InitCommand.Type]
        RESUME: _ClassVar[InitCommand.Type]
    SUBSCRIBE: InitCommand.Type
    HEALTH: InitCommand.Type
    STATUS: InitCommand.Type
    CANCEL: InitCommand.Type
    SKIP: InitCommand.Type
    PAUSE: InitCommand.Type
    RESUME: InitCommand.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    ENDPOINT_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    type: InitCommand.Type
    client_id: str
    endpoint: str
    payload: bytes
    def __init__(self, type: _Optional[_Union[InitCommand.Type, str]] = ..., client_id: _Optional[str] = ..., endpoint: _Optional[str] = ..., payload: _Optional[bytes] = ...) -> None: ...

class InitEvent(_message.Message):
    __slots__ = ("type", "timestamp_ms", "phase", "progress", "endpoint", "message", "data")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        PHASE_STARTED: _ClassVar[InitEvent.Type]
        PROGRESS: _ClassVar[InitEvent.Type]
        ENDPOINT_STARTING: _ClassVar[InitEvent.Type]
        ENDPOINT_READY: _ClassVar[InitEvent.Type]
        ENDPOINT_FAILED: _ClassVar[InitEvent.Type]
        CANCELLED: _ClassVar[InitEvent.Type]
        PAUSED: _ClassVar[InitEvent.Type]
        RESUMED: _ClassVar[InitEvent.Type]
        READY: _ClassVar[InitEvent.Type]
        HEALTH_OK: _ClassVar[InitEvent.Type]
        QUEUED: _ClassVar[InitEvent.Type]
        ERROR: _ClassVar[InitEvent.Type]
        XB_AUTH_COMPLETED: _ClassVar[InitEvent.Type]
        XB_AUTH_FAILED: _ClassVar[InitEvent.Type]
        XB_STATUS_CHANGED: _ClassVar[InitEvent.Type]
    PHASE_STARTED: InitEvent.Type
    PROGRESS: InitEvent.Type
    ENDPOINT_STARTING: InitEvent.Type
    ENDPOINT_READY: InitEvent.Type
    ENDPOINT_FAILED: InitEvent.Type
    CANCELLED: InitEvent.Type
    PAUSED: InitEvent.Type
    RESUMED: InitEvent.Type
    READY: InitEvent.Type
    HEALTH_OK: InitEvent.Type
    QUEUED: InitEvent.Type
    ERROR: InitEvent.Type
    XB_AUTH_COMPLETED: InitEvent.Type
    XB_AUTH_FAILED: InitEvent.Type
    XB_STATUS_CHANGED: InitEvent.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    PHASE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    ENDPOINT_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    type: InitEvent.Type
    timestamp_ms: int
    phase: str
    progress: float
    endpoint: str
    message: str
    data: bytes
    def __init__(self, type: _Optional[_Union[InitEvent.Type, str]] = ..., timestamp_ms: _Optional[int] = ..., phase: _Optional[str] = ..., progress: _Optional[float] = ..., endpoint: _Optional[str] = ..., message: _Optional[str] = ..., data: _Optional[bytes] = ...) -> None: ...

class GetStateRequest(_message.Message):
    __slots__ = ("kb_root", "client_id", "since_generation", "include_geometry")
    KB_ROOT_FIELD_NUMBER: _ClassVar[int]
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    SINCE_GENERATION_FIELD_NUMBER: _ClassVar[int]
    INCLUDE_GEOMETRY_FIELD_NUMBER: _ClassVar[int]
    kb_root: str
    client_id: str
    since_generation: int
    include_geometry: bool
    def __init__(self, kb_root: _Optional[str] = ..., client_id: _Optional[str] = ..., since_generation: _Optional[int] = ..., include_geometry: bool = ...) -> None: ...

class GridState(_message.Message):
    __slots__ = ("snapshot_id", "generation", "updated_at_ms", "documents", "clusters", "allocations", "tda", "geometry", "n_documents", "coverage", "projection_method", "embedding_model")
    SNAPSHOT_ID_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_MS_FIELD_NUMBER: _ClassVar[int]
    DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    CLUSTERS_FIELD_NUMBER: _ClassVar[int]
    ALLOCATIONS_FIELD_NUMBER: _ClassVar[int]
    TDA_FIELD_NUMBER: _ClassVar[int]
    GEOMETRY_FIELD_NUMBER: _ClassVar[int]
    N_DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    COVERAGE_FIELD_NUMBER: _ClassVar[int]
    PROJECTION_METHOD_FIELD_NUMBER: _ClassVar[int]
    EMBEDDING_MODEL_FIELD_NUMBER: _ClassVar[int]
    snapshot_id: str
    generation: int
    updated_at_ms: int
    documents: _containers.RepeatedCompositeFieldContainer[GridPosition]
    clusters: _containers.RepeatedCompositeFieldContainer[GridPosition]
    allocations: _containers.RepeatedScalarFieldContainer[int]
    tda: TDAFeatures
    geometry: GeometryFeatures
    n_documents: int
    coverage: float
    projection_method: str
    embedding_model: str
    def __init__(self, snapshot_id: _Optional[str] = ..., generation: _Optional[int] = ..., updated_at_ms: _Optional[int] = ..., documents: _Optional[_Iterable[_Union[GridPosition, _Mapping]]] = ..., clusters: _Optional[_Iterable[_Union[GridPosition, _Mapping]]] = ..., allocations: _Optional[_Iterable[int]] = ..., tda: _Optional[_Union[TDAFeatures, _Mapping]] = ..., geometry: _Optional[_Union[GeometryFeatures, _Mapping]] = ..., n_documents: _Optional[int] = ..., coverage: _Optional[float] = ..., projection_method: _Optional[str] = ..., embedding_model: _Optional[str] = ...) -> None: ...

class TDAFeatures(_message.Message):
    __slots__ = ("h1_cycles", "h2_voids", "risk_scores", "entropy", "h0_count", "h1_count", "h2_count")
    H1_CYCLES_FIELD_NUMBER: _ClassVar[int]
    H2_VOIDS_FIELD_NUMBER: _ClassVar[int]
    RISK_SCORES_FIELD_NUMBER: _ClassVar[int]
    ENTROPY_FIELD_NUMBER: _ClassVar[int]
    H0_COUNT_FIELD_NUMBER: _ClassVar[int]
    H1_COUNT_FIELD_NUMBER: _ClassVar[int]
    H2_COUNT_FIELD_NUMBER: _ClassVar[int]
    h1_cycles: _containers.RepeatedCompositeFieldContainer[BoundingBox]
    h2_voids: _containers.RepeatedCompositeFieldContainer[BoundingBox]
    risk_scores: _containers.RepeatedScalarFieldContainer[int]
    entropy: float
    h0_count: int
    h1_count: int
    h2_count: int
    def __init__(self, h1_cycles: _Optional[_Iterable[_Union[BoundingBox, _Mapping]]] = ..., h2_voids: _Optional[_Iterable[_Union[BoundingBox, _Mapping]]] = ..., risk_scores: _Optional[_Iterable[int]] = ..., entropy: _Optional[float] = ..., h0_count: _Optional[int] = ..., h1_count: _Optional[int] = ..., h2_count: _Optional[int] = ...) -> None: ...

class BoundingBox(_message.Message):
    __slots__ = ("x_min", "y_min", "x_max", "y_max", "persistence")
    X_MIN_FIELD_NUMBER: _ClassVar[int]
    Y_MIN_FIELD_NUMBER: _ClassVar[int]
    X_MAX_FIELD_NUMBER: _ClassVar[int]
    Y_MAX_FIELD_NUMBER: _ClassVar[int]
    PERSISTENCE_FIELD_NUMBER: _ClassVar[int]
    x_min: int
    y_min: int
    x_max: int
    y_max: int
    persistence: float
    def __init__(self, x_min: _Optional[int] = ..., y_min: _Optional[int] = ..., x_max: _Optional[int] = ..., y_max: _Optional[int] = ..., persistence: _Optional[float] = ...) -> None: ...

class GeometryFeatures(_message.Message):
    __slots__ = ("curvature_map", "gradient_field", "divergence_map")
    CURVATURE_MAP_FIELD_NUMBER: _ClassVar[int]
    GRADIENT_FIELD_FIELD_NUMBER: _ClassVar[int]
    DIVERGENCE_MAP_FIELD_NUMBER: _ClassVar[int]
    curvature_map: _containers.RepeatedScalarFieldContainer[float]
    gradient_field: _containers.RepeatedCompositeFieldContainer[GradientVector]
    divergence_map: _containers.RepeatedScalarFieldContainer[float]
    def __init__(self, curvature_map: _Optional[_Iterable[float]] = ..., gradient_field: _Optional[_Iterable[_Union[GradientVector, _Mapping]]] = ..., divergence_map: _Optional[_Iterable[float]] = ...) -> None: ...

class GradientVector(_message.Message):
    __slots__ = ("x", "y", "gx", "gy")
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    GX_FIELD_NUMBER: _ClassVar[int]
    GY_FIELD_NUMBER: _ClassVar[int]
    x: int
    y: int
    gx: float
    gy: float
    def __init__(self, x: _Optional[int] = ..., y: _Optional[int] = ..., gx: _Optional[float] = ..., gy: _Optional[float] = ...) -> None: ...

class SubscribeStateRequest(_message.Message):
    __slots__ = ("kb_root", "client_id")
    KB_ROOT_FIELD_NUMBER: _ClassVar[int]
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    kb_root: str
    client_id: str
    def __init__(self, kb_root: _Optional[str] = ..., client_id: _Optional[str] = ...) -> None: ...

class StateUpdate(_message.Message):
    __slots__ = ("type", "generation", "timestamp_ms", "state", "progress", "message", "phase")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        FULL_REFRESH: _ClassVar[StateUpdate.Type]
        GENERATION_CHANGED: _ClassVar[StateUpdate.Type]
        COMPUTATION_STARTED: _ClassVar[StateUpdate.Type]
        COMPUTATION_PROGRESS: _ClassVar[StateUpdate.Type]
        COMPUTATION_COMPLETE: _ClassVar[StateUpdate.Type]
        ERROR: _ClassVar[StateUpdate.Type]
    FULL_REFRESH: StateUpdate.Type
    GENERATION_CHANGED: StateUpdate.Type
    COMPUTATION_STARTED: StateUpdate.Type
    COMPUTATION_PROGRESS: StateUpdate.Type
    COMPUTATION_COMPLETE: StateUpdate.Type
    ERROR: StateUpdate.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    PHASE_FIELD_NUMBER: _ClassVar[int]
    type: StateUpdate.Type
    generation: int
    timestamp_ms: int
    state: GridState
    progress: float
    message: str
    phase: str
    def __init__(self, type: _Optional[_Union[StateUpdate.Type, str]] = ..., generation: _Optional[int] = ..., timestamp_ms: _Optional[int] = ..., state: _Optional[_Union[GridState, _Mapping]] = ..., progress: _Optional[float] = ..., message: _Optional[str] = ..., phase: _Optional[str] = ...) -> None: ...

class GetPreferencesRequest(_message.Message):
    __slots__ = ("client_id",)
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    client_id: str
    def __init__(self, client_id: _Optional[str] = ...) -> None: ...

class UIPreferences(_message.Message):
    __slots__ = ("client_id", "cursor_x", "cursor_y", "view_mode", "overlay_mode", "iso_mode", "center_panel_mode", "left_panel_visible", "right_panel_visible", "domain", "preferences_json")
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    CURSOR_X_FIELD_NUMBER: _ClassVar[int]
    CURSOR_Y_FIELD_NUMBER: _ClassVar[int]
    VIEW_MODE_FIELD_NUMBER: _ClassVar[int]
    OVERLAY_MODE_FIELD_NUMBER: _ClassVar[int]
    ISO_MODE_FIELD_NUMBER: _ClassVar[int]
    CENTER_PANEL_MODE_FIELD_NUMBER: _ClassVar[int]
    LEFT_PANEL_VISIBLE_FIELD_NUMBER: _ClassVar[int]
    RIGHT_PANEL_VISIBLE_FIELD_NUMBER: _ClassVar[int]
    DOMAIN_FIELD_NUMBER: _ClassVar[int]
    PREFERENCES_JSON_FIELD_NUMBER: _ClassVar[int]
    client_id: str
    cursor_x: int
    cursor_y: int
    view_mode: str
    overlay_mode: str
    iso_mode: str
    center_panel_mode: str
    left_panel_visible: bool
    right_panel_visible: bool
    domain: str
    preferences_json: bytes
    def __init__(self, client_id: _Optional[str] = ..., cursor_x: _Optional[int] = ..., cursor_y: _Optional[int] = ..., view_mode: _Optional[str] = ..., overlay_mode: _Optional[str] = ..., iso_mode: _Optional[str] = ..., center_panel_mode: _Optional[str] = ..., left_panel_visible: bool = ..., right_panel_visible: bool = ..., domain: _Optional[str] = ..., preferences_json: _Optional[bytes] = ...) -> None: ...

class SavePreferencesRequest(_message.Message):
    __slots__ = ("preferences",)
    PREFERENCES_FIELD_NUMBER: _ClassVar[int]
    preferences: UIPreferences
    def __init__(self, preferences: _Optional[_Union[UIPreferences, _Mapping]] = ...) -> None: ...

class PruneSnapshotsRequest(_message.Message):
    __slots__ = ("kb_root", "keep_count", "older_than_days", "dry_run")
    KB_ROOT_FIELD_NUMBER: _ClassVar[int]
    KEEP_COUNT_FIELD_NUMBER: _ClassVar[int]
    OLDER_THAN_DAYS_FIELD_NUMBER: _ClassVar[int]
    DRY_RUN_FIELD_NUMBER: _ClassVar[int]
    kb_root: str
    keep_count: int
    older_than_days: int
    dry_run: bool
    def __init__(self, kb_root: _Optional[str] = ..., keep_count: _Optional[int] = ..., older_than_days: _Optional[int] = ..., dry_run: bool = ...) -> None: ...

class PruneSnapshotsResponse(_message.Message):
    __slots__ = ("deleted_count", "remaining_count", "dry_run")
    DELETED_COUNT_FIELD_NUMBER: _ClassVar[int]
    REMAINING_COUNT_FIELD_NUMBER: _ClassVar[int]
    DRY_RUN_FIELD_NUMBER: _ClassVar[int]
    deleted_count: int
    remaining_count: int
    dry_run: bool
    def __init__(self, deleted_count: _Optional[int] = ..., remaining_count: _Optional[int] = ..., dry_run: bool = ...) -> None: ...

class ExecuteCommandRequest(_message.Message):
    __slots__ = ("command", "args", "kb_root", "client_id", "context")
    class ContextEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    ARGS_FIELD_NUMBER: _ClassVar[int]
    KB_ROOT_FIELD_NUMBER: _ClassVar[int]
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    command: str
    args: str
    kb_root: str
    client_id: str
    context: _containers.ScalarMap[str, str]
    def __init__(self, command: _Optional[str] = ..., args: _Optional[str] = ..., kb_root: _Optional[str] = ..., client_id: _Optional[str] = ..., context: _Optional[_Mapping[str, str]] = ...) -> None: ...

class ExecuteCommandResponse(_message.Message):
    __slots__ = ("success", "command", "message", "result_json", "generation", "duration_ms")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    RESULT_JSON_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    command: str
    message: str
    result_json: bytes
    generation: int
    duration_ms: int
    def __init__(self, success: bool = ..., command: _Optional[str] = ..., message: _Optional[str] = ..., result_json: _Optional[bytes] = ..., generation: _Optional[int] = ..., duration_ms: _Optional[int] = ...) -> None: ...

class InitRequest(_message.Message):
    __slots__ = ("kb_root", "client_id", "force", "embedding_model", "projection_method")
    KB_ROOT_FIELD_NUMBER: _ClassVar[int]
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    FORCE_FIELD_NUMBER: _ClassVar[int]
    EMBEDDING_MODEL_FIELD_NUMBER: _ClassVar[int]
    PROJECTION_METHOD_FIELD_NUMBER: _ClassVar[int]
    kb_root: str
    client_id: str
    force: bool
    embedding_model: str
    projection_method: str
    def __init__(self, kb_root: _Optional[str] = ..., client_id: _Optional[str] = ..., force: bool = ..., embedding_model: _Optional[str] = ..., projection_method: _Optional[str] = ...) -> None: ...

class InitResponse(_message.Message):
    __slots__ = ("success", "message", "documents_indexed", "h0_count", "h1_count", "h2_count", "entropy", "generation", "duration_ms")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DOCUMENTS_INDEXED_FIELD_NUMBER: _ClassVar[int]
    H0_COUNT_FIELD_NUMBER: _ClassVar[int]
    H1_COUNT_FIELD_NUMBER: _ClassVar[int]
    H2_COUNT_FIELD_NUMBER: _ClassVar[int]
    ENTROPY_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    documents_indexed: int
    h0_count: int
    h1_count: int
    h2_count: int
    entropy: float
    generation: int
    duration_ms: int
    def __init__(self, success: bool = ..., message: _Optional[str] = ..., documents_indexed: _Optional[int] = ..., h0_count: _Optional[int] = ..., h1_count: _Optional[int] = ..., h2_count: _Optional[int] = ..., entropy: _Optional[float] = ..., generation: _Optional[int] = ..., duration_ms: _Optional[int] = ...) -> None: ...

class InitProgress(_message.Message):
    __slots__ = ("phase", "progress", "message", "documents_processed", "documents_total")
    class Phase(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STARTED: _ClassVar[InitProgress.Phase]
        SCANNING: _ClassVar[InitProgress.Phase]
        EMBEDDING: _ClassVar[InitProgress.Phase]
        PROJECTING: _ClassVar[InitProgress.Phase]
        TDA: _ClassVar[InitProgress.Phase]
        GEOMETRY: _ClassVar[InitProgress.Phase]
        SAVING: _ClassVar[InitProgress.Phase]
        COMPLETE: _ClassVar[InitProgress.Phase]
        ERROR: _ClassVar[InitProgress.Phase]
    STARTED: InitProgress.Phase
    SCANNING: InitProgress.Phase
    EMBEDDING: InitProgress.Phase
    PROJECTING: InitProgress.Phase
    TDA: InitProgress.Phase
    GEOMETRY: InitProgress.Phase
    SAVING: InitProgress.Phase
    COMPLETE: InitProgress.Phase
    ERROR: InitProgress.Phase
    PHASE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DOCUMENTS_PROCESSED_FIELD_NUMBER: _ClassVar[int]
    DOCUMENTS_TOTAL_FIELD_NUMBER: _ClassVar[int]
    phase: InitProgress.Phase
    progress: float
    message: str
    documents_processed: int
    documents_total: int
    def __init__(self, phase: _Optional[_Union[InitProgress.Phase, str]] = ..., progress: _Optional[float] = ..., message: _Optional[str] = ..., documents_processed: _Optional[int] = ..., documents_total: _Optional[int] = ...) -> None: ...

class ReindexRequest(_message.Message):
    __slots__ = ("kb_root", "client_id", "force", "embedding_model")
    KB_ROOT_FIELD_NUMBER: _ClassVar[int]
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    FORCE_FIELD_NUMBER: _ClassVar[int]
    EMBEDDING_MODEL_FIELD_NUMBER: _ClassVar[int]
    kb_root: str
    client_id: str
    force: bool
    embedding_model: str
    def __init__(self, kb_root: _Optional[str] = ..., client_id: _Optional[str] = ..., force: bool = ..., embedding_model: _Optional[str] = ...) -> None: ...

class ReindexResponse(_message.Message):
    __slots__ = ("success", "message", "documents_indexed", "documents_skipped", "generation", "duration_ms")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DOCUMENTS_INDEXED_FIELD_NUMBER: _ClassVar[int]
    DOCUMENTS_SKIPPED_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    documents_indexed: int
    documents_skipped: int
    generation: int
    duration_ms: int
    def __init__(self, success: bool = ..., message: _Optional[str] = ..., documents_indexed: _Optional[int] = ..., documents_skipped: _Optional[int] = ..., generation: _Optional[int] = ..., duration_ms: _Optional[int] = ...) -> None: ...

class ReindexProgress(_message.Message):
    __slots__ = ("phase", "progress", "message", "documents_processed", "documents_total")
    class Phase(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        STARTED: _ClassVar[ReindexProgress.Phase]
        SCANNING: _ClassVar[ReindexProgress.Phase]
        EMBEDDING: _ClassVar[ReindexProgress.Phase]
        PROJECTING: _ClassVar[ReindexProgress.Phase]
        TDA: _ClassVar[ReindexProgress.Phase]
        SAVING: _ClassVar[ReindexProgress.Phase]
        COMPLETE: _ClassVar[ReindexProgress.Phase]
        ERROR: _ClassVar[ReindexProgress.Phase]
    STARTED: ReindexProgress.Phase
    SCANNING: ReindexProgress.Phase
    EMBEDDING: ReindexProgress.Phase
    PROJECTING: ReindexProgress.Phase
    TDA: ReindexProgress.Phase
    SAVING: ReindexProgress.Phase
    COMPLETE: ReindexProgress.Phase
    ERROR: ReindexProgress.Phase
    PHASE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DOCUMENTS_PROCESSED_FIELD_NUMBER: _ClassVar[int]
    DOCUMENTS_TOTAL_FIELD_NUMBER: _ClassVar[int]
    phase: ReindexProgress.Phase
    progress: float
    message: str
    documents_processed: int
    documents_total: int
    def __init__(self, phase: _Optional[_Union[ReindexProgress.Phase, str]] = ..., progress: _Optional[float] = ..., message: _Optional[str] = ..., documents_processed: _Optional[int] = ..., documents_total: _Optional[int] = ...) -> None: ...

class ExplainRequest(_message.Message):
    __slots__ = ("kb_root", "x", "y", "save_to_kb", "client_id", "max_tokens")
    KB_ROOT_FIELD_NUMBER: _ClassVar[int]
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    SAVE_TO_KB_FIELD_NUMBER: _ClassVar[int]
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    MAX_TOKENS_FIELD_NUMBER: _ClassVar[int]
    kb_root: str
    x: int
    y: int
    save_to_kb: bool
    client_id: str
    max_tokens: int
    def __init__(self, kb_root: _Optional[str] = ..., x: _Optional[int] = ..., y: _Optional[int] = ..., save_to_kb: bool = ..., client_id: _Optional[str] = ..., max_tokens: _Optional[int] = ...) -> None: ...

class ExplainResponse(_message.Message):
    __slots__ = ("success", "position", "x", "y", "document_title", "document_path", "curvature", "gradient_x", "gradient_y", "divergence", "tda_entropy", "h0_count", "h1_count", "h2_count", "risk_score", "grid_coverage", "total_documents", "nearby_documents", "embed_grid", "iso_grid", "explanation", "model", "duration_ms", "saved_path", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    POSITION_FIELD_NUMBER: _ClassVar[int]
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_TITLE_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_PATH_FIELD_NUMBER: _ClassVar[int]
    CURVATURE_FIELD_NUMBER: _ClassVar[int]
    GRADIENT_X_FIELD_NUMBER: _ClassVar[int]
    GRADIENT_Y_FIELD_NUMBER: _ClassVar[int]
    DIVERGENCE_FIELD_NUMBER: _ClassVar[int]
    TDA_ENTROPY_FIELD_NUMBER: _ClassVar[int]
    H0_COUNT_FIELD_NUMBER: _ClassVar[int]
    H1_COUNT_FIELD_NUMBER: _ClassVar[int]
    H2_COUNT_FIELD_NUMBER: _ClassVar[int]
    RISK_SCORE_FIELD_NUMBER: _ClassVar[int]
    GRID_COVERAGE_FIELD_NUMBER: _ClassVar[int]
    TOTAL_DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    NEARBY_DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    EMBED_GRID_FIELD_NUMBER: _ClassVar[int]
    ISO_GRID_FIELD_NUMBER: _ClassVar[int]
    EXPLANATION_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    SAVED_PATH_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    position: str
    x: int
    y: int
    document_title: str
    document_path: str
    curvature: float
    gradient_x: float
    gradient_y: float
    divergence: float
    tda_entropy: float
    h0_count: int
    h1_count: int
    h2_count: int
    risk_score: float
    grid_coverage: float
    total_documents: int
    nearby_documents: _containers.RepeatedScalarFieldContainer[str]
    embed_grid: _containers.RepeatedScalarFieldContainer[float]
    iso_grid: _containers.RepeatedScalarFieldContainer[float]
    explanation: str
    model: str
    duration_ms: int
    saved_path: str
    error: str
    def __init__(self, success: bool = ..., position: _Optional[str] = ..., x: _Optional[int] = ..., y: _Optional[int] = ..., document_title: _Optional[str] = ..., document_path: _Optional[str] = ..., curvature: _Optional[float] = ..., gradient_x: _Optional[float] = ..., gradient_y: _Optional[float] = ..., divergence: _Optional[float] = ..., tda_entropy: _Optional[float] = ..., h0_count: _Optional[int] = ..., h1_count: _Optional[int] = ..., h2_count: _Optional[int] = ..., risk_score: _Optional[float] = ..., grid_coverage: _Optional[float] = ..., total_documents: _Optional[int] = ..., nearby_documents: _Optional[_Iterable[str]] = ..., embed_grid: _Optional[_Iterable[float]] = ..., iso_grid: _Optional[_Iterable[float]] = ..., explanation: _Optional[str] = ..., model: _Optional[str] = ..., duration_ms: _Optional[int] = ..., saved_path: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class ProjectEmbeddingsRequest(_message.Message):
    __slots__ = ("embedding_ids", "method", "grid_size")
    EMBEDDING_IDS_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    GRID_SIZE_FIELD_NUMBER: _ClassVar[int]
    embedding_ids: _containers.RepeatedScalarFieldContainer[str]
    method: str
    grid_size: int
    def __init__(self, embedding_ids: _Optional[_Iterable[str]] = ..., method: _Optional[str] = ..., grid_size: _Optional[int] = ...) -> None: ...

class GridPosition(_message.Message):
    __slots__ = ("id", "x", "y", "cluster", "confidence")
    ID_FIELD_NUMBER: _ClassVar[int]
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    CLUSTER_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    id: str
    x: int
    y: int
    cluster: int
    confidence: float
    def __init__(self, id: _Optional[str] = ..., x: _Optional[int] = ..., y: _Optional[int] = ..., cluster: _Optional[int] = ..., confidence: _Optional[float] = ...) -> None: ...

class ProjectEmbeddingsResponse(_message.Message):
    __slots__ = ("positions", "num_clusters", "grid_size")
    POSITIONS_FIELD_NUMBER: _ClassVar[int]
    NUM_CLUSTERS_FIELD_NUMBER: _ClassVar[int]
    GRID_SIZE_FIELD_NUMBER: _ClassVar[int]
    positions: _containers.RepeatedCompositeFieldContainer[GridPosition]
    num_clusters: int
    grid_size: int
    def __init__(self, positions: _Optional[_Iterable[_Union[GridPosition, _Mapping]]] = ..., num_clusters: _Optional[int] = ..., grid_size: _Optional[int] = ...) -> None: ...

class ProjectQueryRequest(_message.Message):
    __slots__ = ("embedding", "method")
    EMBEDDING_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    embedding: _containers.RepeatedScalarFieldContainer[float]
    method: str
    def __init__(self, embedding: _Optional[_Iterable[float]] = ..., method: _Optional[str] = ...) -> None: ...

class ProjectQueryResponse(_message.Message):
    __slots__ = ("x", "y", "nearest_ids", "distances")
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    NEAREST_IDS_FIELD_NUMBER: _ClassVar[int]
    DISTANCES_FIELD_NUMBER: _ClassVar[int]
    x: int
    y: int
    nearest_ids: _containers.RepeatedScalarFieldContainer[str]
    distances: _containers.RepeatedScalarFieldContainer[float]
    def __init__(self, x: _Optional[int] = ..., y: _Optional[int] = ..., nearest_ids: _Optional[_Iterable[str]] = ..., distances: _Optional[_Iterable[float]] = ...) -> None: ...

class ComputeTDARequest(_message.Message):
    __slots__ = ("embedding_ids", "method", "max_dimension")
    EMBEDDING_IDS_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    MAX_DIMENSION_FIELD_NUMBER: _ClassVar[int]
    embedding_ids: _containers.RepeatedScalarFieldContainer[str]
    method: str
    max_dimension: int
    def __init__(self, embedding_ids: _Optional[_Iterable[str]] = ..., method: _Optional[str] = ..., max_dimension: _Optional[int] = ...) -> None: ...

class PersistenceInterval(_message.Message):
    __slots__ = ("dimension", "birth", "death")
    DIMENSION_FIELD_NUMBER: _ClassVar[int]
    BIRTH_FIELD_NUMBER: _ClassVar[int]
    DEATH_FIELD_NUMBER: _ClassVar[int]
    dimension: int
    birth: float
    death: float
    def __init__(self, dimension: _Optional[int] = ..., birth: _Optional[float] = ..., death: _Optional[float] = ...) -> None: ...

class TDAResponse(_message.Message):
    __slots__ = ("intervals", "betti_numbers", "persistence_diagram")
    INTERVALS_FIELD_NUMBER: _ClassVar[int]
    BETTI_NUMBERS_FIELD_NUMBER: _ClassVar[int]
    PERSISTENCE_DIAGRAM_FIELD_NUMBER: _ClassVar[int]
    intervals: _containers.RepeatedCompositeFieldContainer[PersistenceInterval]
    betti_numbers: _containers.RepeatedScalarFieldContainer[int]
    persistence_diagram: bytes
    def __init__(self, intervals: _Optional[_Iterable[_Union[PersistenceInterval, _Mapping]]] = ..., betti_numbers: _Optional[_Iterable[int]] = ..., persistence_diagram: _Optional[bytes] = ...) -> None: ...

class DatasetGenerationRequest(_message.Message):
    __slots__ = ("flow_name", "steps", "mode", "dataset_id", "variants_per_action", "min_quality_score", "enable_calibration", "calibration_sample_rate", "export_calibration", "storage_backend")
    FLOW_NAME_FIELD_NUMBER: _ClassVar[int]
    STEPS_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    DATASET_ID_FIELD_NUMBER: _ClassVar[int]
    VARIANTS_PER_ACTION_FIELD_NUMBER: _ClassVar[int]
    MIN_QUALITY_SCORE_FIELD_NUMBER: _ClassVar[int]
    ENABLE_CALIBRATION_FIELD_NUMBER: _ClassVar[int]
    CALIBRATION_SAMPLE_RATE_FIELD_NUMBER: _ClassVar[int]
    EXPORT_CALIBRATION_FIELD_NUMBER: _ClassVar[int]
    STORAGE_BACKEND_FIELD_NUMBER: _ClassVar[int]
    flow_name: str
    steps: _containers.RepeatedScalarFieldContainer[str]
    mode: str
    dataset_id: str
    variants_per_action: int
    min_quality_score: float
    enable_calibration: bool
    calibration_sample_rate: float
    export_calibration: bool
    storage_backend: str
    def __init__(self, flow_name: _Optional[str] = ..., steps: _Optional[_Iterable[str]] = ..., mode: _Optional[str] = ..., dataset_id: _Optional[str] = ..., variants_per_action: _Optional[int] = ..., min_quality_score: _Optional[float] = ..., enable_calibration: bool = ..., calibration_sample_rate: _Optional[float] = ..., export_calibration: bool = ..., storage_backend: _Optional[str] = ...) -> None: ...

class DatasetJobStatus(_message.Message):
    __slots__ = ("job_id", "status", "total_examples", "completed_examples", "accepted_examples", "rejected_examples", "progress", "current_phase", "error")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_EXAMPLES_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_EXAMPLES_FIELD_NUMBER: _ClassVar[int]
    ACCEPTED_EXAMPLES_FIELD_NUMBER: _ClassVar[int]
    REJECTED_EXAMPLES_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_PHASE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    status: str
    total_examples: int
    completed_examples: int
    accepted_examples: int
    rejected_examples: int
    progress: float
    current_phase: str
    error: str
    def __init__(self, job_id: _Optional[str] = ..., status: _Optional[str] = ..., total_examples: _Optional[int] = ..., completed_examples: _Optional[int] = ..., accepted_examples: _Optional[int] = ..., rejected_examples: _Optional[int] = ..., progress: _Optional[float] = ..., current_phase: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class DatasetProgressEvent(_message.Message):
    __slots__ = ("type", "timestamp_ms", "job_id", "progress", "message", "phase", "example_id", "data")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        QUEUED: _ClassVar[DatasetProgressEvent.Type]
        STARTED: _ClassVar[DatasetProgressEvent.Type]
        PHASE_STARTED: _ClassVar[DatasetProgressEvent.Type]
        EXAMPLE_STARTED: _ClassVar[DatasetProgressEvent.Type]
        EXAMPLE_COMPLETED: _ClassVar[DatasetProgressEvent.Type]
        EXAMPLE_REJECTED: _ClassVar[DatasetProgressEvent.Type]
        PHASE_COMPLETED: _ClassVar[DatasetProgressEvent.Type]
        CALIBRATION_STARTED: _ClassVar[DatasetProgressEvent.Type]
        CALIBRATION_COMPLETED: _ClassVar[DatasetProgressEvent.Type]
        EXPORT_STARTED: _ClassVar[DatasetProgressEvent.Type]
        COMPLETED: _ClassVar[DatasetProgressEvent.Type]
        FAILED: _ClassVar[DatasetProgressEvent.Type]
    QUEUED: DatasetProgressEvent.Type
    STARTED: DatasetProgressEvent.Type
    PHASE_STARTED: DatasetProgressEvent.Type
    EXAMPLE_STARTED: DatasetProgressEvent.Type
    EXAMPLE_COMPLETED: DatasetProgressEvent.Type
    EXAMPLE_REJECTED: DatasetProgressEvent.Type
    PHASE_COMPLETED: DatasetProgressEvent.Type
    CALIBRATION_STARTED: DatasetProgressEvent.Type
    CALIBRATION_COMPLETED: DatasetProgressEvent.Type
    EXPORT_STARTED: DatasetProgressEvent.Type
    COMPLETED: DatasetProgressEvent.Type
    FAILED: DatasetProgressEvent.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    PHASE_FIELD_NUMBER: _ClassVar[int]
    EXAMPLE_ID_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    type: DatasetProgressEvent.Type
    timestamp_ms: int
    job_id: str
    progress: float
    message: str
    phase: str
    example_id: str
    data: bytes
    def __init__(self, type: _Optional[_Union[DatasetProgressEvent.Type, str]] = ..., timestamp_ms: _Optional[int] = ..., job_id: _Optional[str] = ..., progress: _Optional[float] = ..., message: _Optional[str] = ..., phase: _Optional[str] = ..., example_id: _Optional[str] = ..., data: _Optional[bytes] = ...) -> None: ...

class GetDatasetJobRequest(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...

class CancelDatasetJobRequest(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...

class DatasetLineageRequest(_message.Message):
    __slots__ = ("dataset_id",)
    DATASET_ID_FIELD_NUMBER: _ClassVar[int]
    dataset_id: str
    def __init__(self, dataset_id: _Optional[str] = ...) -> None: ...

class DatasetLineageResponse(_message.Message):
    __slots__ = ("dataset_id", "total_examples", "nodes", "edges")
    DATASET_ID_FIELD_NUMBER: _ClassVar[int]
    TOTAL_EXAMPLES_FIELD_NUMBER: _ClassVar[int]
    NODES_FIELD_NUMBER: _ClassVar[int]
    EDGES_FIELD_NUMBER: _ClassVar[int]
    dataset_id: str
    total_examples: int
    nodes: _containers.RepeatedCompositeFieldContainer[LineageNode]
    edges: _containers.RepeatedCompositeFieldContainer[LineageEdge]
    def __init__(self, dataset_id: _Optional[str] = ..., total_examples: _Optional[int] = ..., nodes: _Optional[_Iterable[_Union[LineageNode, _Mapping]]] = ..., edges: _Optional[_Iterable[_Union[LineageEdge, _Mapping]]] = ...) -> None: ...

class LineageNode(_message.Message):
    __slots__ = ("id", "type", "namespace", "name", "properties")
    ID_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    id: str
    type: str
    namespace: str
    name: str
    properties: bytes
    def __init__(self, id: _Optional[str] = ..., type: _Optional[str] = ..., namespace: _Optional[str] = ..., name: _Optional[str] = ..., properties: _Optional[bytes] = ...) -> None: ...

class LineageEdge(_message.Message):
    __slots__ = ("type", "from_id", "to_id")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    FROM_ID_FIELD_NUMBER: _ClassVar[int]
    TO_ID_FIELD_NUMBER: _ClassVar[int]
    type: str
    from_id: str
    to_id: str
    def __init__(self, type: _Optional[str] = ..., from_id: _Optional[str] = ..., to_id: _Optional[str] = ...) -> None: ...

class ThetaConsolidateRequest(_message.Message):
    __slots__ = ("temporal_slice", "max_candidates", "research_mode")
    TEMPORAL_SLICE_FIELD_NUMBER: _ClassVar[int]
    MAX_CANDIDATES_FIELD_NUMBER: _ClassVar[int]
    RESEARCH_MODE_FIELD_NUMBER: _ClassVar[int]
    temporal_slice: str
    max_candidates: int
    research_mode: bool
    def __init__(self, temporal_slice: _Optional[str] = ..., max_candidates: _Optional[int] = ..., research_mode: bool = ...) -> None: ...

class ThetaConsolidateResponse(_message.Message):
    __slots__ = ("success", "slice_id", "urgency", "drift", "candidates_evaluated", "candidates_selected", "documents_augmented", "error", "guru_meditation")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    SLICE_ID_FIELD_NUMBER: _ClassVar[int]
    URGENCY_FIELD_NUMBER: _ClassVar[int]
    DRIFT_FIELD_NUMBER: _ClassVar[int]
    CANDIDATES_EVALUATED_FIELD_NUMBER: _ClassVar[int]
    CANDIDATES_SELECTED_FIELD_NUMBER: _ClassVar[int]
    DOCUMENTS_AUGMENTED_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    GURU_MEDITATION_FIELD_NUMBER: _ClassVar[int]
    success: bool
    slice_id: str
    urgency: float
    drift: float
    candidates_evaluated: int
    candidates_selected: int
    documents_augmented: int
    error: str
    guru_meditation: str
    def __init__(self, success: bool = ..., slice_id: _Optional[str] = ..., urgency: _Optional[float] = ..., drift: _Optional[float] = ..., candidates_evaluated: _Optional[int] = ..., candidates_selected: _Optional[int] = ..., documents_augmented: _Optional[int] = ..., error: _Optional[str] = ..., guru_meditation: _Optional[str] = ...) -> None: ...

class ThetaConsolidationStatsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ThetaConsolidationStatsResponse(_message.Message):
    __slots__ = ("nvar_k", "nvar_order", "slice_count", "can_predict", "research_mode", "measurement_cost", "n_measurements", "current_best_value", "effectiveness_history_length", "effectiveness_trend", "mean_contribution", "confidence_threshold", "template_type", "classifier_loaded")
    NVAR_K_FIELD_NUMBER: _ClassVar[int]
    NVAR_ORDER_FIELD_NUMBER: _ClassVar[int]
    SLICE_COUNT_FIELD_NUMBER: _ClassVar[int]
    CAN_PREDICT_FIELD_NUMBER: _ClassVar[int]
    RESEARCH_MODE_FIELD_NUMBER: _ClassVar[int]
    MEASUREMENT_COST_FIELD_NUMBER: _ClassVar[int]
    N_MEASUREMENTS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_BEST_VALUE_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVENESS_HISTORY_LENGTH_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVENESS_TREND_FIELD_NUMBER: _ClassVar[int]
    MEAN_CONTRIBUTION_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_THRESHOLD_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_TYPE_FIELD_NUMBER: _ClassVar[int]
    CLASSIFIER_LOADED_FIELD_NUMBER: _ClassVar[int]
    nvar_k: int
    nvar_order: int
    slice_count: int
    can_predict: bool
    research_mode: bool
    measurement_cost: float
    n_measurements: int
    current_best_value: float
    effectiveness_history_length: int
    effectiveness_trend: str
    mean_contribution: float
    confidence_threshold: float
    template_type: str
    classifier_loaded: bool
    def __init__(self, nvar_k: _Optional[int] = ..., nvar_order: _Optional[int] = ..., slice_count: _Optional[int] = ..., can_predict: bool = ..., research_mode: bool = ..., measurement_cost: _Optional[float] = ..., n_measurements: _Optional[int] = ..., current_best_value: _Optional[float] = ..., effectiveness_history_length: _Optional[int] = ..., effectiveness_trend: _Optional[str] = ..., mean_contribution: _Optional[float] = ..., confidence_threshold: _Optional[float] = ..., template_type: _Optional[str] = ..., classifier_loaded: bool = ...) -> None: ...

class ThetaSitrepRequest(_message.Message):
    __slots__ = ("horizon",)
    HORIZON_FIELD_NUMBER: _ClassVar[int]
    horizon: str
    def __init__(self, horizon: _Optional[str] = ...) -> None: ...

class ThetaSitrepResponse(_message.Message):
    __slots__ = ("success", "horizon", "generated_at_ms", "healthy", "status_text", "gpu_count", "endpoint_count", "priority_count", "thought_count", "objective_count", "project_count", "report_json", "ascii_format", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    HORIZON_FIELD_NUMBER: _ClassVar[int]
    GENERATED_AT_MS_FIELD_NUMBER: _ClassVar[int]
    HEALTHY_FIELD_NUMBER: _ClassVar[int]
    STATUS_TEXT_FIELD_NUMBER: _ClassVar[int]
    GPU_COUNT_FIELD_NUMBER: _ClassVar[int]
    ENDPOINT_COUNT_FIELD_NUMBER: _ClassVar[int]
    PRIORITY_COUNT_FIELD_NUMBER: _ClassVar[int]
    THOUGHT_COUNT_FIELD_NUMBER: _ClassVar[int]
    OBJECTIVE_COUNT_FIELD_NUMBER: _ClassVar[int]
    PROJECT_COUNT_FIELD_NUMBER: _ClassVar[int]
    REPORT_JSON_FIELD_NUMBER: _ClassVar[int]
    ASCII_FORMAT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    horizon: str
    generated_at_ms: int
    healthy: bool
    status_text: str
    gpu_count: int
    endpoint_count: int
    priority_count: int
    thought_count: int
    objective_count: int
    project_count: int
    report_json: bytes
    ascii_format: str
    error: str
    def __init__(self, success: bool = ..., horizon: _Optional[str] = ..., generated_at_ms: _Optional[int] = ..., healthy: bool = ..., status_text: _Optional[str] = ..., gpu_count: _Optional[int] = ..., endpoint_count: _Optional[int] = ..., priority_count: _Optional[int] = ..., thought_count: _Optional[int] = ..., objective_count: _Optional[int] = ..., project_count: _Optional[int] = ..., report_json: _Optional[bytes] = ..., ascii_format: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class ThetaAgendaRequest(_message.Message):
    __slots__ = ("action", "horizon")
    ACTION_FIELD_NUMBER: _ClassVar[int]
    HORIZON_FIELD_NUMBER: _ClassVar[int]
    action: str
    horizon: str
    def __init__(self, action: _Optional[str] = ..., horizon: _Optional[str] = ...) -> None: ...

class ThetaAgendaItem(_message.Message):
    __slots__ = ("description", "priority", "project", "due_date", "completed", "source_path")
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    PRIORITY_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    DUE_DATE_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_FIELD_NUMBER: _ClassVar[int]
    SOURCE_PATH_FIELD_NUMBER: _ClassVar[int]
    description: str
    priority: str
    project: str
    due_date: str
    completed: bool
    source_path: str
    def __init__(self, description: _Optional[str] = ..., priority: _Optional[str] = ..., project: _Optional[str] = ..., due_date: _Optional[str] = ..., completed: bool = ..., source_path: _Optional[str] = ...) -> None: ...

class ThetaAgendaResponse(_message.Message):
    __slots__ = ("success", "action", "horizon", "path", "created", "items", "ascii_format", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    HORIZON_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    CREATED_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    ASCII_FORMAT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    action: str
    horizon: str
    path: str
    created: bool
    items: _containers.RepeatedCompositeFieldContainer[ThetaAgendaItem]
    ascii_format: str
    error: str
    def __init__(self, success: bool = ..., action: _Optional[str] = ..., horizon: _Optional[str] = ..., path: _Optional[str] = ..., created: bool = ..., items: _Optional[_Iterable[_Union[ThetaAgendaItem, _Mapping]]] = ..., ascii_format: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class AgendaCheck(_message.Message):
    __slots__ = ("done", "text")
    DONE_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    done: bool
    text: str
    def __init__(self, done: bool = ..., text: _Optional[str] = ...) -> None: ...

class AgendaCard(_message.Message):
    __slots__ = ("path", "kind", "title", "body", "excerpt", "prev", "next", "starts", "ends", "tags", "pin", "checks", "created_ms", "intent", "with_whom", "calendar_url", "timezone")
    PATH_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    EXCERPT_FIELD_NUMBER: _ClassVar[int]
    PREV_FIELD_NUMBER: _ClassVar[int]
    NEXT_FIELD_NUMBER: _ClassVar[int]
    STARTS_FIELD_NUMBER: _ClassVar[int]
    ENDS_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    PIN_FIELD_NUMBER: _ClassVar[int]
    CHECKS_FIELD_NUMBER: _ClassVar[int]
    CREATED_MS_FIELD_NUMBER: _ClassVar[int]
    INTENT_FIELD_NUMBER: _ClassVar[int]
    WITH_WHOM_FIELD_NUMBER: _ClassVar[int]
    CALENDAR_URL_FIELD_NUMBER: _ClassVar[int]
    TIMEZONE_FIELD_NUMBER: _ClassVar[int]
    path: str
    kind: str
    title: str
    body: str
    excerpt: str
    prev: str
    next: str
    starts: str
    ends: str
    tags: _containers.RepeatedScalarFieldContainer[str]
    pin: bool
    checks: _containers.RepeatedCompositeFieldContainer[AgendaCheck]
    created_ms: int
    intent: str
    with_whom: str
    calendar_url: str
    timezone: str
    def __init__(self, path: _Optional[str] = ..., kind: _Optional[str] = ..., title: _Optional[str] = ..., body: _Optional[str] = ..., excerpt: _Optional[str] = ..., prev: _Optional[str] = ..., next: _Optional[str] = ..., starts: _Optional[str] = ..., ends: _Optional[str] = ..., tags: _Optional[_Iterable[str]] = ..., pin: bool = ..., checks: _Optional[_Iterable[_Union[AgendaCheck, _Mapping]]] = ..., created_ms: _Optional[int] = ..., intent: _Optional[str] = ..., with_whom: _Optional[str] = ..., calendar_url: _Optional[str] = ..., timezone: _Optional[str] = ...) -> None: ...

class AgendaListRequest(_message.Message):
    __slots__ = ("window_days", "kind", "tag", "origin", "timezone")
    WINDOW_DAYS_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    TAG_FIELD_NUMBER: _ClassVar[int]
    ORIGIN_FIELD_NUMBER: _ClassVar[int]
    TIMEZONE_FIELD_NUMBER: _ClassVar[int]
    window_days: int
    kind: str
    tag: str
    origin: str
    timezone: str
    def __init__(self, window_days: _Optional[int] = ..., kind: _Optional[str] = ..., tag: _Optional[str] = ..., origin: _Optional[str] = ..., timezone: _Optional[str] = ...) -> None: ...

class AgendaListResponse(_message.Message):
    __slots__ = ("items", "error")
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[AgendaCard]
    error: str
    def __init__(self, items: _Optional[_Iterable[_Union[AgendaCard, _Mapping]]] = ..., error: _Optional[str] = ...) -> None: ...

class AgendaGetRequest(_message.Message):
    __slots__ = ("path",)
    PATH_FIELD_NUMBER: _ClassVar[int]
    path: str
    def __init__(self, path: _Optional[str] = ...) -> None: ...

class AgendaGetResponse(_message.Message):
    __slots__ = ("item", "error")
    ITEM_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    item: AgendaCard
    error: str
    def __init__(self, item: _Optional[_Union[AgendaCard, _Mapping]] = ..., error: _Optional[str] = ...) -> None: ...

class AgendaCreateRequest(_message.Message):
    __slots__ = ("kind", "title", "body", "starts", "ends", "tags", "pin", "intent", "with_whom", "timezone")
    KIND_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    STARTS_FIELD_NUMBER: _ClassVar[int]
    ENDS_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    PIN_FIELD_NUMBER: _ClassVar[int]
    INTENT_FIELD_NUMBER: _ClassVar[int]
    WITH_WHOM_FIELD_NUMBER: _ClassVar[int]
    TIMEZONE_FIELD_NUMBER: _ClassVar[int]
    kind: str
    title: str
    body: str
    starts: str
    ends: str
    tags: _containers.RepeatedScalarFieldContainer[str]
    pin: bool
    intent: str
    with_whom: str
    timezone: str
    def __init__(self, kind: _Optional[str] = ..., title: _Optional[str] = ..., body: _Optional[str] = ..., starts: _Optional[str] = ..., ends: _Optional[str] = ..., tags: _Optional[_Iterable[str]] = ..., pin: bool = ..., intent: _Optional[str] = ..., with_whom: _Optional[str] = ..., timezone: _Optional[str] = ...) -> None: ...

class AgendaCreateResponse(_message.Message):
    __slots__ = ("item", "error")
    ITEM_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    item: AgendaCard
    error: str
    def __init__(self, item: _Optional[_Union[AgendaCard, _Mapping]] = ..., error: _Optional[str] = ...) -> None: ...

class AgendaUpdateRequest(_message.Message):
    __slots__ = ("path", "title", "body", "starts", "ends", "tags", "pin", "has_pin", "checks", "has_checks", "intent", "has_intent", "with_whom", "has_with", "timezone", "has_timezone")
    PATH_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    STARTS_FIELD_NUMBER: _ClassVar[int]
    ENDS_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    PIN_FIELD_NUMBER: _ClassVar[int]
    HAS_PIN_FIELD_NUMBER: _ClassVar[int]
    CHECKS_FIELD_NUMBER: _ClassVar[int]
    HAS_CHECKS_FIELD_NUMBER: _ClassVar[int]
    INTENT_FIELD_NUMBER: _ClassVar[int]
    HAS_INTENT_FIELD_NUMBER: _ClassVar[int]
    WITH_WHOM_FIELD_NUMBER: _ClassVar[int]
    HAS_WITH_FIELD_NUMBER: _ClassVar[int]
    TIMEZONE_FIELD_NUMBER: _ClassVar[int]
    HAS_TIMEZONE_FIELD_NUMBER: _ClassVar[int]
    path: str
    title: str
    body: str
    starts: str
    ends: str
    tags: _containers.RepeatedScalarFieldContainer[str]
    pin: bool
    has_pin: bool
    checks: _containers.RepeatedCompositeFieldContainer[AgendaCheck]
    has_checks: bool
    intent: str
    has_intent: bool
    with_whom: str
    has_with: bool
    timezone: str
    has_timezone: bool
    def __init__(self, path: _Optional[str] = ..., title: _Optional[str] = ..., body: _Optional[str] = ..., starts: _Optional[str] = ..., ends: _Optional[str] = ..., tags: _Optional[_Iterable[str]] = ..., pin: bool = ..., has_pin: bool = ..., checks: _Optional[_Iterable[_Union[AgendaCheck, _Mapping]]] = ..., has_checks: bool = ..., intent: _Optional[str] = ..., has_intent: bool = ..., with_whom: _Optional[str] = ..., has_with: bool = ..., timezone: _Optional[str] = ..., has_timezone: bool = ...) -> None: ...

class AgendaUpdateResponse(_message.Message):
    __slots__ = ("item", "error")
    ITEM_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    item: AgendaCard
    error: str
    def __init__(self, item: _Optional[_Union[AgendaCard, _Mapping]] = ..., error: _Optional[str] = ...) -> None: ...

class WeeklySignalsRemote(_message.Message):
    __slots__ = ("project", "name", "url")
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    project: str
    name: str
    url: str
    def __init__(self, project: _Optional[str] = ..., name: _Optional[str] = ..., url: _Optional[str] = ...) -> None: ...

class WeeklySignalsSummaryRequest(_message.Message):
    __slots__ = ("week", "previous")
    WEEK_FIELD_NUMBER: _ClassVar[int]
    PREVIOUS_FIELD_NUMBER: _ClassVar[int]
    week: str
    previous: bool
    def __init__(self, week: _Optional[str] = ..., previous: bool = ...) -> None: ...

class WeeklySignalsSummaryResponse(_message.Message):
    __slots__ = ("path", "week", "body", "projects", "remotes", "acp_used", "error")
    PATH_FIELD_NUMBER: _ClassVar[int]
    WEEK_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    PROJECTS_FIELD_NUMBER: _ClassVar[int]
    REMOTES_FIELD_NUMBER: _ClassVar[int]
    ACP_USED_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    path: str
    week: str
    body: str
    projects: _containers.RepeatedScalarFieldContainer[str]
    remotes: _containers.RepeatedCompositeFieldContainer[WeeklySignalsRemote]
    acp_used: bool
    error: str
    def __init__(self, path: _Optional[str] = ..., week: _Optional[str] = ..., body: _Optional[str] = ..., projects: _Optional[_Iterable[str]] = ..., remotes: _Optional[_Iterable[_Union[WeeklySignalsRemote, _Mapping]]] = ..., acp_used: bool = ..., error: _Optional[str] = ...) -> None: ...

class WeeklySignalsSummaryListRequest(_message.Message):
    __slots__ = ("limit",)
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    limit: int
    def __init__(self, limit: _Optional[int] = ...) -> None: ...

class WeeklySignalsSummaryItem(_message.Message):
    __slots__ = ("path", "week", "title")
    PATH_FIELD_NUMBER: _ClassVar[int]
    WEEK_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    path: str
    week: str
    title: str
    def __init__(self, path: _Optional[str] = ..., week: _Optional[str] = ..., title: _Optional[str] = ...) -> None: ...

class WeeklySignalsSummaryListResponse(_message.Message):
    __slots__ = ("items", "error")
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[WeeklySignalsSummaryItem]
    error: str
    def __init__(self, items: _Optional[_Iterable[_Union[WeeklySignalsSummaryItem, _Mapping]]] = ..., error: _Optional[str] = ...) -> None: ...

class WeeklySignalsSummaryGetRequest(_message.Message):
    __slots__ = ("path",)
    PATH_FIELD_NUMBER: _ClassVar[int]
    path: str
    def __init__(self, path: _Optional[str] = ...) -> None: ...

class WeeklySignalsSummaryGetResponse(_message.Message):
    __slots__ = ("path", "body", "error")
    PATH_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    path: str
    body: str
    error: str
    def __init__(self, path: _Optional[str] = ..., body: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class KnowledgeSummaryRequest(_message.Message):
    __slots__ = ("week", "section")
    WEEK_FIELD_NUMBER: _ClassVar[int]
    SECTION_FIELD_NUMBER: _ClassVar[int]
    week: str
    section: str
    def __init__(self, week: _Optional[str] = ..., section: _Optional[str] = ...) -> None: ...

class KnowledgeSummaryWritten(_message.Message):
    __slots__ = ("section", "path", "notes")
    SECTION_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    NOTES_FIELD_NUMBER: _ClassVar[int]
    section: str
    path: str
    notes: int
    def __init__(self, section: _Optional[str] = ..., path: _Optional[str] = ..., notes: _Optional[int] = ...) -> None: ...

class KnowledgeSummaryResponse(_message.Message):
    __slots__ = ("week", "items", "error")
    WEEK_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    week: str
    items: _containers.RepeatedCompositeFieldContainer[KnowledgeSummaryWritten]
    error: str
    def __init__(self, week: _Optional[str] = ..., items: _Optional[_Iterable[_Union[KnowledgeSummaryWritten, _Mapping]]] = ..., error: _Optional[str] = ...) -> None: ...

class FederationSurface(_message.Message):
    __slots__ = ("project", "engine_target", "primary_ui")
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    ENGINE_TARGET_FIELD_NUMBER: _ClassVar[int]
    PRIMARY_UI_FIELD_NUMBER: _ClassVar[int]
    project: str
    engine_target: str
    primary_ui: str
    def __init__(self, project: _Optional[str] = ..., engine_target: _Optional[str] = ..., primary_ui: _Optional[str] = ...) -> None: ...

class FederationSurfacesRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class FederationSurfacesResponse(_message.Message):
    __slots__ = ("items", "error")
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[FederationSurface]
    error: str
    def __init__(self, items: _Optional[_Iterable[_Union[FederationSurface, _Mapping]]] = ..., error: _Optional[str] = ...) -> None: ...

class AskPresentRequest(_message.Message):
    __slots__ = ("kind", "symbol", "title", "from_date", "to_date", "payload_json")
    KIND_FIELD_NUMBER: _ClassVar[int]
    SYMBOL_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    FROM_DATE_FIELD_NUMBER: _ClassVar[int]
    TO_DATE_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_JSON_FIELD_NUMBER: _ClassVar[int]
    kind: str
    symbol: str
    title: str
    from_date: str
    to_date: str
    payload_json: str
    def __init__(self, kind: _Optional[str] = ..., symbol: _Optional[str] = ..., title: _Optional[str] = ..., from_date: _Optional[str] = ..., to_date: _Optional[str] = ..., payload_json: _Optional[str] = ...) -> None: ...

class AskPresentResponse(_message.Message):
    __slots__ = ("artifact_json", "error", "n_items")
    ARTIFACT_JSON_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    N_ITEMS_FIELD_NUMBER: _ClassVar[int]
    artifact_json: str
    error: str
    n_items: int
    def __init__(self, artifact_json: _Optional[str] = ..., error: _Optional[str] = ..., n_items: _Optional[int] = ...) -> None: ...

class FmpNewsRequest(_message.Message):
    __slots__ = ("kind", "symbol", "limit")
    KIND_FIELD_NUMBER: _ClassVar[int]
    SYMBOL_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    kind: str
    symbol: str
    limit: int
    def __init__(self, kind: _Optional[str] = ..., symbol: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class FmpNewsResponse(_message.Message):
    __slots__ = ("items_json", "error")
    ITEMS_JSON_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    items_json: str
    error: str
    def __init__(self, items_json: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class FmpSearchRequest(_message.Message):
    __slots__ = ("query", "limit")
    QUERY_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    query: str
    limit: int
    def __init__(self, query: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class FmpSearchResponse(_message.Message):
    __slots__ = ("items_json", "error")
    ITEMS_JSON_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    items_json: str
    error: str
    def __init__(self, items_json: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class SummaryNote(_message.Message):
    __slots__ = ("id", "title", "body", "section", "lens", "week", "mtime_ms", "links", "origin_project", "origin_id", "excerpt", "virtual")
    ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    SECTION_FIELD_NUMBER: _ClassVar[int]
    LENS_FIELD_NUMBER: _ClassVar[int]
    WEEK_FIELD_NUMBER: _ClassVar[int]
    MTIME_MS_FIELD_NUMBER: _ClassVar[int]
    LINKS_FIELD_NUMBER: _ClassVar[int]
    ORIGIN_PROJECT_FIELD_NUMBER: _ClassVar[int]
    ORIGIN_ID_FIELD_NUMBER: _ClassVar[int]
    EXCERPT_FIELD_NUMBER: _ClassVar[int]
    VIRTUAL_FIELD_NUMBER: _ClassVar[int]
    id: str
    title: str
    body: str
    section: str
    lens: str
    week: str
    mtime_ms: int
    links: _containers.RepeatedScalarFieldContainer[str]
    origin_project: str
    origin_id: str
    excerpt: str
    virtual: bool
    def __init__(self, id: _Optional[str] = ..., title: _Optional[str] = ..., body: _Optional[str] = ..., section: _Optional[str] = ..., lens: _Optional[str] = ..., week: _Optional[str] = ..., mtime_ms: _Optional[int] = ..., links: _Optional[_Iterable[str]] = ..., origin_project: _Optional[str] = ..., origin_id: _Optional[str] = ..., excerpt: _Optional[str] = ..., virtual: bool = ...) -> None: ...

class SummaryIndexRequest(_message.Message):
    __slots__ = ("section", "lens", "week", "limit")
    SECTION_FIELD_NUMBER: _ClassVar[int]
    LENS_FIELD_NUMBER: _ClassVar[int]
    WEEK_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    section: str
    lens: str
    week: str
    limit: int
    def __init__(self, section: _Optional[str] = ..., lens: _Optional[str] = ..., week: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class SummaryIndexResponse(_message.Message):
    __slots__ = ("week", "landing_id", "seed", "items", "error")
    WEEK_FIELD_NUMBER: _ClassVar[int]
    LANDING_ID_FIELD_NUMBER: _ClassVar[int]
    SEED_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    week: str
    landing_id: str
    seed: SummaryNote
    items: _containers.RepeatedCompositeFieldContainer[SummaryNote]
    error: str
    def __init__(self, week: _Optional[str] = ..., landing_id: _Optional[str] = ..., seed: _Optional[_Union[SummaryNote, _Mapping]] = ..., items: _Optional[_Iterable[_Union[SummaryNote, _Mapping]]] = ..., error: _Optional[str] = ...) -> None: ...

class SummaryGetRequest(_message.Message):
    __slots__ = ("id", "section", "lens", "week")
    ID_FIELD_NUMBER: _ClassVar[int]
    SECTION_FIELD_NUMBER: _ClassVar[int]
    LENS_FIELD_NUMBER: _ClassVar[int]
    WEEK_FIELD_NUMBER: _ClassVar[int]
    id: str
    section: str
    lens: str
    week: str
    def __init__(self, id: _Optional[str] = ..., section: _Optional[str] = ..., lens: _Optional[str] = ..., week: _Optional[str] = ...) -> None: ...

class SummaryGetResponse(_message.Message):
    __slots__ = ("note", "error")
    NOTE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    note: SummaryNote
    error: str
    def __init__(self, note: _Optional[_Union[SummaryNote, _Mapping]] = ..., error: _Optional[str] = ...) -> None: ...

class SummaryHopRequest(_message.Message):
    __slots__ = ("from_id", "target", "section", "lens", "week")
    FROM_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    SECTION_FIELD_NUMBER: _ClassVar[int]
    LENS_FIELD_NUMBER: _ClassVar[int]
    WEEK_FIELD_NUMBER: _ClassVar[int]
    from_id: str
    target: str
    section: str
    lens: str
    week: str
    def __init__(self, from_id: _Optional[str] = ..., target: _Optional[str] = ..., section: _Optional[str] = ..., lens: _Optional[str] = ..., week: _Optional[str] = ...) -> None: ...

class SummaryHopResponse(_message.Message):
    __slots__ = ("note", "resolved_id", "error")
    NOTE_FIELD_NUMBER: _ClassVar[int]
    RESOLVED_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    note: SummaryNote
    resolved_id: str
    error: str
    def __init__(self, note: _Optional[_Union[SummaryNote, _Mapping]] = ..., resolved_id: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class SummaryForkRequest(_message.Message):
    __slots__ = ("id", "origin_project")
    ID_FIELD_NUMBER: _ClassVar[int]
    ORIGIN_PROJECT_FIELD_NUMBER: _ClassVar[int]
    id: str
    origin_project: str
    def __init__(self, id: _Optional[str] = ..., origin_project: _Optional[str] = ...) -> None: ...

class SummaryForkResponse(_message.Message):
    __slots__ = ("note", "error")
    NOTE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    note: SummaryNote
    error: str
    def __init__(self, note: _Optional[_Union[SummaryNote, _Mapping]] = ..., error: _Optional[str] = ...) -> None: ...

class SummarySchedule(_message.Message):
    __slots__ = ("id", "cron", "task_type", "source", "enabled", "triggerable", "cadence")
    ID_FIELD_NUMBER: _ClassVar[int]
    CRON_FIELD_NUMBER: _ClassVar[int]
    TASK_TYPE_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    TRIGGERABLE_FIELD_NUMBER: _ClassVar[int]
    CADENCE_FIELD_NUMBER: _ClassVar[int]
    id: str
    cron: str
    task_type: str
    source: str
    enabled: bool
    triggerable: bool
    cadence: str
    def __init__(self, id: _Optional[str] = ..., cron: _Optional[str] = ..., task_type: _Optional[str] = ..., source: _Optional[str] = ..., enabled: bool = ..., triggerable: bool = ..., cadence: _Optional[str] = ...) -> None: ...

class SummarySchedulesRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class SummarySchedulesResponse(_message.Message):
    __slots__ = ("items", "error")
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[SummarySchedule]
    error: str
    def __init__(self, items: _Optional[_Iterable[_Union[SummarySchedule, _Mapping]]] = ..., error: _Optional[str] = ...) -> None: ...

class SummaryScheduleTriggerRequest(_message.Message):
    __slots__ = ("id",)
    ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    def __init__(self, id: _Optional[str] = ...) -> None: ...

class SummaryScheduleTriggerResponse(_message.Message):
    __slots__ = ("task_id", "task_type", "error")
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    TASK_TYPE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    task_id: int
    task_type: str
    error: str
    def __init__(self, task_id: _Optional[int] = ..., task_type: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class MetaAgentQueryRequest(_message.Message):
    __slots__ = ("query", "include_dot", "include_markdown", "domains", "max_agents")
    QUERY_FIELD_NUMBER: _ClassVar[int]
    INCLUDE_DOT_FIELD_NUMBER: _ClassVar[int]
    INCLUDE_MARKDOWN_FIELD_NUMBER: _ClassVar[int]
    DOMAINS_FIELD_NUMBER: _ClassVar[int]
    MAX_AGENTS_FIELD_NUMBER: _ClassVar[int]
    query: str
    include_dot: bool
    include_markdown: bool
    domains: _containers.RepeatedScalarFieldContainer[str]
    max_agents: int
    def __init__(self, query: _Optional[str] = ..., include_dot: bool = ..., include_markdown: bool = ..., domains: _Optional[_Iterable[str]] = ..., max_agents: _Optional[int] = ...) -> None: ...

class MetaAgentEvent(_message.Message):
    __slots__ = ("type", "timestamp_ms", "agent", "domain", "message", "data")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        AGENT_STARTED: _ClassVar[MetaAgentEvent.Type]
        AGENT_QUERY: _ClassVar[MetaAgentEvent.Type]
        AGENT_RESULT: _ClassVar[MetaAgentEvent.Type]
        AGENT_COMPLETED: _ClassVar[MetaAgentEvent.Type]
        CORRELATION: _ClassVar[MetaAgentEvent.Type]
        COMPLETE: _ClassVar[MetaAgentEvent.Type]
        ERROR: _ClassVar[MetaAgentEvent.Type]
    AGENT_STARTED: MetaAgentEvent.Type
    AGENT_QUERY: MetaAgentEvent.Type
    AGENT_RESULT: MetaAgentEvent.Type
    AGENT_COMPLETED: MetaAgentEvent.Type
    CORRELATION: MetaAgentEvent.Type
    COMPLETE: MetaAgentEvent.Type
    ERROR: MetaAgentEvent.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    AGENT_FIELD_NUMBER: _ClassVar[int]
    DOMAIN_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    type: MetaAgentEvent.Type
    timestamp_ms: int
    agent: str
    domain: str
    message: str
    data: bytes
    def __init__(self, type: _Optional[_Union[MetaAgentEvent.Type, str]] = ..., timestamp_ms: _Optional[int] = ..., agent: _Optional[str] = ..., domain: _Optional[str] = ..., message: _Optional[str] = ..., data: _Optional[bytes] = ...) -> None: ...

class MetaAgentQueryResponse(_message.Message):
    __slots__ = ("success", "answer", "dot_graph", "markdown_tables", "agent_insights", "queries_executed", "agents_used", "duration_ms", "error")
    class AgentInsightsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: bytes
        def __init__(self, key: _Optional[str] = ..., value: _Optional[bytes] = ...) -> None: ...
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ANSWER_FIELD_NUMBER: _ClassVar[int]
    DOT_GRAPH_FIELD_NUMBER: _ClassVar[int]
    MARKDOWN_TABLES_FIELD_NUMBER: _ClassVar[int]
    AGENT_INSIGHTS_FIELD_NUMBER: _ClassVar[int]
    QUERIES_EXECUTED_FIELD_NUMBER: _ClassVar[int]
    AGENTS_USED_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    answer: str
    dot_graph: str
    markdown_tables: _containers.RepeatedScalarFieldContainer[str]
    agent_insights: _containers.ScalarMap[str, bytes]
    queries_executed: _containers.RepeatedScalarFieldContainer[str]
    agents_used: int
    duration_ms: int
    error: str
    def __init__(self, success: bool = ..., answer: _Optional[str] = ..., dot_graph: _Optional[str] = ..., markdown_tables: _Optional[_Iterable[str]] = ..., agent_insights: _Optional[_Mapping[str, bytes]] = ..., queries_executed: _Optional[_Iterable[str]] = ..., agents_used: _Optional[int] = ..., duration_ms: _Optional[int] = ..., error: _Optional[str] = ...) -> None: ...

class MetaAgentStatusRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class MetaAgentStatusResponse(_message.Message):
    __slots__ = ("running", "metabase_connected", "last_sync_at", "last_audit_at", "next_audit_at", "budget", "models_synced", "dashboards_synced", "error")
    RUNNING_FIELD_NUMBER: _ClassVar[int]
    METABASE_CONNECTED_FIELD_NUMBER: _ClassVar[int]
    LAST_SYNC_AT_FIELD_NUMBER: _ClassVar[int]
    LAST_AUDIT_AT_FIELD_NUMBER: _ClassVar[int]
    NEXT_AUDIT_AT_FIELD_NUMBER: _ClassVar[int]
    BUDGET_FIELD_NUMBER: _ClassVar[int]
    MODELS_SYNCED_FIELD_NUMBER: _ClassVar[int]
    DASHBOARDS_SYNCED_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    running: bool
    metabase_connected: bool
    last_sync_at: str
    last_audit_at: str
    next_audit_at: str
    budget: PooledBudgetStatus
    models_synced: int
    dashboards_synced: int
    error: str
    def __init__(self, running: bool = ..., metabase_connected: bool = ..., last_sync_at: _Optional[str] = ..., last_audit_at: _Optional[str] = ..., next_audit_at: _Optional[str] = ..., budget: _Optional[_Union[PooledBudgetStatus, _Mapping]] = ..., models_synced: _Optional[int] = ..., dashboards_synced: _Optional[int] = ..., error: _Optional[str] = ...) -> None: ...

class MetabaseSyncRequest(_message.Message):
    __slots__ = ("full_refresh", "tables", "sync_dashboards")
    FULL_REFRESH_FIELD_NUMBER: _ClassVar[int]
    TABLES_FIELD_NUMBER: _ClassVar[int]
    SYNC_DASHBOARDS_FIELD_NUMBER: _ClassVar[int]
    full_refresh: bool
    tables: _containers.RepeatedScalarFieldContainer[str]
    sync_dashboards: bool
    def __init__(self, full_refresh: bool = ..., tables: _Optional[_Iterable[str]] = ..., sync_dashboards: bool = ...) -> None: ...

class MetabaseSyncResponse(_message.Message):
    __slots__ = ("success", "models_created", "models_updated", "models_failed", "dashboards_synced", "duration_ms", "errors", "error", "models_synced", "dashboards_failed")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MODELS_CREATED_FIELD_NUMBER: _ClassVar[int]
    MODELS_UPDATED_FIELD_NUMBER: _ClassVar[int]
    MODELS_FAILED_FIELD_NUMBER: _ClassVar[int]
    DASHBOARDS_SYNCED_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    ERRORS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    MODELS_SYNCED_FIELD_NUMBER: _ClassVar[int]
    DASHBOARDS_FAILED_FIELD_NUMBER: _ClassVar[int]
    success: bool
    models_created: int
    models_updated: int
    models_failed: int
    dashboards_synced: int
    duration_ms: int
    errors: _containers.RepeatedScalarFieldContainer[str]
    error: str
    models_synced: int
    dashboards_failed: int
    def __init__(self, success: bool = ..., models_created: _Optional[int] = ..., models_updated: _Optional[int] = ..., models_failed: _Optional[int] = ..., dashboards_synced: _Optional[int] = ..., duration_ms: _Optional[int] = ..., errors: _Optional[_Iterable[str]] = ..., error: _Optional[str] = ..., models_synced: _Optional[int] = ..., dashboards_failed: _Optional[int] = ...) -> None: ...

class MetaAgentAuditRequest(_message.Message):
    __slots__ = ("scope", "use_remote_llm", "lookback_days", "dry_run")
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    USE_REMOTE_LLM_FIELD_NUMBER: _ClassVar[int]
    LOOKBACK_DAYS_FIELD_NUMBER: _ClassVar[int]
    DRY_RUN_FIELD_NUMBER: _ClassVar[int]
    scope: str
    use_remote_llm: bool
    lookback_days: int
    dry_run: bool
    def __init__(self, scope: _Optional[str] = ..., use_remote_llm: bool = ..., lookback_days: _Optional[int] = ..., dry_run: bool = ...) -> None: ...

class AuditFinding(_message.Message):
    __slots__ = ("category", "severity", "title", "description", "suggested_action", "evidence", "affected_component")
    CATEGORY_FIELD_NUMBER: _ClassVar[int]
    SEVERITY_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    SUGGESTED_ACTION_FIELD_NUMBER: _ClassVar[int]
    EVIDENCE_FIELD_NUMBER: _ClassVar[int]
    AFFECTED_COMPONENT_FIELD_NUMBER: _ClassVar[int]
    category: str
    severity: str
    title: str
    description: str
    suggested_action: str
    evidence: bytes
    affected_component: str
    def __init__(self, category: _Optional[str] = ..., severity: _Optional[str] = ..., title: _Optional[str] = ..., description: _Optional[str] = ..., suggested_action: _Optional[str] = ..., evidence: _Optional[bytes] = ..., affected_component: _Optional[str] = ...) -> None: ...

class AuditRecommendation(_message.Message):
    __slots__ = ("id", "audit_id", "category", "severity", "title", "description", "suggested_implementation", "status", "created_at")
    ID_FIELD_NUMBER: _ClassVar[int]
    AUDIT_ID_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_FIELD_NUMBER: _ClassVar[int]
    SEVERITY_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    SUGGESTED_IMPLEMENTATION_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    id: str
    audit_id: str
    category: str
    severity: str
    title: str
    description: str
    suggested_implementation: str
    status: str
    created_at: str
    def __init__(self, id: _Optional[str] = ..., audit_id: _Optional[str] = ..., category: _Optional[str] = ..., severity: _Optional[str] = ..., title: _Optional[str] = ..., description: _Optional[str] = ..., suggested_implementation: _Optional[str] = ..., status: _Optional[str] = ..., created_at: _Optional[str] = ...) -> None: ...

class MetaAgentAuditResponse(_message.Message):
    __slots__ = ("success", "audit_id", "scope", "summary", "findings", "recommendations", "kb_path", "tokens_used", "provider", "duration_ms", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    AUDIT_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    FINDINGS_FIELD_NUMBER: _ClassVar[int]
    RECOMMENDATIONS_FIELD_NUMBER: _ClassVar[int]
    KB_PATH_FIELD_NUMBER: _ClassVar[int]
    TOKENS_USED_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    audit_id: str
    scope: str
    summary: str
    findings: _containers.RepeatedCompositeFieldContainer[AuditFinding]
    recommendations: _containers.RepeatedCompositeFieldContainer[AuditRecommendation]
    kb_path: str
    tokens_used: int
    provider: str
    duration_ms: int
    error: str
    def __init__(self, success: bool = ..., audit_id: _Optional[str] = ..., scope: _Optional[str] = ..., summary: _Optional[str] = ..., findings: _Optional[_Iterable[_Union[AuditFinding, _Mapping]]] = ..., recommendations: _Optional[_Iterable[_Union[AuditRecommendation, _Mapping]]] = ..., kb_path: _Optional[str] = ..., tokens_used: _Optional[int] = ..., provider: _Optional[str] = ..., duration_ms: _Optional[int] = ..., error: _Optional[str] = ...) -> None: ...

class PooledBudgetStatus(_message.Message):
    __slots__ = ("weekly_limit", "weekly_used", "weekly_remaining", "grok_calls", "cerebras_calls", "week_start", "last_reset", "usage_pct", "budget_health")
    WEEKLY_LIMIT_FIELD_NUMBER: _ClassVar[int]
    WEEKLY_USED_FIELD_NUMBER: _ClassVar[int]
    WEEKLY_REMAINING_FIELD_NUMBER: _ClassVar[int]
    GROK_CALLS_FIELD_NUMBER: _ClassVar[int]
    CEREBRAS_CALLS_FIELD_NUMBER: _ClassVar[int]
    WEEK_START_FIELD_NUMBER: _ClassVar[int]
    LAST_RESET_FIELD_NUMBER: _ClassVar[int]
    USAGE_PCT_FIELD_NUMBER: _ClassVar[int]
    BUDGET_HEALTH_FIELD_NUMBER: _ClassVar[int]
    weekly_limit: int
    weekly_used: int
    weekly_remaining: int
    grok_calls: int
    cerebras_calls: int
    week_start: str
    last_reset: str
    usage_pct: float
    budget_health: str
    def __init__(self, weekly_limit: _Optional[int] = ..., weekly_used: _Optional[int] = ..., weekly_remaining: _Optional[int] = ..., grok_calls: _Optional[int] = ..., cerebras_calls: _Optional[int] = ..., week_start: _Optional[str] = ..., last_reset: _Optional[str] = ..., usage_pct: _Optional[float] = ..., budget_health: _Optional[str] = ...) -> None: ...

class GetPooledBudgetRequest(_message.Message):
    __slots__ = ("pool_id",)
    POOL_ID_FIELD_NUMBER: _ClassVar[int]
    pool_id: str
    def __init__(self, pool_id: _Optional[str] = ...) -> None: ...

class GetPooledBudgetResponse(_message.Message):
    __slots__ = ("success", "budget", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    BUDGET_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    budget: PooledBudgetStatus
    error: str
    def __init__(self, success: bool = ..., budget: _Optional[_Union[PooledBudgetStatus, _Mapping]] = ..., error: _Optional[str] = ...) -> None: ...

class QualityAssessment(_message.Message):
    __slots__ = ("id", "source_type", "source_id", "coherence_score", "coverage_score", "novelty_score", "weighted_reward", "is_textbook_quality", "evaluator_type", "created_at")
    ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    SOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    COHERENCE_SCORE_FIELD_NUMBER: _ClassVar[int]
    COVERAGE_SCORE_FIELD_NUMBER: _ClassVar[int]
    NOVELTY_SCORE_FIELD_NUMBER: _ClassVar[int]
    WEIGHTED_REWARD_FIELD_NUMBER: _ClassVar[int]
    IS_TEXTBOOK_QUALITY_FIELD_NUMBER: _ClassVar[int]
    EVALUATOR_TYPE_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    id: int
    source_type: str
    source_id: str
    coherence_score: float
    coverage_score: float
    novelty_score: float
    weighted_reward: float
    is_textbook_quality: bool
    evaluator_type: str
    created_at: str
    def __init__(self, id: _Optional[int] = ..., source_type: _Optional[str] = ..., source_id: _Optional[str] = ..., coherence_score: _Optional[float] = ..., coverage_score: _Optional[float] = ..., novelty_score: _Optional[float] = ..., weighted_reward: _Optional[float] = ..., is_textbook_quality: bool = ..., evaluator_type: _Optional[str] = ..., created_at: _Optional[str] = ...) -> None: ...

class GetQualitySummaryRequest(_message.Message):
    __slots__ = ("source_type", "limit")
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    source_type: str
    limit: int
    def __init__(self, source_type: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class QualitySourceSummary(_message.Message):
    __slots__ = ("source_type", "total_assessments", "textbook_quality_count", "textbook_quality_pct", "avg_coherence", "avg_coverage", "avg_novelty", "avg_weighted_reward")
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    TOTAL_ASSESSMENTS_FIELD_NUMBER: _ClassVar[int]
    TEXTBOOK_QUALITY_COUNT_FIELD_NUMBER: _ClassVar[int]
    TEXTBOOK_QUALITY_PCT_FIELD_NUMBER: _ClassVar[int]
    AVG_COHERENCE_FIELD_NUMBER: _ClassVar[int]
    AVG_COVERAGE_FIELD_NUMBER: _ClassVar[int]
    AVG_NOVELTY_FIELD_NUMBER: _ClassVar[int]
    AVG_WEIGHTED_REWARD_FIELD_NUMBER: _ClassVar[int]
    source_type: str
    total_assessments: int
    textbook_quality_count: int
    textbook_quality_pct: float
    avg_coherence: float
    avg_coverage: float
    avg_novelty: float
    avg_weighted_reward: float
    def __init__(self, source_type: _Optional[str] = ..., total_assessments: _Optional[int] = ..., textbook_quality_count: _Optional[int] = ..., textbook_quality_pct: _Optional[float] = ..., avg_coherence: _Optional[float] = ..., avg_coverage: _Optional[float] = ..., avg_novelty: _Optional[float] = ..., avg_weighted_reward: _Optional[float] = ...) -> None: ...

class GetQualitySummaryResponse(_message.Message):
    __slots__ = ("success", "total_assessments", "textbook_quality_count", "textbook_quality_pct", "avg_coherence", "avg_coverage", "avg_novelty", "avg_weighted_reward", "recent", "error", "assessments")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_ASSESSMENTS_FIELD_NUMBER: _ClassVar[int]
    TEXTBOOK_QUALITY_COUNT_FIELD_NUMBER: _ClassVar[int]
    TEXTBOOK_QUALITY_PCT_FIELD_NUMBER: _ClassVar[int]
    AVG_COHERENCE_FIELD_NUMBER: _ClassVar[int]
    AVG_COVERAGE_FIELD_NUMBER: _ClassVar[int]
    AVG_NOVELTY_FIELD_NUMBER: _ClassVar[int]
    AVG_WEIGHTED_REWARD_FIELD_NUMBER: _ClassVar[int]
    RECENT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    ASSESSMENTS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    total_assessments: int
    textbook_quality_count: int
    textbook_quality_pct: float
    avg_coherence: float
    avg_coverage: float
    avg_novelty: float
    avg_weighted_reward: float
    recent: _containers.RepeatedCompositeFieldContainer[QualityAssessment]
    error: str
    assessments: _containers.RepeatedCompositeFieldContainer[QualitySourceSummary]
    def __init__(self, success: bool = ..., total_assessments: _Optional[int] = ..., textbook_quality_count: _Optional[int] = ..., textbook_quality_pct: _Optional[float] = ..., avg_coherence: _Optional[float] = ..., avg_coverage: _Optional[float] = ..., avg_novelty: _Optional[float] = ..., avg_weighted_reward: _Optional[float] = ..., recent: _Optional[_Iterable[_Union[QualityAssessment, _Mapping]]] = ..., error: _Optional[str] = ..., assessments: _Optional[_Iterable[_Union[QualitySourceSummary, _Mapping]]] = ...) -> None: ...

class ListRecommendationsRequest(_message.Message):
    __slots__ = ("status", "audit_id", "limit", "status_filter", "severity_filter")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    AUDIT_ID_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    STATUS_FILTER_FIELD_NUMBER: _ClassVar[int]
    SEVERITY_FILTER_FIELD_NUMBER: _ClassVar[int]
    status: str
    audit_id: str
    limit: int
    status_filter: str
    severity_filter: str
    def __init__(self, status: _Optional[str] = ..., audit_id: _Optional[str] = ..., limit: _Optional[int] = ..., status_filter: _Optional[str] = ..., severity_filter: _Optional[str] = ...) -> None: ...

class ListRecommendationsResponse(_message.Message):
    __slots__ = ("success", "recommendations", "total_count", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    RECOMMENDATIONS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_COUNT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    recommendations: _containers.RepeatedCompositeFieldContainer[AuditRecommendation]
    total_count: int
    error: str
    def __init__(self, success: bool = ..., recommendations: _Optional[_Iterable[_Union[AuditRecommendation, _Mapping]]] = ..., total_count: _Optional[int] = ..., error: _Optional[str] = ...) -> None: ...

class UpdateRecommendationRequest(_message.Message):
    __slots__ = ("recommendation_id", "new_status")
    RECOMMENDATION_ID_FIELD_NUMBER: _ClassVar[int]
    NEW_STATUS_FIELD_NUMBER: _ClassVar[int]
    recommendation_id: str
    new_status: str
    def __init__(self, recommendation_id: _Optional[str] = ..., new_status: _Optional[str] = ...) -> None: ...

class UpdateRecommendationResponse(_message.Message):
    __slots__ = ("success", "recommendation", "error", "recommendation_id", "new_status")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    RECOMMENDATION_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    RECOMMENDATION_ID_FIELD_NUMBER: _ClassVar[int]
    NEW_STATUS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    recommendation: AuditRecommendation
    error: str
    recommendation_id: str
    new_status: str
    def __init__(self, success: bool = ..., recommendation: _Optional[_Union[AuditRecommendation, _Mapping]] = ..., error: _Optional[str] = ..., recommendation_id: _Optional[str] = ..., new_status: _Optional[str] = ...) -> None: ...

class CLTExtractRequest(_message.Message):
    __slots__ = ("text", "layer_indices", "top_k", "model_name", "device")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    LAYER_INDICES_FIELD_NUMBER: _ClassVar[int]
    TOP_K_FIELD_NUMBER: _ClassVar[int]
    MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    DEVICE_FIELD_NUMBER: _ClassVar[int]
    text: str
    layer_indices: _containers.RepeatedScalarFieldContainer[int]
    top_k: int
    model_name: str
    device: str
    def __init__(self, text: _Optional[str] = ..., layer_indices: _Optional[_Iterable[int]] = ..., top_k: _Optional[int] = ..., model_name: _Optional[str] = ..., device: _Optional[str] = ...) -> None: ...

class SparseFeature(_message.Message):
    __slots__ = ("layer_idx", "position", "feature_idx", "activation", "semantic_label")
    LAYER_IDX_FIELD_NUMBER: _ClassVar[int]
    POSITION_FIELD_NUMBER: _ClassVar[int]
    FEATURE_IDX_FIELD_NUMBER: _ClassVar[int]
    ACTIVATION_FIELD_NUMBER: _ClassVar[int]
    SEMANTIC_LABEL_FIELD_NUMBER: _ClassVar[int]
    layer_idx: int
    position: int
    feature_idx: int
    activation: float
    semantic_label: str
    def __init__(self, layer_idx: _Optional[int] = ..., position: _Optional[int] = ..., feature_idx: _Optional[int] = ..., activation: _Optional[float] = ..., semantic_label: _Optional[str] = ...) -> None: ...

class CLTExtractResponse(_message.Message):
    __slots__ = ("success", "features", "total_positions", "sparsity", "model_used", "duration_ms", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    FEATURES_FIELD_NUMBER: _ClassVar[int]
    TOTAL_POSITIONS_FIELD_NUMBER: _ClassVar[int]
    SPARSITY_FIELD_NUMBER: _ClassVar[int]
    MODEL_USED_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    features: _containers.RepeatedCompositeFieldContainer[SparseFeature]
    total_positions: int
    sparsity: float
    model_used: str
    duration_ms: int
    error: str
    def __init__(self, success: bool = ..., features: _Optional[_Iterable[_Union[SparseFeature, _Mapping]]] = ..., total_positions: _Optional[int] = ..., sparsity: _Optional[float] = ..., model_used: _Optional[str] = ..., duration_ms: _Optional[int] = ..., error: _Optional[str] = ...) -> None: ...

class CLTAttributeRequest(_message.Message):
    __slots__ = ("text", "target_positions", "threshold", "model_name", "device")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    TARGET_POSITIONS_FIELD_NUMBER: _ClassVar[int]
    THRESHOLD_FIELD_NUMBER: _ClassVar[int]
    MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    DEVICE_FIELD_NUMBER: _ClassVar[int]
    text: str
    target_positions: _containers.RepeatedScalarFieldContainer[int]
    threshold: float
    model_name: str
    device: str
    def __init__(self, text: _Optional[str] = ..., target_positions: _Optional[_Iterable[int]] = ..., threshold: _Optional[float] = ..., model_name: _Optional[str] = ..., device: _Optional[str] = ...) -> None: ...

class CLTAttributionEdge(_message.Message):
    __slots__ = ("source_layer", "source_feature", "target_layer", "target_feature", "weight")
    SOURCE_LAYER_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FEATURE_FIELD_NUMBER: _ClassVar[int]
    TARGET_LAYER_FIELD_NUMBER: _ClassVar[int]
    TARGET_FEATURE_FIELD_NUMBER: _ClassVar[int]
    WEIGHT_FIELD_NUMBER: _ClassVar[int]
    source_layer: int
    source_feature: int
    target_layer: int
    target_feature: int
    weight: float
    def __init__(self, source_layer: _Optional[int] = ..., source_feature: _Optional[int] = ..., target_layer: _Optional[int] = ..., target_feature: _Optional[int] = ..., weight: _Optional[float] = ...) -> None: ...

class CLTAttributeResponse(_message.Message):
    __slots__ = ("success", "edges", "dot_graph", "edge_count", "model_used", "duration_ms", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    EDGES_FIELD_NUMBER: _ClassVar[int]
    DOT_GRAPH_FIELD_NUMBER: _ClassVar[int]
    EDGE_COUNT_FIELD_NUMBER: _ClassVar[int]
    MODEL_USED_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    edges: _containers.RepeatedCompositeFieldContainer[CLTAttributionEdge]
    dot_graph: str
    edge_count: int
    model_used: str
    duration_ms: int
    error: str
    def __init__(self, success: bool = ..., edges: _Optional[_Iterable[_Union[CLTAttributionEdge, _Mapping]]] = ..., dot_graph: _Optional[str] = ..., edge_count: _Optional[int] = ..., model_used: _Optional[str] = ..., duration_ms: _Optional[int] = ..., error: _Optional[str] = ...) -> None: ...

class CLTStatusRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CLTStatusResponse(_message.Message):
    __slots__ = ("available", "models", "loaded_model", "features_per_layer", "l0_sparsity", "memory_used_mb", "gpu_ids", "error")
    AVAILABLE_FIELD_NUMBER: _ClassVar[int]
    MODELS_FIELD_NUMBER: _ClassVar[int]
    LOADED_MODEL_FIELD_NUMBER: _ClassVar[int]
    FEATURES_PER_LAYER_FIELD_NUMBER: _ClassVar[int]
    L0_SPARSITY_FIELD_NUMBER: _ClassVar[int]
    MEMORY_USED_MB_FIELD_NUMBER: _ClassVar[int]
    GPU_IDS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    available: bool
    models: _containers.RepeatedScalarFieldContainer[str]
    loaded_model: str
    features_per_layer: int
    l0_sparsity: int
    memory_used_mb: float
    gpu_ids: _containers.RepeatedScalarFieldContainer[int]
    error: str
    def __init__(self, available: bool = ..., models: _Optional[_Iterable[str]] = ..., loaded_model: _Optional[str] = ..., features_per_layer: _Optional[int] = ..., l0_sparsity: _Optional[int] = ..., memory_used_mb: _Optional[float] = ..., gpu_ids: _Optional[_Iterable[int]] = ..., error: _Optional[str] = ...) -> None: ...

class HealthObserverStatusRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class HealthObserverStatusResponse(_message.Message):
    __slots__ = ("running", "enabled", "poll_count", "last_poll_at", "active_incidents", "incidents", "metrics", "config")
    RUNNING_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    POLL_COUNT_FIELD_NUMBER: _ClassVar[int]
    LAST_POLL_AT_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_INCIDENTS_FIELD_NUMBER: _ClassVar[int]
    INCIDENTS_FIELD_NUMBER: _ClassVar[int]
    METRICS_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    running: bool
    enabled: bool
    poll_count: int
    last_poll_at: str
    active_incidents: int
    incidents: _containers.RepeatedCompositeFieldContainer[HealthIncident]
    metrics: HealthObserverMetrics
    config: HealthObserverConfig
    def __init__(self, running: bool = ..., enabled: bool = ..., poll_count: _Optional[int] = ..., last_poll_at: _Optional[str] = ..., active_incidents: _Optional[int] = ..., incidents: _Optional[_Iterable[_Union[HealthIncident, _Mapping]]] = ..., metrics: _Optional[_Union[HealthObserverMetrics, _Mapping]] = ..., config: _Optional[_Union[HealthObserverConfig, _Mapping]] = ...) -> None: ...

class HealthIncident(_message.Message):
    __slots__ = ("incident_id", "fingerprint", "endpoint", "failure_mode_id", "rpn_score", "rpn_severity", "rpn_occurrence", "rpn_detection", "current_tier", "sequence_id", "created_at", "last_check_at", "attempts", "github_issue", "status")
    INCIDENT_ID_FIELD_NUMBER: _ClassVar[int]
    FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    ENDPOINT_FIELD_NUMBER: _ClassVar[int]
    FAILURE_MODE_ID_FIELD_NUMBER: _ClassVar[int]
    RPN_SCORE_FIELD_NUMBER: _ClassVar[int]
    RPN_SEVERITY_FIELD_NUMBER: _ClassVar[int]
    RPN_OCCURRENCE_FIELD_NUMBER: _ClassVar[int]
    RPN_DETECTION_FIELD_NUMBER: _ClassVar[int]
    CURRENT_TIER_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    LAST_CHECK_AT_FIELD_NUMBER: _ClassVar[int]
    ATTEMPTS_FIELD_NUMBER: _ClassVar[int]
    GITHUB_ISSUE_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    incident_id: str
    fingerprint: str
    endpoint: str
    failure_mode_id: str
    rpn_score: int
    rpn_severity: int
    rpn_occurrence: int
    rpn_detection: int
    current_tier: int
    sequence_id: str
    created_at: str
    last_check_at: str
    attempts: int
    github_issue: int
    status: str
    def __init__(self, incident_id: _Optional[str] = ..., fingerprint: _Optional[str] = ..., endpoint: _Optional[str] = ..., failure_mode_id: _Optional[str] = ..., rpn_score: _Optional[int] = ..., rpn_severity: _Optional[int] = ..., rpn_occurrence: _Optional[int] = ..., rpn_detection: _Optional[int] = ..., current_tier: _Optional[int] = ..., sequence_id: _Optional[str] = ..., created_at: _Optional[str] = ..., last_check_at: _Optional[str] = ..., attempts: _Optional[int] = ..., github_issue: _Optional[int] = ..., status: _Optional[str] = ...) -> None: ...

class HealthObserverMetrics(_message.Message):
    __slots__ = ("incidents_created", "incidents_resolved", "acp_escalations")
    INCIDENTS_CREATED_FIELD_NUMBER: _ClassVar[int]
    INCIDENTS_RESOLVED_FIELD_NUMBER: _ClassVar[int]
    ACP_ESCALATIONS_FIELD_NUMBER: _ClassVar[int]
    incidents_created: int
    incidents_resolved: int
    acp_escalations: int
    def __init__(self, incidents_created: _Optional[int] = ..., incidents_resolved: _Optional[int] = ..., acp_escalations: _Optional[int] = ...) -> None: ...

class HealthObserverConfig(_message.Message):
    __slots__ = ("poll_interval", "escalate_to_acp", "github_repo")
    POLL_INTERVAL_FIELD_NUMBER: _ClassVar[int]
    ESCALATE_TO_ACP_FIELD_NUMBER: _ClassVar[int]
    GITHUB_REPO_FIELD_NUMBER: _ClassVar[int]
    poll_interval: float
    escalate_to_acp: bool
    github_repo: str
    def __init__(self, poll_interval: _Optional[float] = ..., escalate_to_acp: bool = ..., github_repo: _Optional[str] = ...) -> None: ...

class HealthObserverControlRequest(_message.Message):
    __slots__ = ("start",)
    START_FIELD_NUMBER: _ClassVar[int]
    start: bool
    def __init__(self, start: bool = ...) -> None: ...

class ForceHealthCheckRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ForceHealthCheckResponse(_message.Message):
    __slots__ = ("healthy", "summary", "passed", "warnings", "failures", "new_incidents", "checks")
    HEALTHY_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    PASSED_FIELD_NUMBER: _ClassVar[int]
    WARNINGS_FIELD_NUMBER: _ClassVar[int]
    FAILURES_FIELD_NUMBER: _ClassVar[int]
    NEW_INCIDENTS_FIELD_NUMBER: _ClassVar[int]
    CHECKS_FIELD_NUMBER: _ClassVar[int]
    healthy: bool
    summary: str
    passed: int
    warnings: int
    failures: int
    new_incidents: int
    checks: _containers.RepeatedCompositeFieldContainer[HealthCheckResult]
    def __init__(self, healthy: bool = ..., summary: _Optional[str] = ..., passed: _Optional[int] = ..., warnings: _Optional[int] = ..., failures: _Optional[int] = ..., new_incidents: _Optional[int] = ..., checks: _Optional[_Iterable[_Union[HealthCheckResult, _Mapping]]] = ...) -> None: ...

class HealthCheckResult(_message.Message):
    __slots__ = ("name", "status", "message", "heuristic_id", "details_json")
    NAME_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    HEURISTIC_ID_FIELD_NUMBER: _ClassVar[int]
    DETAILS_JSON_FIELD_NUMBER: _ClassVar[int]
    name: str
    status: str
    message: str
    heuristic_id: str
    details_json: str
    def __init__(self, name: _Optional[str] = ..., status: _Optional[str] = ..., message: _Optional[str] = ..., heuristic_id: _Optional[str] = ..., details_json: _Optional[str] = ...) -> None: ...

class GetIncidentDetailRequest(_message.Message):
    __slots__ = ("fingerprint",)
    FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    fingerprint: str
    def __init__(self, fingerprint: _Optional[str] = ...) -> None: ...

class GetIncidentDetailResponse(_message.Message):
    __slots__ = ("incident", "found", "healing_events_json", "acp_history_json", "github_issue_detail_json")
    INCIDENT_FIELD_NUMBER: _ClassVar[int]
    FOUND_FIELD_NUMBER: _ClassVar[int]
    HEALING_EVENTS_JSON_FIELD_NUMBER: _ClassVar[int]
    ACP_HISTORY_JSON_FIELD_NUMBER: _ClassVar[int]
    GITHUB_ISSUE_DETAIL_JSON_FIELD_NUMBER: _ClassVar[int]
    incident: HealthIncident
    found: bool
    healing_events_json: str
    acp_history_json: str
    github_issue_detail_json: str
    def __init__(self, incident: _Optional[_Union[HealthIncident, _Mapping]] = ..., found: bool = ..., healing_events_json: _Optional[str] = ..., acp_history_json: _Optional[str] = ..., github_issue_detail_json: _Optional[str] = ...) -> None: ...

class ListIncidentsRequest(_message.Message):
    __slots__ = ("status",)
    STATUS_FIELD_NUMBER: _ClassVar[int]
    status: str
    def __init__(self, status: _Optional[str] = ...) -> None: ...

class ListIncidentsResponse(_message.Message):
    __slots__ = ("incidents",)
    INCIDENTS_FIELD_NUMBER: _ClassVar[int]
    incidents: _containers.RepeatedCompositeFieldContainer[HealthIncident]
    def __init__(self, incidents: _Optional[_Iterable[_Union[HealthIncident, _Mapping]]] = ...) -> None: ...

class ResolveIncidentRequest(_message.Message):
    __slots__ = ("fingerprint",)
    FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    fingerprint: str
    def __init__(self, fingerprint: _Optional[str] = ...) -> None: ...

class ResolveIncidentResponse(_message.Message):
    __slots__ = ("resolved", "fingerprint", "was_active", "note")
    RESOLVED_FIELD_NUMBER: _ClassVar[int]
    FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    WAS_ACTIVE_FIELD_NUMBER: _ClassVar[int]
    NOTE_FIELD_NUMBER: _ClassVar[int]
    resolved: bool
    fingerprint: str
    was_active: bool
    note: str
    def __init__(self, resolved: bool = ..., fingerprint: _Optional[str] = ..., was_active: bool = ..., note: _Optional[str] = ...) -> None: ...

class GetOrphanedIssuesRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class GetOrphanedIssuesResponse(_message.Message):
    __slots__ = ("orphans",)
    ORPHANS_FIELD_NUMBER: _ClassVar[int]
    orphans: _containers.RepeatedCompositeFieldContainer[OrphanedGitHubIssue]
    def __init__(self, orphans: _Optional[_Iterable[_Union[OrphanedGitHubIssue, _Mapping]]] = ...) -> None: ...

class OrphanedGitHubIssue(_message.Message):
    __slots__ = ("issue_number", "repo", "fingerprint", "created_at", "issue_url")
    ISSUE_NUMBER_FIELD_NUMBER: _ClassVar[int]
    REPO_FIELD_NUMBER: _ClassVar[int]
    FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    ISSUE_URL_FIELD_NUMBER: _ClassVar[int]
    issue_number: int
    repo: str
    fingerprint: str
    created_at: str
    issue_url: str
    def __init__(self, issue_number: _Optional[int] = ..., repo: _Optional[str] = ..., fingerprint: _Optional[str] = ..., created_at: _Optional[str] = ..., issue_url: _Optional[str] = ...) -> None: ...

class XBookmarksAuthRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class XBookmarksAuthResponse(_message.Message):
    __slots__ = ("auth_url", "state", "verifier")
    AUTH_URL_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    VERIFIER_FIELD_NUMBER: _ClassVar[int]
    auth_url: str
    state: str
    verifier: str
    def __init__(self, auth_url: _Optional[str] = ..., state: _Optional[str] = ..., verifier: _Optional[str] = ...) -> None: ...

class XBookmarksCompleteAuthRequest(_message.Message):
    __slots__ = ("code", "verifier")
    CODE_FIELD_NUMBER: _ClassVar[int]
    VERIFIER_FIELD_NUMBER: _ClassVar[int]
    code: str
    verifier: str
    def __init__(self, code: _Optional[str] = ..., verifier: _Optional[str] = ...) -> None: ...

class XBookmarksCompleteAuthByStateRequest(_message.Message):
    __slots__ = ("code", "state")
    CODE_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    code: str
    state: str
    def __init__(self, code: _Optional[str] = ..., state: _Optional[str] = ...) -> None: ...

class XBookmarksCompleteAuthResponse(_message.Message):
    __slots__ = ("success", "user_id", "username", "scopes", "expires_at", "error", "message")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    SCOPES_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    user_id: str
    username: str
    scopes: _containers.RepeatedScalarFieldContainer[str]
    expires_at: str
    error: str
    message: str
    def __init__(self, success: bool = ..., user_id: _Optional[str] = ..., username: _Optional[str] = ..., scopes: _Optional[_Iterable[str]] = ..., expires_at: _Optional[str] = ..., error: _Optional[str] = ..., message: _Optional[str] = ...) -> None: ...

class XBookmarksAuthStatusRequest(_message.Message):
    __slots__ = ("user_id",)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    def __init__(self, user_id: _Optional[str] = ...) -> None: ...

class XBookmarksAuthStatusResponse(_message.Message):
    __slots__ = ("authenticated", "user_id", "username", "expires_at", "scopes", "error", "guru_code", "action_required", "guidance_message")
    AUTHENTICATED_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    SCOPES_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    GURU_CODE_FIELD_NUMBER: _ClassVar[int]
    ACTION_REQUIRED_FIELD_NUMBER: _ClassVar[int]
    GUIDANCE_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    authenticated: bool
    user_id: str
    username: str
    expires_at: str
    scopes: _containers.RepeatedScalarFieldContainer[str]
    error: str
    guru_code: str
    action_required: str
    guidance_message: str
    def __init__(self, authenticated: bool = ..., user_id: _Optional[str] = ..., username: _Optional[str] = ..., expires_at: _Optional[str] = ..., scopes: _Optional[_Iterable[str]] = ..., error: _Optional[str] = ..., guru_code: _Optional[str] = ..., action_required: _Optional[str] = ..., guidance_message: _Optional[str] = ...) -> None: ...

class XBookmarksSyncRequest(_message.Message):
    __slots__ = ("user_id", "full_sync", "folder_id")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    FULL_SYNC_FIELD_NUMBER: _ClassVar[int]
    FOLDER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    full_sync: bool
    folder_id: str
    def __init__(self, user_id: _Optional[str] = ..., full_sync: bool = ..., folder_id: _Optional[str] = ...) -> None: ...

class XBookmarksSyncResponse(_message.Message):
    __slots__ = ("started", "run_id", "message", "status", "bookmarks_fetched", "iceberg_written", "queue_items", "action_required", "guidance_message")
    STARTED_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    BOOKMARKS_FETCHED_FIELD_NUMBER: _ClassVar[int]
    ICEBERG_WRITTEN_FIELD_NUMBER: _ClassVar[int]
    QUEUE_ITEMS_FIELD_NUMBER: _ClassVar[int]
    ACTION_REQUIRED_FIELD_NUMBER: _ClassVar[int]
    GUIDANCE_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    started: bool
    run_id: int
    message: str
    status: str
    bookmarks_fetched: int
    iceberg_written: int
    queue_items: int
    action_required: str
    guidance_message: str
    def __init__(self, started: bool = ..., run_id: _Optional[int] = ..., message: _Optional[str] = ..., status: _Optional[str] = ..., bookmarks_fetched: _Optional[int] = ..., iceberg_written: _Optional[int] = ..., queue_items: _Optional[int] = ..., action_required: _Optional[str] = ..., guidance_message: _Optional[str] = ...) -> None: ...

class XBookmarksSyncStatusRequest(_message.Message):
    __slots__ = ("user_id",)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    def __init__(self, user_id: _Optional[str] = ...) -> None: ...

class XBookmarksSyncStatusResponse(_message.Message):
    __slots__ = ("configured", "user_id", "username", "token_status", "folder_count", "bookmark_count", "queued_requests", "last_sync_at", "last_run_status", "action_required", "guidance_message")
    CONFIGURED_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    TOKEN_STATUS_FIELD_NUMBER: _ClassVar[int]
    FOLDER_COUNT_FIELD_NUMBER: _ClassVar[int]
    BOOKMARK_COUNT_FIELD_NUMBER: _ClassVar[int]
    QUEUED_REQUESTS_FIELD_NUMBER: _ClassVar[int]
    LAST_SYNC_AT_FIELD_NUMBER: _ClassVar[int]
    LAST_RUN_STATUS_FIELD_NUMBER: _ClassVar[int]
    ACTION_REQUIRED_FIELD_NUMBER: _ClassVar[int]
    GUIDANCE_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    configured: bool
    user_id: str
    username: str
    token_status: str
    folder_count: int
    bookmark_count: int
    queued_requests: int
    last_sync_at: str
    last_run_status: str
    action_required: str
    guidance_message: str
    def __init__(self, configured: bool = ..., user_id: _Optional[str] = ..., username: _Optional[str] = ..., token_status: _Optional[str] = ..., folder_count: _Optional[int] = ..., bookmark_count: _Optional[int] = ..., queued_requests: _Optional[int] = ..., last_sync_at: _Optional[str] = ..., last_run_status: _Optional[str] = ..., action_required: _Optional[str] = ..., guidance_message: _Optional[str] = ...) -> None: ...

class XBookmarksServiceStatusRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class XBookmarksServiceStatusResponse(_message.Message):
    __slots__ = ("running", "total_syncs", "total_bookmarks", "last_sync_at", "queue_poll_interval_s")
    RUNNING_FIELD_NUMBER: _ClassVar[int]
    TOTAL_SYNCS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_BOOKMARKS_FIELD_NUMBER: _ClassVar[int]
    LAST_SYNC_AT_FIELD_NUMBER: _ClassVar[int]
    QUEUE_POLL_INTERVAL_S_FIELD_NUMBER: _ClassVar[int]
    running: bool
    total_syncs: int
    total_bookmarks: int
    last_sync_at: str
    queue_poll_interval_s: int
    def __init__(self, running: bool = ..., total_syncs: _Optional[int] = ..., total_bookmarks: _Optional[int] = ..., last_sync_at: _Optional[str] = ..., queue_poll_interval_s: _Optional[int] = ...) -> None: ...

class XBookmarkFolder(_message.Message):
    __slots__ = ("id", "name", "kb_path", "bookmark_count")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    KB_PATH_FIELD_NUMBER: _ClassVar[int]
    BOOKMARK_COUNT_FIELD_NUMBER: _ClassVar[int]
    id: str
    name: str
    kb_path: str
    bookmark_count: int
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., kb_path: _Optional[str] = ..., bookmark_count: _Optional[int] = ...) -> None: ...

class XBookmarksListFoldersRequest(_message.Message):
    __slots__ = ("user_id",)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    def __init__(self, user_id: _Optional[str] = ...) -> None: ...

class XBookmarksListFoldersResponse(_message.Message):
    __slots__ = ("folders", "folders_available", "message")
    FOLDERS_FIELD_NUMBER: _ClassVar[int]
    FOLDERS_AVAILABLE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    folders: _containers.RepeatedCompositeFieldContainer[XBookmarkFolder]
    folders_available: bool
    message: str
    def __init__(self, folders: _Optional[_Iterable[_Union[XBookmarkFolder, _Mapping]]] = ..., folders_available: bool = ..., message: _Optional[str] = ...) -> None: ...

class XBookmarksQueueStatusRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class XBookmarksQueueStatusResponse(_message.Message):
    __slots__ = ("queue_depth", "cooldown_end_iso", "cooldown_seconds", "can_request")
    QUEUE_DEPTH_FIELD_NUMBER: _ClassVar[int]
    COOLDOWN_END_ISO_FIELD_NUMBER: _ClassVar[int]
    COOLDOWN_SECONDS_FIELD_NUMBER: _ClassVar[int]
    CAN_REQUEST_FIELD_NUMBER: _ClassVar[int]
    queue_depth: int
    cooldown_end_iso: str
    cooldown_seconds: int
    can_request: bool
    def __init__(self, queue_depth: _Optional[int] = ..., cooldown_end_iso: _Optional[str] = ..., cooldown_seconds: _Optional[int] = ..., can_request: bool = ...) -> None: ...

class XBookmarksEmitTestEventRequest(_message.Message):
    __slots__ = ("event_type",)
    EVENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    event_type: str
    def __init__(self, event_type: _Optional[str] = ...) -> None: ...

class XBookmarksEmitTestEventResponse(_message.Message):
    __slots__ = ("success", "event_type", "message")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    EVENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    event_type: str
    message: str
    def __init__(self, success: bool = ..., event_type: _Optional[str] = ..., message: _Optional[str] = ...) -> None: ...

class ListHFDatasetsRequest(_message.Message):
    __slots__ = ("limit",)
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    limit: int
    def __init__(self, limit: _Optional[int] = ...) -> None: ...

class HFDatasetInfo(_message.Message):
    __slots__ = ("id", "author", "description", "downloads", "likes", "private", "created_at", "last_modified", "tags")
    ID_FIELD_NUMBER: _ClassVar[int]
    AUTHOR_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    DOWNLOADS_FIELD_NUMBER: _ClassVar[int]
    LIKES_FIELD_NUMBER: _ClassVar[int]
    PRIVATE_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    LAST_MODIFIED_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    id: str
    author: str
    description: str
    downloads: int
    likes: int
    private: bool
    created_at: str
    last_modified: str
    tags: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, id: _Optional[str] = ..., author: _Optional[str] = ..., description: _Optional[str] = ..., downloads: _Optional[int] = ..., likes: _Optional[int] = ..., private: bool = ..., created_at: _Optional[str] = ..., last_modified: _Optional[str] = ..., tags: _Optional[_Iterable[str]] = ...) -> None: ...

class ListHFDatasetsResponse(_message.Message):
    __slots__ = ("datasets", "count", "saved_to", "error")
    DATASETS_FIELD_NUMBER: _ClassVar[int]
    COUNT_FIELD_NUMBER: _ClassVar[int]
    SAVED_TO_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    datasets: _containers.RepeatedCompositeFieldContainer[HFDatasetInfo]
    count: int
    saved_to: str
    error: str
    def __init__(self, datasets: _Optional[_Iterable[_Union[HFDatasetInfo, _Mapping]]] = ..., count: _Optional[int] = ..., saved_to: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class AddExternalDatasetRequest(_message.Message):
    __slots__ = ("dataset_id", "notes")
    DATASET_ID_FIELD_NUMBER: _ClassVar[int]
    NOTES_FIELD_NUMBER: _ClassVar[int]
    dataset_id: str
    notes: str
    def __init__(self, dataset_id: _Optional[str] = ..., notes: _Optional[str] = ...) -> None: ...

class AddExternalDatasetResponse(_message.Message):
    __slots__ = ("success", "dataset_id", "saved_to", "downloads", "likes", "description", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    DATASET_ID_FIELD_NUMBER: _ClassVar[int]
    SAVED_TO_FIELD_NUMBER: _ClassVar[int]
    DOWNLOADS_FIELD_NUMBER: _ClassVar[int]
    LIKES_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    dataset_id: str
    saved_to: str
    downloads: int
    likes: int
    description: str
    error: str
    def __init__(self, success: bool = ..., dataset_id: _Optional[str] = ..., saved_to: _Optional[str] = ..., downloads: _Optional[int] = ..., likes: _Optional[int] = ..., description: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class GetHFDatasetInfoRequest(_message.Message):
    __slots__ = ("dataset_id",)
    DATASET_ID_FIELD_NUMBER: _ClassVar[int]
    dataset_id: str
    def __init__(self, dataset_id: _Optional[str] = ...) -> None: ...

class GetHFDatasetInfoResponse(_message.Message):
    __slots__ = ("info", "url", "error")
    INFO_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    info: HFDatasetInfo
    url: str
    error: str
    def __init__(self, info: _Optional[_Union[HFDatasetInfo, _Mapping]] = ..., url: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class ListKBDatasetsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class KBDatasetEntry(_message.Message):
    __slots__ = ("id", "type", "path")
    ID_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    id: str
    type: str
    path: str
    def __init__(self, id: _Optional[str] = ..., type: _Optional[str] = ..., path: _Optional[str] = ...) -> None: ...

class ListKBDatasetsResponse(_message.Message):
    __slots__ = ("internal", "external", "internal_count", "external_count")
    INTERNAL_FIELD_NUMBER: _ClassVar[int]
    EXTERNAL_FIELD_NUMBER: _ClassVar[int]
    INTERNAL_COUNT_FIELD_NUMBER: _ClassVar[int]
    EXTERNAL_COUNT_FIELD_NUMBER: _ClassVar[int]
    internal: _containers.RepeatedCompositeFieldContainer[KBDatasetEntry]
    external: _containers.RepeatedCompositeFieldContainer[KBDatasetEntry]
    internal_count: int
    external_count: int
    def __init__(self, internal: _Optional[_Iterable[_Union[KBDatasetEntry, _Mapping]]] = ..., external: _Optional[_Iterable[_Union[KBDatasetEntry, _Mapping]]] = ..., internal_count: _Optional[int] = ..., external_count: _Optional[int] = ...) -> None: ...

class ListHFModelsRequest(_message.Message):
    __slots__ = ("limit", "filter")
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    FILTER_FIELD_NUMBER: _ClassVar[int]
    limit: int
    filter: str
    def __init__(self, limit: _Optional[int] = ..., filter: _Optional[str] = ...) -> None: ...

class HFModelInfo(_message.Message):
    __slots__ = ("id", "author", "pipeline_tag", "downloads", "likes", "private", "created_at", "last_modified", "tags", "gated", "library_name")
    ID_FIELD_NUMBER: _ClassVar[int]
    AUTHOR_FIELD_NUMBER: _ClassVar[int]
    PIPELINE_TAG_FIELD_NUMBER: _ClassVar[int]
    DOWNLOADS_FIELD_NUMBER: _ClassVar[int]
    LIKES_FIELD_NUMBER: _ClassVar[int]
    PRIVATE_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    LAST_MODIFIED_FIELD_NUMBER: _ClassVar[int]
    TAGS_FIELD_NUMBER: _ClassVar[int]
    GATED_FIELD_NUMBER: _ClassVar[int]
    LIBRARY_NAME_FIELD_NUMBER: _ClassVar[int]
    id: str
    author: str
    pipeline_tag: str
    downloads: int
    likes: int
    private: bool
    created_at: str
    last_modified: str
    tags: _containers.RepeatedScalarFieldContainer[str]
    gated: bool
    library_name: str
    def __init__(self, id: _Optional[str] = ..., author: _Optional[str] = ..., pipeline_tag: _Optional[str] = ..., downloads: _Optional[int] = ..., likes: _Optional[int] = ..., private: bool = ..., created_at: _Optional[str] = ..., last_modified: _Optional[str] = ..., tags: _Optional[_Iterable[str]] = ..., gated: bool = ..., library_name: _Optional[str] = ...) -> None: ...

class ListHFModelsResponse(_message.Message):
    __slots__ = ("models", "count", "saved_to", "error")
    MODELS_FIELD_NUMBER: _ClassVar[int]
    COUNT_FIELD_NUMBER: _ClassVar[int]
    SAVED_TO_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    models: _containers.RepeatedCompositeFieldContainer[HFModelInfo]
    count: int
    saved_to: str
    error: str
    def __init__(self, models: _Optional[_Iterable[_Union[HFModelInfo, _Mapping]]] = ..., count: _Optional[int] = ..., saved_to: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class AddExternalModelRequest(_message.Message):
    __slots__ = ("model_id", "notes")
    MODEL_ID_FIELD_NUMBER: _ClassVar[int]
    NOTES_FIELD_NUMBER: _ClassVar[int]
    model_id: str
    notes: str
    def __init__(self, model_id: _Optional[str] = ..., notes: _Optional[str] = ...) -> None: ...

class AddExternalModelResponse(_message.Message):
    __slots__ = ("success", "model_id", "saved_to", "downloads", "likes", "pipeline_tag", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MODEL_ID_FIELD_NUMBER: _ClassVar[int]
    SAVED_TO_FIELD_NUMBER: _ClassVar[int]
    DOWNLOADS_FIELD_NUMBER: _ClassVar[int]
    LIKES_FIELD_NUMBER: _ClassVar[int]
    PIPELINE_TAG_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    model_id: str
    saved_to: str
    downloads: int
    likes: int
    pipeline_tag: str
    error: str
    def __init__(self, success: bool = ..., model_id: _Optional[str] = ..., saved_to: _Optional[str] = ..., downloads: _Optional[int] = ..., likes: _Optional[int] = ..., pipeline_tag: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class GetHFModelInfoRequest(_message.Message):
    __slots__ = ("model_id",)
    MODEL_ID_FIELD_NUMBER: _ClassVar[int]
    model_id: str
    def __init__(self, model_id: _Optional[str] = ...) -> None: ...

class GetHFModelInfoResponse(_message.Message):
    __slots__ = ("info", "url", "error")
    INFO_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    info: HFModelInfo
    url: str
    error: str
    def __init__(self, info: _Optional[_Union[HFModelInfo, _Mapping]] = ..., url: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class ListKBModelsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class KBModelEntry(_message.Message):
    __slots__ = ("id", "type", "path", "size_bytes", "pipeline_tag")
    ID_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    PIPELINE_TAG_FIELD_NUMBER: _ClassVar[int]
    id: str
    type: str
    path: str
    size_bytes: int
    pipeline_tag: str
    def __init__(self, id: _Optional[str] = ..., type: _Optional[str] = ..., path: _Optional[str] = ..., size_bytes: _Optional[int] = ..., pipeline_tag: _Optional[str] = ...) -> None: ...

class ListKBModelsResponse(_message.Message):
    __slots__ = ("internal", "external", "internal_count", "external_count", "total_cache_bytes")
    INTERNAL_FIELD_NUMBER: _ClassVar[int]
    EXTERNAL_FIELD_NUMBER: _ClassVar[int]
    INTERNAL_COUNT_FIELD_NUMBER: _ClassVar[int]
    EXTERNAL_COUNT_FIELD_NUMBER: _ClassVar[int]
    TOTAL_CACHE_BYTES_FIELD_NUMBER: _ClassVar[int]
    internal: _containers.RepeatedCompositeFieldContainer[KBModelEntry]
    external: _containers.RepeatedCompositeFieldContainer[KBModelEntry]
    internal_count: int
    external_count: int
    total_cache_bytes: int
    def __init__(self, internal: _Optional[_Iterable[_Union[KBModelEntry, _Mapping]]] = ..., external: _Optional[_Iterable[_Union[KBModelEntry, _Mapping]]] = ..., internal_count: _Optional[int] = ..., external_count: _Optional[int] = ..., total_cache_bytes: _Optional[int] = ...) -> None: ...

class AmbientCycleRequest(_message.Message):
    __slots__ = ("skip_reasoning", "baseline_task_count", "reasoning_prompt")
    SKIP_REASONING_FIELD_NUMBER: _ClassVar[int]
    BASELINE_TASK_COUNT_FIELD_NUMBER: _ClassVar[int]
    REASONING_PROMPT_FIELD_NUMBER: _ClassVar[int]
    skip_reasoning: bool
    baseline_task_count: int
    reasoning_prompt: str
    def __init__(self, skip_reasoning: bool = ..., baseline_task_count: _Optional[int] = ..., reasoning_prompt: _Optional[str] = ...) -> None: ...

class AmbientPhaseEvent(_message.Message):
    __slots__ = ("phase", "message", "progress", "metrics", "timestamp_ms")
    class MetricsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    PHASE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    METRICS_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    phase: AmbientPhase
    message: str
    progress: float
    metrics: _containers.ScalarMap[str, str]
    timestamp_ms: int
    def __init__(self, phase: _Optional[_Union[AmbientPhase, str]] = ..., message: _Optional[str] = ..., progress: _Optional[float] = ..., metrics: _Optional[_Mapping[str, str]] = ..., timestamp_ms: _Optional[int] = ...) -> None: ...

class AmbientCycleResponse(_message.Message):
    __slots__ = ("success", "phases_completed", "total_tasks", "successful_tasks", "endpoint_latencies", "error_message", "duration_ms")
    class EndpointLatenciesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    PHASES_COMPLETED_FIELD_NUMBER: _ClassVar[int]
    TOTAL_TASKS_FIELD_NUMBER: _ClassVar[int]
    SUCCESSFUL_TASKS_FIELD_NUMBER: _ClassVar[int]
    ENDPOINT_LATENCIES_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    phases_completed: int
    total_tasks: int
    successful_tasks: int
    endpoint_latencies: _containers.ScalarMap[str, int]
    error_message: str
    duration_ms: int
    def __init__(self, success: bool = ..., phases_completed: _Optional[int] = ..., total_tasks: _Optional[int] = ..., successful_tasks: _Optional[int] = ..., endpoint_latencies: _Optional[_Mapping[str, int]] = ..., error_message: _Optional[str] = ..., duration_ms: _Optional[int] = ...) -> None: ...

class AmbientStatusResponse(_message.Message):
    __slots__ = ("cycle_running", "current_phase", "cycles_completed", "last_cycle_timestamp_ms", "baseline_endpoints", "reasoning_endpoint", "last_result", "daemon_running", "max_cycles", "current_cycle", "daemon_started_at_ms", "daemon_stopped_at_ms")
    CYCLE_RUNNING_FIELD_NUMBER: _ClassVar[int]
    CURRENT_PHASE_FIELD_NUMBER: _ClassVar[int]
    CYCLES_COMPLETED_FIELD_NUMBER: _ClassVar[int]
    LAST_CYCLE_TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    BASELINE_ENDPOINTS_FIELD_NUMBER: _ClassVar[int]
    REASONING_ENDPOINT_FIELD_NUMBER: _ClassVar[int]
    LAST_RESULT_FIELD_NUMBER: _ClassVar[int]
    DAEMON_RUNNING_FIELD_NUMBER: _ClassVar[int]
    MAX_CYCLES_FIELD_NUMBER: _ClassVar[int]
    CURRENT_CYCLE_FIELD_NUMBER: _ClassVar[int]
    DAEMON_STARTED_AT_MS_FIELD_NUMBER: _ClassVar[int]
    DAEMON_STOPPED_AT_MS_FIELD_NUMBER: _ClassVar[int]
    cycle_running: bool
    current_phase: AmbientPhase
    cycles_completed: int
    last_cycle_timestamp_ms: int
    baseline_endpoints: _containers.RepeatedScalarFieldContainer[str]
    reasoning_endpoint: str
    last_result: AmbientCycleResponse
    daemon_running: bool
    max_cycles: int
    current_cycle: int
    daemon_started_at_ms: int
    daemon_stopped_at_ms: int
    def __init__(self, cycle_running: bool = ..., current_phase: _Optional[_Union[AmbientPhase, str]] = ..., cycles_completed: _Optional[int] = ..., last_cycle_timestamp_ms: _Optional[int] = ..., baseline_endpoints: _Optional[_Iterable[str]] = ..., reasoning_endpoint: _Optional[str] = ..., last_result: _Optional[_Union[AmbientCycleResponse, _Mapping]] = ..., daemon_running: bool = ..., max_cycles: _Optional[int] = ..., current_cycle: _Optional[int] = ..., daemon_started_at_ms: _Optional[int] = ..., daemon_stopped_at_ms: _Optional[int] = ...) -> None: ...

class AmbientStartRequest(_message.Message):
    __slots__ = ("baseline_only", "max_cycles")
    BASELINE_ONLY_FIELD_NUMBER: _ClassVar[int]
    MAX_CYCLES_FIELD_NUMBER: _ClassVar[int]
    baseline_only: bool
    max_cycles: int
    def __init__(self, baseline_only: bool = ..., max_cycles: _Optional[int] = ...) -> None: ...

class AmbientStartResponse(_message.Message):
    __slots__ = ("success", "message", "max_cycles")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    MAX_CYCLES_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    max_cycles: int
    def __init__(self, success: bool = ..., message: _Optional[str] = ..., max_cycles: _Optional[int] = ...) -> None: ...

class AmbientStopRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class AmbientStopResponse(_message.Message):
    __slots__ = ("success", "message", "cycles_completed")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    CYCLES_COMPLETED_FIELD_NUMBER: _ClassVar[int]
    success: bool
    message: str
    cycles_completed: int
    def __init__(self, success: bool = ..., message: _Optional[str] = ..., cycles_completed: _Optional[int] = ...) -> None: ...

class AmbientSubscribeRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class AmbientBufferExportRequest(_message.Message):
    __slots__ = ("kb_root",)
    KB_ROOT_FIELD_NUMBER: _ClassVar[int]
    kb_root: str
    def __init__(self, kb_root: _Optional[str] = ...) -> None: ...

class AmbientBufferExportResponse(_message.Message):
    __slots__ = ("path", "entry_count", "total_bytes", "error")
    PATH_FIELD_NUMBER: _ClassVar[int]
    ENTRY_COUNT_FIELD_NUMBER: _ClassVar[int]
    TOTAL_BYTES_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    path: str
    entry_count: int
    total_bytes: int
    error: str
    def __init__(self, path: _Optional[str] = ..., entry_count: _Optional[int] = ..., total_bytes: _Optional[int] = ..., error: _Optional[str] = ...) -> None: ...

class ObserveStatusRequest(_message.Message):
    __slots__ = ("include_sparklines", "sparkline_points")
    INCLUDE_SPARKLINES_FIELD_NUMBER: _ClassVar[int]
    SPARKLINE_POINTS_FIELD_NUMBER: _ClassVar[int]
    include_sparklines: bool
    sparkline_points: int
    def __init__(self, include_sparklines: bool = ..., sparkline_points: _Optional[int] = ...) -> None: ...

class MetricSnapshot(_message.Message):
    __slots__ = ("name", "display_name", "current_value", "unit", "sparkline_data", "status")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    CURRENT_VALUE_FIELD_NUMBER: _ClassVar[int]
    UNIT_FIELD_NUMBER: _ClassVar[int]
    SPARKLINE_DATA_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    name: str
    display_name: str
    current_value: float
    unit: str
    sparkline_data: _containers.RepeatedScalarFieldContainer[float]
    status: str
    def __init__(self, name: _Optional[str] = ..., display_name: _Optional[str] = ..., current_value: _Optional[float] = ..., unit: _Optional[str] = ..., sparkline_data: _Optional[_Iterable[float]] = ..., status: _Optional[str] = ...) -> None: ...

class EndpointSnapshot(_message.Message):
    __slots__ = ("name", "status", "gpus", "model")
    NAME_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    GPUS_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    name: str
    status: str
    gpus: _containers.RepeatedScalarFieldContainer[int]
    model: str
    def __init__(self, name: _Optional[str] = ..., status: _Optional[str] = ..., gpus: _Optional[_Iterable[int]] = ..., model: _Optional[str] = ...) -> None: ...

class ObserveStatusResponse(_message.Message):
    __slots__ = ("timestamp", "prometheus_available", "metrics", "endpoints", "healthy_endpoints", "unhealthy_endpoints", "active_incidents", "evolution_cycles")
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    PROMETHEUS_AVAILABLE_FIELD_NUMBER: _ClassVar[int]
    METRICS_FIELD_NUMBER: _ClassVar[int]
    ENDPOINTS_FIELD_NUMBER: _ClassVar[int]
    HEALTHY_ENDPOINTS_FIELD_NUMBER: _ClassVar[int]
    UNHEALTHY_ENDPOINTS_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_INCIDENTS_FIELD_NUMBER: _ClassVar[int]
    EVOLUTION_CYCLES_FIELD_NUMBER: _ClassVar[int]
    timestamp: str
    prometheus_available: bool
    metrics: _containers.RepeatedCompositeFieldContainer[MetricSnapshot]
    endpoints: _containers.RepeatedCompositeFieldContainer[EndpointSnapshot]
    healthy_endpoints: int
    unhealthy_endpoints: int
    active_incidents: int
    evolution_cycles: int
    def __init__(self, timestamp: _Optional[str] = ..., prometheus_available: bool = ..., metrics: _Optional[_Iterable[_Union[MetricSnapshot, _Mapping]]] = ..., endpoints: _Optional[_Iterable[_Union[EndpointSnapshot, _Mapping]]] = ..., healthy_endpoints: _Optional[int] = ..., unhealthy_endpoints: _Optional[int] = ..., active_incidents: _Optional[int] = ..., evolution_cycles: _Optional[int] = ...) -> None: ...

class CandidateSummary(_message.Message):
    __slots__ = ("symbol", "company_name", "exchange", "cik", "last_filing_date", "last_filing_type", "pending_filings")
    SYMBOL_FIELD_NUMBER: _ClassVar[int]
    COMPANY_NAME_FIELD_NUMBER: _ClassVar[int]
    EXCHANGE_FIELD_NUMBER: _ClassVar[int]
    CIK_FIELD_NUMBER: _ClassVar[int]
    LAST_FILING_DATE_FIELD_NUMBER: _ClassVar[int]
    LAST_FILING_TYPE_FIELD_NUMBER: _ClassVar[int]
    PENDING_FILINGS_FIELD_NUMBER: _ClassVar[int]
    symbol: str
    company_name: str
    exchange: str
    cik: str
    last_filing_date: str
    last_filing_type: str
    pending_filings: int
    def __init__(self, symbol: _Optional[str] = ..., company_name: _Optional[str] = ..., exchange: _Optional[str] = ..., cik: _Optional[str] = ..., last_filing_date: _Optional[str] = ..., last_filing_type: _Optional[str] = ..., pending_filings: _Optional[int] = ...) -> None: ...

class StrategySummary(_message.Message):
    __slots__ = ("symbol", "category", "allocation_weight", "target_weight", "conviction", "last_analysis_at", "needs_update")
    SYMBOL_FIELD_NUMBER: _ClassVar[int]
    CATEGORY_FIELD_NUMBER: _ClassVar[int]
    ALLOCATION_WEIGHT_FIELD_NUMBER: _ClassVar[int]
    TARGET_WEIGHT_FIELD_NUMBER: _ClassVar[int]
    CONVICTION_FIELD_NUMBER: _ClassVar[int]
    LAST_ANALYSIS_AT_FIELD_NUMBER: _ClassVar[int]
    NEEDS_UPDATE_FIELD_NUMBER: _ClassVar[int]
    symbol: str
    category: str
    allocation_weight: float
    target_weight: float
    conviction: float
    last_analysis_at: str
    needs_update: bool
    def __init__(self, symbol: _Optional[str] = ..., category: _Optional[str] = ..., allocation_weight: _Optional[float] = ..., target_weight: _Optional[float] = ..., conviction: _Optional[float] = ..., last_analysis_at: _Optional[str] = ..., needs_update: bool = ...) -> None: ...

class ProspectsStatusRequest(_message.Message):
    __slots__ = ("profile", "domain", "symbols")
    PROFILE_FIELD_NUMBER: _ClassVar[int]
    DOMAIN_FIELD_NUMBER: _ClassVar[int]
    SYMBOLS_FIELD_NUMBER: _ClassVar[int]
    profile: str
    domain: str
    symbols: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, profile: _Optional[str] = ..., domain: _Optional[str] = ..., symbols: _Optional[_Iterable[str]] = ...) -> None: ...

class ProspectsStatusResponse(_message.Message):
    __slots__ = ("success", "profile", "domain", "candidates", "strategies", "pending_filings", "last_fmp_sync_at", "update_recommended", "update_reason", "error", "buffer_bytes", "buffer_max_bytes", "buffer_entries")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    PROFILE_FIELD_NUMBER: _ClassVar[int]
    DOMAIN_FIELD_NUMBER: _ClassVar[int]
    CANDIDATES_FIELD_NUMBER: _ClassVar[int]
    STRATEGIES_FIELD_NUMBER: _ClassVar[int]
    PENDING_FILINGS_FIELD_NUMBER: _ClassVar[int]
    LAST_FMP_SYNC_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATE_RECOMMENDED_FIELD_NUMBER: _ClassVar[int]
    UPDATE_REASON_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    BUFFER_BYTES_FIELD_NUMBER: _ClassVar[int]
    BUFFER_MAX_BYTES_FIELD_NUMBER: _ClassVar[int]
    BUFFER_ENTRIES_FIELD_NUMBER: _ClassVar[int]
    success: bool
    profile: str
    domain: str
    candidates: _containers.RepeatedCompositeFieldContainer[CandidateSummary]
    strategies: _containers.RepeatedCompositeFieldContainer[StrategySummary]
    pending_filings: int
    last_fmp_sync_at: str
    update_recommended: bool
    update_reason: str
    error: str
    buffer_bytes: int
    buffer_max_bytes: int
    buffer_entries: int
    def __init__(self, success: bool = ..., profile: _Optional[str] = ..., domain: _Optional[str] = ..., candidates: _Optional[_Iterable[_Union[CandidateSummary, _Mapping]]] = ..., strategies: _Optional[_Iterable[_Union[StrategySummary, _Mapping]]] = ..., pending_filings: _Optional[int] = ..., last_fmp_sync_at: _Optional[str] = ..., update_recommended: bool = ..., update_reason: _Optional[str] = ..., error: _Optional[str] = ..., buffer_bytes: _Optional[int] = ..., buffer_max_bytes: _Optional[int] = ..., buffer_entries: _Optional[int] = ...) -> None: ...

class ProspectsCheckRequest(_message.Message):
    __slots__ = ("profile", "domain", "force")
    PROFILE_FIELD_NUMBER: _ClassVar[int]
    DOMAIN_FIELD_NUMBER: _ClassVar[int]
    FORCE_FIELD_NUMBER: _ClassVar[int]
    profile: str
    domain: str
    force: bool
    def __init__(self, profile: _Optional[str] = ..., domain: _Optional[str] = ..., force: bool = ...) -> None: ...

class ProspectsCheckResponse(_message.Message):
    __slots__ = ("success", "update_recommended", "reason", "new_filings_count", "symbols_with_new_filings", "checked_at", "duration_ms", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    UPDATE_RECOMMENDED_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    NEW_FILINGS_COUNT_FIELD_NUMBER: _ClassVar[int]
    SYMBOLS_WITH_NEW_FILINGS_FIELD_NUMBER: _ClassVar[int]
    CHECKED_AT_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    update_recommended: bool
    reason: str
    new_filings_count: int
    symbols_with_new_filings: _containers.RepeatedScalarFieldContainer[str]
    checked_at: str
    duration_ms: int
    error: str
    def __init__(self, success: bool = ..., update_recommended: bool = ..., reason: _Optional[str] = ..., new_filings_count: _Optional[int] = ..., symbols_with_new_filings: _Optional[_Iterable[str]] = ..., checked_at: _Optional[str] = ..., duration_ms: _Optional[int] = ..., error: _Optional[str] = ...) -> None: ...

class ProspectsUpdateRequest(_message.Message):
    __slots__ = ("profile", "domain", "symbols", "force", "filings_per_symbol")
    PROFILE_FIELD_NUMBER: _ClassVar[int]
    DOMAIN_FIELD_NUMBER: _ClassVar[int]
    SYMBOLS_FIELD_NUMBER: _ClassVar[int]
    FORCE_FIELD_NUMBER: _ClassVar[int]
    FILINGS_PER_SYMBOL_FIELD_NUMBER: _ClassVar[int]
    profile: str
    domain: str
    symbols: _containers.RepeatedScalarFieldContainer[str]
    force: bool
    filings_per_symbol: int
    def __init__(self, profile: _Optional[str] = ..., domain: _Optional[str] = ..., symbols: _Optional[_Iterable[str]] = ..., force: bool = ..., filings_per_symbol: _Optional[int] = ...) -> None: ...

class ProspectsUpdateEvent(_message.Message):
    __slots__ = ("type", "timestamp_ms", "progress", "message", "symbol", "filing_type", "data", "sitrep_path")
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        QUEUED: _ClassVar[ProspectsUpdateEvent.Type]
        FMP_SYNC_STARTED: _ClassVar[ProspectsUpdateEvent.Type]
        FMP_SYNC_COMPLETED: _ClassVar[ProspectsUpdateEvent.Type]
        ANALYSIS_STARTED: _ClassVar[ProspectsUpdateEvent.Type]
        FILING_ANALYZED: _ClassVar[ProspectsUpdateEvent.Type]
        SYNTHESIS_STARTED: _ClassVar[ProspectsUpdateEvent.Type]
        SYNTHESIS_COMPLETED: _ClassVar[ProspectsUpdateEvent.Type]
        KB_WRITE_STARTED: _ClassVar[ProspectsUpdateEvent.Type]
        KB_WRITE_COMPLETED: _ClassVar[ProspectsUpdateEvent.Type]
        COMPLETED: _ClassVar[ProspectsUpdateEvent.Type]
        FAILED: _ClassVar[ProspectsUpdateEvent.Type]
    QUEUED: ProspectsUpdateEvent.Type
    FMP_SYNC_STARTED: ProspectsUpdateEvent.Type
    FMP_SYNC_COMPLETED: ProspectsUpdateEvent.Type
    ANALYSIS_STARTED: ProspectsUpdateEvent.Type
    FILING_ANALYZED: ProspectsUpdateEvent.Type
    SYNTHESIS_STARTED: ProspectsUpdateEvent.Type
    SYNTHESIS_COMPLETED: ProspectsUpdateEvent.Type
    KB_WRITE_STARTED: ProspectsUpdateEvent.Type
    KB_WRITE_COMPLETED: ProspectsUpdateEvent.Type
    COMPLETED: ProspectsUpdateEvent.Type
    FAILED: ProspectsUpdateEvent.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    SYMBOL_FIELD_NUMBER: _ClassVar[int]
    FILING_TYPE_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    SITREP_PATH_FIELD_NUMBER: _ClassVar[int]
    type: ProspectsUpdateEvent.Type
    timestamp_ms: int
    progress: float
    message: str
    symbol: str
    filing_type: str
    data: bytes
    sitrep_path: str
    def __init__(self, type: _Optional[_Union[ProspectsUpdateEvent.Type, str]] = ..., timestamp_ms: _Optional[int] = ..., progress: _Optional[float] = ..., message: _Optional[str] = ..., symbol: _Optional[str] = ..., filing_type: _Optional[str] = ..., data: _Optional[bytes] = ..., sitrep_path: _Optional[str] = ...) -> None: ...

class CollectionInfo(_message.Message):
    __slots__ = ("collection_id", "slug", "name", "description", "status", "featured", "total_cards", "pending_cards", "published_cards", "created_at")
    COLLECTION_ID_FIELD_NUMBER: _ClassVar[int]
    SLUG_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    FEATURED_FIELD_NUMBER: _ClassVar[int]
    TOTAL_CARDS_FIELD_NUMBER: _ClassVar[int]
    PENDING_CARDS_FIELD_NUMBER: _ClassVar[int]
    PUBLISHED_CARDS_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    collection_id: str
    slug: str
    name: str
    description: str
    status: str
    featured: bool
    total_cards: int
    pending_cards: int
    published_cards: int
    created_at: str
    def __init__(self, collection_id: _Optional[str] = ..., slug: _Optional[str] = ..., name: _Optional[str] = ..., description: _Optional[str] = ..., status: _Optional[str] = ..., featured: bool = ..., total_cards: _Optional[int] = ..., pending_cards: _Optional[int] = ..., published_cards: _Optional[int] = ..., created_at: _Optional[str] = ...) -> None: ...

class CardInfo(_message.Message):
    __slots__ = ("card_id", "title", "summary", "source_url", "source_type", "image_url", "status", "published_at", "sequence")
    CARD_ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    SOURCE_URL_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    IMAGE_URL_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    PUBLISHED_AT_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    card_id: str
    title: str
    summary: str
    source_url: str
    source_type: str
    image_url: str
    status: str
    published_at: str
    sequence: int
    def __init__(self, card_id: _Optional[str] = ..., title: _Optional[str] = ..., summary: _Optional[str] = ..., source_url: _Optional[str] = ..., source_type: _Optional[str] = ..., image_url: _Optional[str] = ..., status: _Optional[str] = ..., published_at: _Optional[str] = ..., sequence: _Optional[int] = ...) -> None: ...

class CollectionStatusRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CollectionStatusResponse(_message.Message):
    __slots__ = ("success", "total_collections", "total_cards", "pending_cards", "published_cards", "featured_collection", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_COLLECTIONS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_CARDS_FIELD_NUMBER: _ClassVar[int]
    PENDING_CARDS_FIELD_NUMBER: _ClassVar[int]
    PUBLISHED_CARDS_FIELD_NUMBER: _ClassVar[int]
    FEATURED_COLLECTION_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    total_collections: int
    total_cards: int
    pending_cards: int
    published_cards: int
    featured_collection: CollectionInfo
    error: str
    def __init__(self, success: bool = ..., total_collections: _Optional[int] = ..., total_cards: _Optional[int] = ..., pending_cards: _Optional[int] = ..., published_cards: _Optional[int] = ..., featured_collection: _Optional[_Union[CollectionInfo, _Mapping]] = ..., error: _Optional[str] = ...) -> None: ...

class CollectionListRequest(_message.Message):
    __slots__ = ("status", "limit")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    status: str
    limit: int
    def __init__(self, status: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class CollectionListResponse(_message.Message):
    __slots__ = ("success", "collections", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    COLLECTIONS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    collections: _containers.RepeatedCompositeFieldContainer[CollectionInfo]
    error: str
    def __init__(self, success: bool = ..., collections: _Optional[_Iterable[_Union[CollectionInfo, _Mapping]]] = ..., error: _Optional[str] = ...) -> None: ...

class CollectionCreateRequest(_message.Message):
    __slots__ = ("slug", "name", "description", "featured")
    SLUG_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    FEATURED_FIELD_NUMBER: _ClassVar[int]
    slug: str
    name: str
    description: str
    featured: bool
    def __init__(self, slug: _Optional[str] = ..., name: _Optional[str] = ..., description: _Optional[str] = ..., featured: bool = ...) -> None: ...

class CollectionCreateResponse(_message.Message):
    __slots__ = ("success", "collection", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    COLLECTION_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    collection: CollectionInfo
    error: str
    def __init__(self, success: bool = ..., collection: _Optional[_Union[CollectionInfo, _Mapping]] = ..., error: _Optional[str] = ...) -> None: ...

class CollectionSetFeaturedRequest(_message.Message):
    __slots__ = ("slug",)
    SLUG_FIELD_NUMBER: _ClassVar[int]
    slug: str
    def __init__(self, slug: _Optional[str] = ...) -> None: ...

class CollectionSetFeaturedResponse(_message.Message):
    __slots__ = ("success", "collection", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    COLLECTION_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    collection: CollectionInfo
    error: str
    def __init__(self, success: bool = ..., collection: _Optional[_Union[CollectionInfo, _Mapping]] = ..., error: _Optional[str] = ...) -> None: ...

class CollectionAddCardRequest(_message.Message):
    __slots__ = ("slug", "title", "summary", "source_url", "source_type", "image_url")
    SLUG_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    SOURCE_URL_FIELD_NUMBER: _ClassVar[int]
    SOURCE_TYPE_FIELD_NUMBER: _ClassVar[int]
    IMAGE_URL_FIELD_NUMBER: _ClassVar[int]
    slug: str
    title: str
    summary: str
    source_url: str
    source_type: str
    image_url: str
    def __init__(self, slug: _Optional[str] = ..., title: _Optional[str] = ..., summary: _Optional[str] = ..., source_url: _Optional[str] = ..., source_type: _Optional[str] = ..., image_url: _Optional[str] = ...) -> None: ...

class CollectionAddCardResponse(_message.Message):
    __slots__ = ("success", "card", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    CARD_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    card: CardInfo
    error: str
    def __init__(self, success: bool = ..., card: _Optional[_Union[CardInfo, _Mapping]] = ..., error: _Optional[str] = ...) -> None: ...

class CollectionListCardsRequest(_message.Message):
    __slots__ = ("slug", "status", "limit")
    SLUG_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    slug: str
    status: str
    limit: int
    def __init__(self, slug: _Optional[str] = ..., status: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class CollectionListCardsResponse(_message.Message):
    __slots__ = ("success", "cards", "total", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    CARDS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    cards: _containers.RepeatedCompositeFieldContainer[CardInfo]
    total: int
    error: str
    def __init__(self, success: bool = ..., cards: _Optional[_Iterable[_Union[CardInfo, _Mapping]]] = ..., total: _Optional[int] = ..., error: _Optional[str] = ...) -> None: ...

class CollectionPublishCardsRequest(_message.Message):
    __slots__ = ("count", "collection_slug")
    COUNT_FIELD_NUMBER: _ClassVar[int]
    COLLECTION_SLUG_FIELD_NUMBER: _ClassVar[int]
    count: int
    collection_slug: str
    def __init__(self, count: _Optional[int] = ..., collection_slug: _Optional[str] = ...) -> None: ...

class CollectionPublishCardsResponse(_message.Message):
    __slots__ = ("success", "published_cards", "published_count", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    PUBLISHED_CARDS_FIELD_NUMBER: _ClassVar[int]
    PUBLISHED_COUNT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    published_cards: _containers.RepeatedCompositeFieldContainer[CardInfo]
    published_count: int
    error: str
    def __init__(self, success: bool = ..., published_cards: _Optional[_Iterable[_Union[CardInfo, _Mapping]]] = ..., published_count: _Optional[int] = ..., error: _Optional[str] = ...) -> None: ...

class CollectionPublishVizRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CollectionPublishVizResponse(_message.Message):
    __slots__ = ("success", "points_count", "clusters_count", "published_at", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    POINTS_COUNT_FIELD_NUMBER: _ClassVar[int]
    CLUSTERS_COUNT_FIELD_NUMBER: _ClassVar[int]
    PUBLISHED_AT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    points_count: int
    clusters_count: int
    published_at: str
    error: str
    def __init__(self, success: bool = ..., points_count: _Optional[int] = ..., clusters_count: _Optional[int] = ..., published_at: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class CollectionSyncThemeRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CollectionSyncThemeResponse(_message.Message):
    __slots__ = ("success", "theme_id", "title", "namespace_id", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    THEME_ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    theme_id: str
    title: str
    namespace_id: str
    error: str
    def __init__(self, success: bool = ..., theme_id: _Optional[str] = ..., title: _Optional[str] = ..., namespace_id: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class ArticleInfo(_message.Message):
    __slots__ = ("slug", "title", "status", "zk_count", "sources_count")
    SLUG_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    ZK_COUNT_FIELD_NUMBER: _ClassVar[int]
    SOURCES_COUNT_FIELD_NUMBER: _ClassVar[int]
    slug: str
    title: str
    status: str
    zk_count: int
    sources_count: int
    def __init__(self, slug: _Optional[str] = ..., title: _Optional[str] = ..., status: _Optional[str] = ..., zk_count: _Optional[int] = ..., sources_count: _Optional[int] = ...) -> None: ...

class CurationRunInfo(_message.Message):
    __slots__ = ("run_id", "slug", "completed_at", "cards_created")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    SLUG_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_AT_FIELD_NUMBER: _ClassVar[int]
    CARDS_CREATED_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    slug: str
    completed_at: str
    cards_created: int
    def __init__(self, run_id: _Optional[str] = ..., slug: _Optional[str] = ..., completed_at: _Optional[str] = ..., cards_created: _Optional[int] = ...) -> None: ...

class ArticleStatusRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ArticleStatusResponse(_message.Message):
    __slots__ = ("success", "running", "current_run_id", "current_step", "articles_pending", "articles", "recent_curations", "total_cards_pending", "total_cards_published", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    RUNNING_FIELD_NUMBER: _ClassVar[int]
    CURRENT_RUN_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_STEP_FIELD_NUMBER: _ClassVar[int]
    ARTICLES_PENDING_FIELD_NUMBER: _ClassVar[int]
    ARTICLES_FIELD_NUMBER: _ClassVar[int]
    RECENT_CURATIONS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_CARDS_PENDING_FIELD_NUMBER: _ClassVar[int]
    TOTAL_CARDS_PUBLISHED_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    running: bool
    current_run_id: str
    current_step: str
    articles_pending: int
    articles: _containers.RepeatedCompositeFieldContainer[ArticleInfo]
    recent_curations: _containers.RepeatedCompositeFieldContainer[CurationRunInfo]
    total_cards_pending: int
    total_cards_published: int
    error: str
    def __init__(self, success: bool = ..., running: bool = ..., current_run_id: _Optional[str] = ..., current_step: _Optional[str] = ..., articles_pending: _Optional[int] = ..., articles: _Optional[_Iterable[_Union[ArticleInfo, _Mapping]]] = ..., recent_curations: _Optional[_Iterable[_Union[CurationRunInfo, _Mapping]]] = ..., total_cards_pending: _Optional[int] = ..., total_cards_published: _Optional[int] = ..., error: _Optional[str] = ...) -> None: ...

class ArticleNewRequest(_message.Message):
    __slots__ = ("slug", "title")
    SLUG_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    slug: str
    title: str
    def __init__(self, slug: _Optional[str] = ..., title: _Optional[str] = ...) -> None: ...

class ArticleNewResponse(_message.Message):
    __slots__ = ("success", "slug", "title", "kb_path", "article_id", "collection_id", "message", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    SLUG_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    KB_PATH_FIELD_NUMBER: _ClassVar[int]
    ARTICLE_ID_FIELD_NUMBER: _ClassVar[int]
    COLLECTION_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    slug: str
    title: str
    kb_path: str
    article_id: str
    collection_id: str
    message: str
    error: str
    def __init__(self, success: bool = ..., slug: _Optional[str] = ..., title: _Optional[str] = ..., kb_path: _Optional[str] = ..., article_id: _Optional[str] = ..., collection_id: _Optional[str] = ..., message: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class ArticleCurationEvent(_message.Message):
    __slots__ = ("run_id", "step", "step_number", "total_steps", "progress", "message")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    STEP_FIELD_NUMBER: _ClassVar[int]
    STEP_NUMBER_FIELD_NUMBER: _ClassVar[int]
    TOTAL_STEPS_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    step: str
    step_number: int
    total_steps: int
    progress: float
    message: str
    def __init__(self, run_id: _Optional[str] = ..., step: _Optional[str] = ..., step_number: _Optional[int] = ..., total_steps: _Optional[int] = ..., progress: _Optional[float] = ..., message: _Optional[str] = ...) -> None: ...

class ArticleCurateRequest(_message.Message):
    __slots__ = ("slug", "skip_grok", "max_sources")
    SLUG_FIELD_NUMBER: _ClassVar[int]
    SKIP_GROK_FIELD_NUMBER: _ClassVar[int]
    MAX_SOURCES_FIELD_NUMBER: _ClassVar[int]
    slug: str
    skip_grok: bool
    max_sources: int
    def __init__(self, slug: _Optional[str] = ..., skip_grok: bool = ..., max_sources: _Optional[int] = ...) -> None: ...

class RenderCardsRequest(_message.Message):
    __slots__ = ("collection_slug", "card_id", "sample", "variants", "force", "upload")
    COLLECTION_SLUG_FIELD_NUMBER: _ClassVar[int]
    CARD_ID_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_FIELD_NUMBER: _ClassVar[int]
    VARIANTS_FIELD_NUMBER: _ClassVar[int]
    FORCE_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_FIELD_NUMBER: _ClassVar[int]
    collection_slug: str
    card_id: str
    sample: int
    variants: _containers.RepeatedScalarFieldContainer[str]
    force: bool
    upload: bool
    def __init__(self, collection_slug: _Optional[str] = ..., card_id: _Optional[str] = ..., sample: _Optional[int] = ..., variants: _Optional[_Iterable[str]] = ..., force: bool = ..., upload: bool = ...) -> None: ...

class RenderCardEvent(_message.Message):
    __slots__ = ("phase", "card_id", "message", "progress", "variant", "output_path", "image_url", "cards_done", "cards_total", "duration_ms", "error")
    PHASE_FIELD_NUMBER: _ClassVar[int]
    CARD_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    VARIANT_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_PATH_FIELD_NUMBER: _ClassVar[int]
    IMAGE_URL_FIELD_NUMBER: _ClassVar[int]
    CARDS_DONE_FIELD_NUMBER: _ClassVar[int]
    CARDS_TOTAL_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    phase: RenderPhase
    card_id: str
    message: str
    progress: float
    variant: str
    output_path: str
    image_url: str
    cards_done: int
    cards_total: int
    duration_ms: int
    error: str
    def __init__(self, phase: _Optional[_Union[RenderPhase, str]] = ..., card_id: _Optional[str] = ..., message: _Optional[str] = ..., progress: _Optional[float] = ..., variant: _Optional[str] = ..., output_path: _Optional[str] = ..., image_url: _Optional[str] = ..., cards_done: _Optional[int] = ..., cards_total: _Optional[int] = ..., duration_ms: _Optional[int] = ..., error: _Optional[str] = ...) -> None: ...

class SignalsTelemetryRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class GpuWatt(_message.Message):
    __slots__ = ("index", "uuid", "model", "power_w", "util", "memory_used_mib", "memory_free_mib", "energy_mj", "temp_c")
    INDEX_FIELD_NUMBER: _ClassVar[int]
    UUID_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    POWER_W_FIELD_NUMBER: _ClassVar[int]
    UTIL_FIELD_NUMBER: _ClassVar[int]
    MEMORY_USED_MIB_FIELD_NUMBER: _ClassVar[int]
    MEMORY_FREE_MIB_FIELD_NUMBER: _ClassVar[int]
    ENERGY_MJ_FIELD_NUMBER: _ClassVar[int]
    TEMP_C_FIELD_NUMBER: _ClassVar[int]
    index: int
    uuid: str
    model: str
    power_w: float
    util: float
    memory_used_mib: float
    memory_free_mib: float
    energy_mj: float
    temp_c: float
    def __init__(self, index: _Optional[int] = ..., uuid: _Optional[str] = ..., model: _Optional[str] = ..., power_w: _Optional[float] = ..., util: _Optional[float] = ..., memory_used_mib: _Optional[float] = ..., memory_free_mib: _Optional[float] = ..., energy_mj: _Optional[float] = ..., temp_c: _Optional[float] = ...) -> None: ...

class SignalsTelemetryResponse(_message.Message):
    __slots__ = ("source_url", "scraped_at", "gpus", "total_w", "parked_w", "inferring_w", "error")
    SOURCE_URL_FIELD_NUMBER: _ClassVar[int]
    SCRAPED_AT_FIELD_NUMBER: _ClassVar[int]
    GPUS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_W_FIELD_NUMBER: _ClassVar[int]
    PARKED_W_FIELD_NUMBER: _ClassVar[int]
    INFERRING_W_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    source_url: str
    scraped_at: str
    gpus: _containers.RepeatedCompositeFieldContainer[GpuWatt]
    total_w: float
    parked_w: float
    inferring_w: float
    error: str
    def __init__(self, source_url: _Optional[str] = ..., scraped_at: _Optional[str] = ..., gpus: _Optional[_Iterable[_Union[GpuWatt, _Mapping]]] = ..., total_w: _Optional[float] = ..., parked_w: _Optional[float] = ..., inferring_w: _Optional[float] = ..., error: _Optional[str] = ...) -> None: ...

class DiscoverSurfaceRequest(_message.Message):
    __slots__ = ("window", "query", "breakdown", "limit", "cursor", "feature_pins", "from_ts", "to_ts")
    WINDOW_FIELD_NUMBER: _ClassVar[int]
    QUERY_FIELD_NUMBER: _ClassVar[int]
    BREAKDOWN_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    FEATURE_PINS_FIELD_NUMBER: _ClassVar[int]
    FROM_TS_FIELD_NUMBER: _ClassVar[int]
    TO_TS_FIELD_NUMBER: _ClassVar[int]
    window: str
    query: str
    breakdown: str
    limit: int
    cursor: str
    feature_pins: _containers.RepeatedScalarFieldContainer[str]
    from_ts: str
    to_ts: str
    def __init__(self, window: _Optional[str] = ..., query: _Optional[str] = ..., breakdown: _Optional[str] = ..., limit: _Optional[int] = ..., cursor: _Optional[str] = ..., feature_pins: _Optional[_Iterable[str]] = ..., from_ts: _Optional[str] = ..., to_ts: _Optional[str] = ...) -> None: ...

class DiscoverBucket(_message.Message):
    __slots__ = ("t", "n", "breakdown_key", "salience", "watts", "util", "salience_ma", "watts_ma", "util_ma")
    T_FIELD_NUMBER: _ClassVar[int]
    N_FIELD_NUMBER: _ClassVar[int]
    BREAKDOWN_KEY_FIELD_NUMBER: _ClassVar[int]
    SALIENCE_FIELD_NUMBER: _ClassVar[int]
    WATTS_FIELD_NUMBER: _ClassVar[int]
    UTIL_FIELD_NUMBER: _ClassVar[int]
    SALIENCE_MA_FIELD_NUMBER: _ClassVar[int]
    WATTS_MA_FIELD_NUMBER: _ClassVar[int]
    UTIL_MA_FIELD_NUMBER: _ClassVar[int]
    t: str
    n: int
    breakdown_key: str
    salience: float
    watts: float
    util: float
    salience_ma: float
    watts_ma: float
    util_ma: float
    def __init__(self, t: _Optional[str] = ..., n: _Optional[int] = ..., breakdown_key: _Optional[str] = ..., salience: _Optional[float] = ..., watts: _Optional[float] = ..., util: _Optional[float] = ..., salience_ma: _Optional[float] = ..., watts_ma: _Optional[float] = ..., util_ma: _Optional[float] = ...) -> None: ...

class DiscoverEpisode(_message.Message):
    __slots__ = ("kind", "at", "eta_s", "label")
    KIND_FIELD_NUMBER: _ClassVar[int]
    AT_FIELD_NUMBER: _ClassVar[int]
    ETA_S_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    kind: str
    at: str
    eta_s: int
    label: str
    def __init__(self, kind: _Optional[str] = ..., at: _Optional[str] = ..., eta_s: _Optional[int] = ..., label: _Optional[str] = ...) -> None: ...

class DiscoverDoc(_message.Message):
    __slots__ = ("id", "stream", "source", "ts", "title", "body", "source_id", "url")
    ID_FIELD_NUMBER: _ClassVar[int]
    STREAM_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    TS_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    BODY_FIELD_NUMBER: _ClassVar[int]
    SOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    id: str
    stream: str
    source: str
    ts: str
    title: str
    body: str
    source_id: str
    url: str
    def __init__(self, id: _Optional[str] = ..., stream: _Optional[str] = ..., source: _Optional[str] = ..., ts: _Optional[str] = ..., title: _Optional[str] = ..., body: _Optional[str] = ..., source_id: _Optional[str] = ..., url: _Optional[str] = ...) -> None: ...

class DiscoverFacet(_message.Message):
    __slots__ = ("key", "kind", "count", "salience", "label")
    KEY_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    COUNT_FIELD_NUMBER: _ClassVar[int]
    SALIENCE_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    key: str
    kind: str
    count: int
    salience: float
    label: str
    def __init__(self, key: _Optional[str] = ..., kind: _Optional[str] = ..., count: _Optional[int] = ..., salience: _Optional[float] = ..., label: _Optional[str] = ...) -> None: ...

class DiscoverSurfaceResponse(_message.Message):
    __slots__ = ("buckets", "docs", "facets", "total", "window", "query", "scraped_at", "interval", "error", "last_salience_at", "next_episode", "clock", "status")
    BUCKETS_FIELD_NUMBER: _ClassVar[int]
    DOCS_FIELD_NUMBER: _ClassVar[int]
    FACETS_FIELD_NUMBER: _ClassVar[int]
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    WINDOW_FIELD_NUMBER: _ClassVar[int]
    QUERY_FIELD_NUMBER: _ClassVar[int]
    SCRAPED_AT_FIELD_NUMBER: _ClassVar[int]
    INTERVAL_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    LAST_SALIENCE_AT_FIELD_NUMBER: _ClassVar[int]
    NEXT_EPISODE_FIELD_NUMBER: _ClassVar[int]
    CLOCK_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    buckets: _containers.RepeatedCompositeFieldContainer[DiscoverBucket]
    docs: _containers.RepeatedCompositeFieldContainer[DiscoverDoc]
    facets: _containers.RepeatedCompositeFieldContainer[DiscoverFacet]
    total: int
    window: str
    query: str
    scraped_at: str
    interval: str
    error: str
    last_salience_at: str
    next_episode: DiscoverEpisode
    clock: str
    status: DiscoverStatus
    def __init__(self, buckets: _Optional[_Iterable[_Union[DiscoverBucket, _Mapping]]] = ..., docs: _Optional[_Iterable[_Union[DiscoverDoc, _Mapping]]] = ..., facets: _Optional[_Iterable[_Union[DiscoverFacet, _Mapping]]] = ..., total: _Optional[int] = ..., window: _Optional[str] = ..., query: _Optional[str] = ..., scraped_at: _Optional[str] = ..., interval: _Optional[str] = ..., error: _Optional[str] = ..., last_salience_at: _Optional[str] = ..., next_episode: _Optional[_Union[DiscoverEpisode, _Mapping]] = ..., clock: _Optional[str] = ..., status: _Optional[_Union[DiscoverStatus, _Mapping]] = ...) -> None: ...

class DiscoverStatus(_message.Message):
    __slots__ = ("updating", "workflows", "waiting_at", "watts", "articles", "projects", "thoughts", "watts_live", "terms_skos", "terms_cites", "agenda_min", "agenda_max", "agenda_std", "salience_peak", "cognition_tokens")
    UPDATING_FIELD_NUMBER: _ClassVar[int]
    WORKFLOWS_FIELD_NUMBER: _ClassVar[int]
    WAITING_AT_FIELD_NUMBER: _ClassVar[int]
    WATTS_FIELD_NUMBER: _ClassVar[int]
    ARTICLES_FIELD_NUMBER: _ClassVar[int]
    PROJECTS_FIELD_NUMBER: _ClassVar[int]
    THOUGHTS_FIELD_NUMBER: _ClassVar[int]
    WATTS_LIVE_FIELD_NUMBER: _ClassVar[int]
    TERMS_SKOS_FIELD_NUMBER: _ClassVar[int]
    TERMS_CITES_FIELD_NUMBER: _ClassVar[int]
    AGENDA_MIN_FIELD_NUMBER: _ClassVar[int]
    AGENDA_MAX_FIELD_NUMBER: _ClassVar[int]
    AGENDA_STD_FIELD_NUMBER: _ClassVar[int]
    SALIENCE_PEAK_FIELD_NUMBER: _ClassVar[int]
    COGNITION_TOKENS_FIELD_NUMBER: _ClassVar[int]
    updating: bool
    workflows: int
    waiting_at: str
    watts: float
    articles: int
    projects: int
    thoughts: int
    watts_live: bool
    terms_skos: int
    terms_cites: int
    agenda_min: float
    agenda_max: float
    agenda_std: float
    salience_peak: float
    cognition_tokens: int
    def __init__(self, updating: bool = ..., workflows: _Optional[int] = ..., waiting_at: _Optional[str] = ..., watts: _Optional[float] = ..., articles: _Optional[int] = ..., projects: _Optional[int] = ..., thoughts: _Optional[int] = ..., watts_live: bool = ..., terms_skos: _Optional[int] = ..., terms_cites: _Optional[int] = ..., agenda_min: _Optional[float] = ..., agenda_max: _Optional[float] = ..., agenda_std: _Optional[float] = ..., salience_peak: _Optional[float] = ..., cognition_tokens: _Optional[int] = ...) -> None: ...

class RefreshDiscoverLandingRequest(_message.Message):
    __slots__ = ("reason",)
    REASON_FIELD_NUMBER: _ClassVar[int]
    reason: str
    def __init__(self, reason: _Optional[str] = ...) -> None: ...

class RefreshDiscoverLandingResponse(_message.Message):
    __slots__ = ("accepted", "started", "refreshed_at", "error")
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    STARTED_FIELD_NUMBER: _ClassVar[int]
    REFRESHED_AT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    accepted: bool
    started: bool
    refreshed_at: str
    error: str
    def __init__(self, accepted: bool = ..., started: bool = ..., refreshed_at: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...
