"""Engine configuration loader using HOCON.

Loads agent-model pairings, resource requirements, and backend settings
from config/agents.conf.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

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
    """OpenTelemetry configuration."""

    enabled: bool = False
    endpoint: str = "http://localhost:4317"
    service_name: str = "gaius-engine"
    sampling_rate: float = 0.01


@dataclass
class OptillmConfig:
    """optillm backend configuration."""

    enabled: bool = True
    api_key: Optional[str] = None
    base_url: str = "http://localhost:8000"
    default_technique: str = "cot_reflection"
    timeout: int = 120


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
    if config_path is None:
        config_path = os.environ.get("GAIUS_CONFIG")

    if config_path is None:
        # Look for config relative to project root
        # __file__ is src/gaius/engine/config.py, so parents[3] is project root
        project_root = Path(__file__).parents[3]
        config_path = project_root / "config" / "agents.conf"

    config_path = Path(config_path)

    if not config_path.exists():
        logger.warning(f"Config file not found: {config_path}, using defaults")
        return EngineConfig()

    logger.info(f"Loading config from {config_path}")

    # Parse HOCON
    conf = ConfigFactory.parse_file(str(config_path))

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

    # Parse telemetry config
    telemetry = TelemetryConfig(
        enabled=get("gaius.engine.telemetry.enabled", False),
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
    optillm = OptillmConfig(
        enabled=optillm_conf.get("enabled", True) if hasattr(optillm_conf, "get") else True,
        api_key=optillm_conf.get("api-key") if hasattr(optillm_conf, "get") else None,
        base_url=optillm_conf.get("base-url", "http://localhost:8000")
        if hasattr(optillm_conf, "get")
        else "http://localhost:8000",
        default_technique=optillm_conf.get("default-technique", "cot_reflection")
        if hasattr(optillm_conf, "get")
        else "cot_reflection",
        timeout=optillm_conf.get("timeout", 120) if hasattr(optillm_conf, "get") else 120,
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
