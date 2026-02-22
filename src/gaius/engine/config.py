"""Engine configuration loader using HOCON.

Loads agent-model pairings, resource requirements, and backend settings
from config/agents.conf.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from pyhocon import ConfigTree

logger = logging.getLogger(__name__)


@dataclass
class ResourceRequirements:
    """GPU and memory requirements for an agent."""

    gpus: int = 1
    vram_gb: float = 16.0
    context_length: int = 8192
    rope_scaling: str = "none"  # none | linear | dynamic


@dataclass
class EndpointConfig:
    """vLLM endpoint configuration."""

    port: int = 8080
    tensor_parallel: int = 1
    max_num_seqs: int = 256  # Max concurrent sequences for vLLM
    task: str = "generate"  # vLLM task: generate | embed | classify | reward
    # Per-endpoint overrides (None = use global vLLM defaults)
    dtype: Optional[str] = None
    enforce_eager: bool = False
    gpu_memory_utilization: Optional[float] = None
    swap_space: Optional[float] = None
    embedding_dim: Optional[int] = None


@dataclass
class AgentConfig:
    """Configuration for a single agent."""

    name: str
    alias: str
    description: str
    model: str
    backend: str  # "vllm" | "optillm"
    optillm_technique: Optional[str] = None
    resources: ResourceRequirements = field(default_factory=ResourceRequirements)
    endpoint: Optional[EndpointConfig] = None


@dataclass
class GrpcConfig:
    """gRPC server configuration."""

    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 50051
    max_workers: int = 10
    max_message_size: int = 100 * 1024 * 1024  # 100MB


@dataclass
class AeronConfig:
    """Aeron IPC configuration."""

    directory: str = "/dev/shm/gaius-aeron"
    request_stream: int = 100
    response_stream: int = 101
    event_stream: int = 102
    health_stream: int = 103


@dataclass
class TelemetryConfig:
    """OpenTelemetry configuration.

    Telemetry is enabled by default. To disable, set OTEL_SDK_DISABLED=true
    in environment (standard OTel convention).
    """

    exporter: str = "otlp"  # otlp or console
    endpoint: str = "http://localhost:4317"
    service_name: str = "gaius-engine"  # Base name, entry point suffix added at init
    sampling_rate: float = 0.01


@dataclass
class GunicornConfig:
    """Gunicorn WSGI server configuration for optillm."""

    workers: int = 4
    worker_class: str = "gthread"
    threads: int = 2
    timeout: int = 120
    graceful_timeout: int = 30
    max_requests: int = 1000
    max_requests_jitter: int = 50
    config_dir: str = "/tmp/gaius"


@dataclass
class OptillmConfig:
    """optillm backend configuration."""

    enabled: bool = True
    api_key: Optional[str] = None
    base_url: str = "http://localhost:8000"
    backend_url: str = "http://localhost:8082/v1"  # vLLM instruct endpoint
    default_technique: str = "cot_reflection"
    timeout: int = 120
    use_gunicorn: bool = True
    gunicorn: GunicornConfig = field(default_factory=GunicornConfig)


@dataclass
class VllmConfig:
    """vLLM backend configuration."""

    binary: str = "vllm"
    gpu_memory_utilization: float = 0.9
    max_model_len: int = 32768
    dtype: str = "auto"
    extra_args: list[str] = field(default_factory=list)


@dataclass
class GPUInventory:
    """GPU resource inventory."""

    total: int = 6
    reserved: list[int] = field(default_factory=list)


@dataclass
class SchedulingConfig:
    """Resource scheduling configuration."""

    prefer_contiguous: bool = True
    allocation_timeout: int = 30
    allow_preemption: bool = False


@dataclass
class EvolutionConfig:
    """Evolution daemon configuration."""

    enabled: bool = True
    rotation: list[str] = field(
        default_factory=lambda: [
            "leader",
            "risk",
            "critic",
            "optimizer",
            "domain",
            "synthesis",
            "validator",
        ]
    )
    strategy: str = "apo"
    candidates_per_iteration: int = 5
    max_iterations: int = 3
    min_idle_gpus: int = 2
    idle_timeout_seconds: int = 300
    parallel_enabled: bool = False
    parallel_max_concurrent: int = 6


@dataclass
class FlowSchedulerConfig:
    """Flow scheduler daemon configuration for autonomous Metaflow runs."""

    enabled: bool = True
    poll_interval_seconds: float = 60.0  # How often to check for new items
    max_concurrent_flows: int = 2  # Max parallel flow runs
    batch_size: int = 5  # Max items per poll
    gpu_index: str = "4,5"  # GPUs to use for flows (avoid vLLM GPUs 0-3)

    # Flow-specific settings
    enable_topics: bool = True
    topic_model_type: str = "bertopic"
    enable_scoring: bool = False  # Disable by default to avoid LLM costs


@dataclass
class AmbientBufferConfig:
    """Ambient buffer configuration for content fetching and summarization.

    The ambient workload ALWAYS fetches external content and summarizes it.
    This is core to ambient computing - exercising real operations to discover
    failures and accumulate operational metrics.

    Uses Firebase API for HN new comments (RSS doesn't support comments).
    """

    # HN Firebase API endpoint
    source_url: str = "https://hacker-news.firebaseio.com/v0/updates.json"
    newcomments: bool = True  # Fetch new comments via Firebase API
    max_items: int = 10  # Items per fetch cycle

    # Buffer sizing (byte-based FIFO)
    buffer_max_bytes: int = 256 * 1024  # 256KB default

    # Summarization
    summarize_max_tokens: int = 256


@dataclass
class StartupConfig:
    """Autonomous startup configuration."""

    clean_start: bool = True  # Kill stale processes on boot
    preload_endpoints: list[str] = field(default_factory=lambda: ["instruct"])
    auto_start_evolution: bool = True  # Start evolution daemon if enabled
    auto_start_cognition: bool = True  # Start cognition daemon for scheduled tasks
    auto_start_flow_scheduler: bool = True  # Start flow scheduler for Metaflow pipelines
    auto_restart_failed: bool = True  # Auto-restart failed endpoints
    max_restart_attempts: int = 3

    # Ambient workload auto-restart after engine restart
    auto_resume_ambient: bool = True  # Resume ambient daemon if it was running before restart


@dataclass
class EngineConfig:
    """Complete engine configuration."""

    grpc: GrpcConfig = field(default_factory=GrpcConfig)
    aeron: AeronConfig = field(default_factory=AeronConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    health_interval_ms: int = 1000
    agents: dict[str, AgentConfig] = field(default_factory=dict)
    optillm: OptillmConfig = field(default_factory=OptillmConfig)
    vllm: VllmConfig = field(default_factory=VllmConfig)
    gpus: GPUInventory = field(default_factory=GPUInventory)
    scheduling: SchedulingConfig = field(default_factory=SchedulingConfig)
    evolution: EvolutionConfig = field(default_factory=EvolutionConfig)
    flow_scheduler: FlowSchedulerConfig = field(default_factory=FlowSchedulerConfig)
    ambient_buffer: AmbientBufferConfig = field(default_factory=AmbientBufferConfig)
    startup: StartupConfig = field(default_factory=StartupConfig)


def load_config(config_path: Optional[str] = None) -> EngineConfig:
    """Load engine configuration from HOCON file.

    Args:
        config_path: Path to config file. Defaults to config/agents.conf
                     or GAIUS_CONFIG environment variable.

    Returns:
        Parsed EngineConfig
    """
    try:
        from pyhocon import ConfigFactory, ConfigTree
    except ImportError:
        logger.warning("pyhocon not installed, using defaults")
        return EngineConfig()

    # Determine config path
    resolved_path: Path
    if config_path is None:
        env_path = os.environ.get("GAIUS_CONFIG")
        if env_path is not None:
            resolved_path = Path(env_path)
        else:
            # Look for config relative to project root
            # __file__ is src/gaius/engine/config.py, so parents[3] is project root
            project_root = Path(__file__).parents[3]
            resolved_path = project_root / "config" / "agents.conf"
    else:
        resolved_path = Path(config_path)

    if not resolved_path.exists():
        logger.warning(f"Config file not found: {resolved_path}, using defaults")
        return EngineConfig()

    logger.info(f"Loading config from {resolved_path}")

    # Parse HOCON
    conf = ConfigFactory.parse_file(str(resolved_path))

    return _parse_config(conf)


def _parse_config(conf: "ConfigTree") -> EngineConfig:
    """Parse ConfigTree into EngineConfig dataclass."""

    # Helper to safely get nested values
    def get(path: str, default=None):
        try:
            return conf.get(path, default)
        except Exception:
            return default

    # Parse gRPC config
    grpc = GrpcConfig(
        enabled=get("gaius.engine.grpc.enabled", True),
        host=get("gaius.engine.grpc.host", "0.0.0.0"),
        port=get("gaius.engine.grpc.port", 50051),
        max_workers=get("gaius.engine.grpc.max_workers", 10),
        max_message_size=get("gaius.engine.grpc.max_message_size", 100 * 1024 * 1024),
    )

    # Parse Aeron config
    aeron = AeronConfig(
        directory=get("gaius.engine.aeron.directory", "/dev/shm/gaius-aeron"),
        request_stream=get("gaius.engine.aeron.request_stream", 100),
        response_stream=get("gaius.engine.aeron.response_stream", 101),
        event_stream=get("gaius.engine.aeron.event_stream", 102),
        health_stream=get("gaius.engine.aeron.health_stream", 103),
    )

    # Parse telemetry config (enabled by default, disable via OTEL_SDK_DISABLED=true)
    telemetry = TelemetryConfig(
        exporter=get("gaius.engine.telemetry.exporter", "otlp"),
        endpoint=get("gaius.engine.telemetry.endpoint", "http://localhost:4317"),
        service_name=get("gaius.engine.telemetry.service_name", "gaius-engine"),
        sampling_rate=get("gaius.engine.telemetry.sampling_rate", 0.01),
    )

    # Parse agents
    agents: dict[str, AgentConfig] = {}
    agents_conf = get("gaius.agents", {})

    def safe_get(conf, key, default=None):
        """Safely get a value from ConfigTree, returning default on missing."""
        try:
            return conf.get(key, default)
        except Exception:
            return default

    if hasattr(agents_conf, "items"):
        for name, agent_conf in agents_conf.items():
            if not hasattr(agent_conf, "get"):
                continue

            # Parse resources
            resources_conf = safe_get(agent_conf, "resources", {})
            if hasattr(resources_conf, "get"):
                resources = ResourceRequirements(
                    gpus=safe_get(resources_conf, "gpus", 1),
                    vram_gb=safe_get(resources_conf, "vram-gb", 16.0),
                    context_length=safe_get(resources_conf, "context-length", 8192),
                    rope_scaling=safe_get(resources_conf, "rope-scaling", "none"),
                )
            else:
                resources = ResourceRequirements()

            # Parse endpoint (optional)
            endpoint = None
            endpoint_conf = safe_get(agent_conf, "endpoint")
            if endpoint_conf and hasattr(endpoint_conf, "get"):
                endpoint = EndpointConfig(
                    port=safe_get(endpoint_conf, "port", 8080),
                    tensor_parallel=safe_get(endpoint_conf, "tensor-parallel", 1),
                    max_num_seqs=safe_get(endpoint_conf, "max-num-seqs", 256),
                    task=safe_get(endpoint_conf, "task", "generate"),
                    dtype=safe_get(endpoint_conf, "dtype"),
                    enforce_eager=safe_get(endpoint_conf, "enforce-eager", False),
                    gpu_memory_utilization=safe_get(endpoint_conf, "gpu-memory-utilization"),
                    swap_space=safe_get(endpoint_conf, "swap-space"),
                    embedding_dim=safe_get(endpoint_conf, "embedding-dim"),
                )

            agents[name] = AgentConfig(
                name=name,
                alias=safe_get(agent_conf, "alias", name),
                description=safe_get(agent_conf, "description", ""),
                model=safe_get(agent_conf, "model", ""),
                backend=safe_get(agent_conf, "backend", "vllm"),
                optillm_technique=safe_get(agent_conf, "optillm-technique"),
                resources=resources,
                endpoint=endpoint,
            )

    # Parse backends
    optillm_conf = get("gaius.inference.backends.optillm", {})

    # Parse gunicorn sub-config
    gunicorn_conf = (
        optillm_conf.get("gunicorn", {})
        if hasattr(optillm_conf, "get")
        else {}
    )
    gunicorn = GunicornConfig(
        workers=gunicorn_conf.get("workers", 4)
        if hasattr(gunicorn_conf, "get")
        else 4,
        worker_class=gunicorn_conf.get("worker-class", "gthread")
        if hasattr(gunicorn_conf, "get")
        else "gthread",
        threads=gunicorn_conf.get("threads", 2)
        if hasattr(gunicorn_conf, "get")
        else 2,
        timeout=gunicorn_conf.get("timeout", 120)
        if hasattr(gunicorn_conf, "get")
        else 120,
        graceful_timeout=gunicorn_conf.get("graceful-timeout", 30)
        if hasattr(gunicorn_conf, "get")
        else 30,
        max_requests=gunicorn_conf.get("max-requests", 1000)
        if hasattr(gunicorn_conf, "get")
        else 1000,
        max_requests_jitter=gunicorn_conf.get("max-requests-jitter", 50)
        if hasattr(gunicorn_conf, "get")
        else 50,
        config_dir=gunicorn_conf.get("config-dir", "/tmp/gaius")
        if hasattr(gunicorn_conf, "get")
        else "/tmp/gaius",
    )

    optillm = OptillmConfig(
        enabled=optillm_conf.get("enabled", True) if hasattr(optillm_conf, "get") else True,
        api_key=optillm_conf.get("api-key") if hasattr(optillm_conf, "get") else None,
        base_url=optillm_conf.get("base-url", "http://localhost:8000")
        if hasattr(optillm_conf, "get")
        else "http://localhost:8000",
        backend_url=optillm_conf.get("backend-url", "http://localhost:8082/v1")
        if hasattr(optillm_conf, "get")
        else "http://localhost:8082/v1",
        default_technique=optillm_conf.get("default-technique", "cot_reflection")
        if hasattr(optillm_conf, "get")
        else "cot_reflection",
        timeout=optillm_conf.get("timeout", 120) if hasattr(optillm_conf, "get") else 120,
        use_gunicorn=optillm_conf.get("use-gunicorn", True)
        if hasattr(optillm_conf, "get")
        else True,
        gunicorn=gunicorn,
    )

    vllm_conf = get("gaius.inference.backends.vllm", {})
    vllm = VllmConfig(
        binary=vllm_conf.get("binary", "vllm") if hasattr(vllm_conf, "get") else "vllm",
        gpu_memory_utilization=vllm_conf.get("gpu-memory-utilization", 0.9)
        if hasattr(vllm_conf, "get")
        else 0.9,
        max_model_len=vllm_conf.get("max-model-len", 32768)
        if hasattr(vllm_conf, "get")
        else 32768,
        dtype=vllm_conf.get("dtype", "auto") if hasattr(vllm_conf, "get") else "auto",
        extra_args=vllm_conf.get("extra-args", []) if hasattr(vllm_conf, "get") else [],
    )

    # Parse GPU inventory
    gpus_conf = get("gaius.resources.gpus", {})
    gpus = GPUInventory(
        total=gpus_conf.get("total", 6) if hasattr(gpus_conf, "get") else 6,
        reserved=list(gpus_conf.get("reserved", [])) if hasattr(gpus_conf, "get") else [],
    )

    # Parse scheduling config
    sched_conf = get("gaius.resources.scheduling", {})
    scheduling = SchedulingConfig(
        prefer_contiguous=sched_conf.get("prefer-contiguous", True)
        if hasattr(sched_conf, "get")
        else True,
        allocation_timeout=sched_conf.get("allocation-timeout", 30)
        if hasattr(sched_conf, "get")
        else 30,
        allow_preemption=sched_conf.get("allow-preemption", False)
        if hasattr(sched_conf, "get")
        else False,
    )

    # Parse evolution config
    evo_conf = get("gaius.evolution", {})
    evolution = EvolutionConfig(
        enabled=evo_conf.get("enabled", True) if hasattr(evo_conf, "get") else True,
        rotation=list(
            evo_conf.get(
                "rotation",
                ["leader", "risk", "critic", "optimizer", "domain", "synthesis", "validator"],
            )
        )
        if hasattr(evo_conf, "get")
        else ["leader", "risk", "critic", "optimizer", "domain", "synthesis", "validator"],
        strategy=evo_conf.get("strategy", "apo") if hasattr(evo_conf, "get") else "apo",
        candidates_per_iteration=evo_conf.get("candidates-per-iteration", 5)
        if hasattr(evo_conf, "get")
        else 5,
        max_iterations=evo_conf.get("max-iterations", 3) if hasattr(evo_conf, "get") else 3,
        min_idle_gpus=evo_conf.get("min-idle-gpus", 2) if hasattr(evo_conf, "get") else 2,
        idle_timeout_seconds=evo_conf.get("idle-timeout-seconds", 300)
        if hasattr(evo_conf, "get")
        else 300,
        parallel_enabled=evo_conf.get("parallel", {}).get("enabled", False)
        if hasattr(evo_conf, "get") and hasattr(evo_conf.get("parallel", {}), "get")
        else False,
        parallel_max_concurrent=evo_conf.get("parallel", {}).get("max-concurrent", 6)
        if hasattr(evo_conf, "get") and hasattr(evo_conf.get("parallel", {}), "get")
        else 6,
    )

    # Parse flow scheduler config
    flow_conf = get("gaius.flow_scheduler", {})
    flow_scheduler = FlowSchedulerConfig(
        enabled=flow_conf.get("enabled", True) if hasattr(flow_conf, "get") else True,
        poll_interval_seconds=flow_conf.get("poll-interval-seconds", 60.0)
        if hasattr(flow_conf, "get")
        else 60.0,
        max_concurrent_flows=flow_conf.get("max-concurrent-flows", 2)
        if hasattr(flow_conf, "get")
        else 2,
        batch_size=flow_conf.get("batch-size", 5) if hasattr(flow_conf, "get") else 5,
        gpu_index=flow_conf.get("gpu-index", "4,5") if hasattr(flow_conf, "get") else "4,5",
        enable_topics=flow_conf.get("enable-topics", True)
        if hasattr(flow_conf, "get")
        else True,
        topic_model_type=flow_conf.get("topic-model-type", "bertopic")
        if hasattr(flow_conf, "get")
        else "bertopic",
        enable_scoring=flow_conf.get("enable-scoring", False)
        if hasattr(flow_conf, "get")
        else False,
    )

    # Parse ambient_buffer config (mandatory content fetching and summarization)
    ambient_conf = get("gaius.ambient_buffer", {})
    ambient_buffer = AmbientBufferConfig(
        source_url=ambient_conf.get("source-url", "https://hacker-news.firebaseio.com/v0/updates.json")
        if hasattr(ambient_conf, "get")
        else "https://hacker-news.firebaseio.com/v0/updates.json",
        newcomments=ambient_conf.get("newcomments", True)
        if hasattr(ambient_conf, "get")
        else True,
        max_items=ambient_conf.get("max-items", 10)
        if hasattr(ambient_conf, "get")
        else 10,
        buffer_max_bytes=ambient_conf.get("buffer-max-bytes", 256 * 1024)
        if hasattr(ambient_conf, "get")
        else 256 * 1024,
        summarize_max_tokens=ambient_conf.get("summarize-max-tokens", 256)
        if hasattr(ambient_conf, "get")
        else 256,
    )

    # Parse startup config
    startup_conf = get("gaius.startup", {})
    startup = StartupConfig(
        clean_start=startup_conf.get("clean-start", True)
        if hasattr(startup_conf, "get")
        else True,
        preload_endpoints=list(startup_conf.get("preload-endpoints", ["orchestrator", "instruct"]))
        if hasattr(startup_conf, "get")
        else ["orchestrator", "instruct"],
        auto_start_evolution=startup_conf.get("auto-start-evolution", True)
        if hasattr(startup_conf, "get")
        else True,
        auto_start_cognition=startup_conf.get("auto-start-cognition", True)
        if hasattr(startup_conf, "get")
        else True,
        auto_start_flow_scheduler=startup_conf.get("auto-start-flow-scheduler", True)
        if hasattr(startup_conf, "get")
        else True,
        auto_restart_failed=startup_conf.get("auto-restart-failed", True)
        if hasattr(startup_conf, "get")
        else True,
        max_restart_attempts=startup_conf.get("max-restart-attempts", 3)
        if hasattr(startup_conf, "get")
        else 3,
        auto_resume_ambient=startup_conf.get("auto-resume-ambient", True)
        if hasattr(startup_conf, "get")
        else True,
    )

    return EngineConfig(
        grpc=grpc,
        aeron=aeron,
        telemetry=telemetry,
        health_interval_ms=get("gaius.engine.health_interval_ms", 1000),
        agents=agents,
        optillm=optillm,
        vllm=vllm,
        gpus=gpus,
        scheduling=scheduling,
        evolution=evolution,
        flow_scheduler=flow_scheduler,
        ambient_buffer=ambient_buffer,
        startup=startup,
    )


def get_agent_by_alias(config: EngineConfig, alias: str) -> Optional[AgentConfig]:
    """Look up agent by alias.

    Args:
        config: Engine configuration
        alias: Agent alias (e.g., "orchestrator", "reasoning")

    Returns:
        AgentConfig if found, None otherwise
    """
    for agent in config.agents.values():
        if agent.alias == alias:
            return agent
    return None
