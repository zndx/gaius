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

class WorkloadType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    WORKLOAD_INIT: _ClassVar[WorkloadType]
    WORKLOAD_SWARM: _ClassVar[WorkloadType]
    WORKLOAD_INFERENCE: _ClassVar[WorkloadType]
    WORKLOAD_EMBEDDING: _ClassVar[WorkloadType]
    WORKLOAD_EVOLUTION: _ClassVar[WorkloadType]

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
PROCESS_STATUS_UNSPECIFIED: ProcessStatus
PROCESS_STATUS_STOPPED: ProcessStatus
PROCESS_STATUS_STARTING: ProcessStatus
PROCESS_STATUS_HEALTHY: ProcessStatus
PROCESS_STATUS_UNHEALTHY: ProcessStatus
PROCESS_STATUS_STOPPING: ProcessStatus
PROCESS_STATUS_FAILED: ProcessStatus
PROCESS_STATUS_PENDING: ProcessStatus
WORKLOAD_INIT: WorkloadType
WORKLOAD_SWARM: WorkloadType
WORKLOAD_INFERENCE: WorkloadType
WORKLOAD_EMBEDDING: WorkloadType
WORKLOAD_EVOLUTION: WorkloadType
AMBIENT_PHASE_UNSPECIFIED: AmbientPhase
AMBIENT_PHASE_BASELINE_HEALTH: AmbientPhase
AMBIENT_PHASE_BASELINE_WORKLOAD: AmbientPhase
AMBIENT_PHASE_REASONING_EVICTION: AmbientPhase
AMBIENT_PHASE_REASONING_WORKLOAD: AmbientPhase
AMBIENT_PHASE_BASELINE_RESTORATION: AmbientPhase
AMBIENT_PHASE_COMPLETE: AmbientPhase
AMBIENT_PHASE_ERROR: AmbientPhase

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
    __slots__ = ("agent_alias", "prompt", "system_prompt", "max_tokens", "temperature", "priority")
    AGENT_ALIAS_FIELD_NUMBER: _ClassVar[int]
    PROMPT_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_PROMPT_FIELD_NUMBER: _ClassVar[int]
    MAX_TOKENS_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_FIELD_NUMBER: _ClassVar[int]
    PRIORITY_FIELD_NUMBER: _ClassVar[int]
    agent_alias: str
    prompt: str
    system_prompt: str
    max_tokens: int
    temperature: float
    priority: str
    def __init__(self, agent_alias: _Optional[str] = ..., prompt: _Optional[str] = ..., system_prompt: _Optional[str] = ..., max_tokens: _Optional[int] = ..., temperature: _Optional[float] = ..., priority: _Optional[str] = ...) -> None: ...

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
    __slots__ = ("healthy", "summary", "passed", "warnings", "failures", "new_incidents")
    HEALTHY_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    PASSED_FIELD_NUMBER: _ClassVar[int]
    WARNINGS_FIELD_NUMBER: _ClassVar[int]
    FAILURES_FIELD_NUMBER: _ClassVar[int]
    NEW_INCIDENTS_FIELD_NUMBER: _ClassVar[int]
    healthy: bool
    summary: str
    passed: int
    warnings: int
    failures: int
    new_incidents: int
    def __init__(self, healthy: bool = ..., summary: _Optional[str] = ..., passed: _Optional[int] = ..., warnings: _Optional[int] = ..., failures: _Optional[int] = ..., new_incidents: _Optional[int] = ...) -> None: ...

class GetIncidentDetailRequest(_message.Message):
    __slots__ = ("fingerprint",)
    FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    fingerprint: str
    def __init__(self, fingerprint: _Optional[str] = ...) -> None: ...

class GetIncidentDetailResponse(_message.Message):
    __slots__ = ("incident", "found")
    INCIDENT_FIELD_NUMBER: _ClassVar[int]
    FOUND_FIELD_NUMBER: _ClassVar[int]
    incident: HealthIncident
    found: bool
    def __init__(self, incident: _Optional[_Union[HealthIncident, _Mapping]] = ..., found: bool = ...) -> None: ...

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
