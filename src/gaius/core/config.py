"""Unified HOCON configuration system for Gaius.

Configuration hierarchy (highest to lowest priority):
1. Environment variables (via HOCON ${?VAR} substitution)
2. Profile-specific config (config/profiles/*.conf)
3. Base config (config/base.conf)

Usage:
    from gaius.core.config import get_config, GaiusConfig

    config = get_config()  # Uses default profile
    config = get_config(profile="weathership")  # Specific profile
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pyhocon import ConfigFactory, ConfigTree


# Default config paths
# Path: src/gaius/core/config.py -> src/gaius/core -> src/gaius -> src -> (project root) -> config
DEFAULT_CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"
BASE_CONFIG = "base.conf"
PROFILES_DIR = "profiles"


@dataclass
class AppConfig:
    """Application identity configuration."""

    name: str = "Gaius"
    version: str = "0.2.0"
    subtitle: str = "Spatial Intelligence Interface"


@dataclass
class KBConfig:
    """Knowledge Base path configuration."""

    root: str = "build/dev"
    current: str = "build/dev/current"
    scratch: str = "build/dev/scratch"
    archive: str = "build/dev/archive"

    @property
    def root_path(self) -> Path:
        return Path(self.root)

    @property
    def current_path(self) -> Path:
        return Path(self.current)

    @property
    def scratch_path(self) -> Path:
        return Path(self.scratch)

    @property
    def archive_path(self) -> Path:
        return Path(self.archive)


@dataclass
class DatabaseConfig:
    """Database connection configuration."""

    url: str = "postgres://localhost:5438/zndx_gaius?sslmode=disable"
    pool_size: int = 10


@dataclass
class VectorStoreConfig:
    """Qdrant vector store configuration."""

    host: str = "localhost"
    port: int = 6339
    collection: str = "gaius_kb"
    embedding_model: str = "all-MiniLM-L6-v2"


@dataclass
class OptillmConfig:
    """optillm-specific settings."""

    url: str = "http://localhost:8080/v1"
    api_key: str = "sk-optillm"
    technique: str = ""


@dataclass
class VllmConfig:
    """vLLM-specific settings."""

    url: str = "http://localhost:8088/v1"


@dataclass
class PhaseModels:
    """Model routing by workflow phase."""

    exploration: str = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    synthesis: str = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    evaluation: str = "claude-sonnet-4-20250514"


@dataclass
class InferenceConfig:
    """Inference and LLM settings."""

    backend: str = "optillm"
    model: str = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    fallback_model: str = "gpt-4o-mini"
    optillm: OptillmConfig = field(default_factory=OptillmConfig)
    vllm: VllmConfig = field(default_factory=VllmConfig)
    phase_models: PhaseModels = field(default_factory=PhaseModels)
    offline_mode: bool = False
    timeout: float = 60.0
    max_tokens: int = 2048


@dataclass
class HybridSearchConfig:
    """Hybrid search weighting."""

    bm25_weight: float = 0.3
    vector_weight: float = 0.7


@dataclass
class SearchConfig:
    """Search configuration."""

    hybrid: HybridSearchConfig = field(default_factory=HybridSearchConfig)
    max_results: int = 20


@dataclass
class WorkersConfig:
    """Worker pool configuration."""

    pool_size: int = 4
    poll_interval: int = 30
    job_timeout: int = 300
    batch_size: int = 10
    max_retries: int = 3


@dataclass
class SwarmConfig:
    """DeepAgents swarm configuration."""

    enabled: bool = True
    auto_trigger_on_domain: bool = True
    roles: list[str] = field(
        default_factory=lambda: [
            "Leader",
            "Risk",
            "Optimizer",
            "Planner",
            "Critic",
            "Executor",
            "Adversary",
        ]
    )


@dataclass
class TDAConfig:
    """Topological Data Analysis configuration."""

    enabled: bool = True
    compute_interval_minutes: int = 60
    projection_method: str = "umap"


@dataclass
class UIConfig:
    """UI state configuration."""

    left_panel_visible: bool = True
    right_panel_visible: bool = True
    view_mode: str = "go"
    overlay_mode: str = "none"
    center_panel_mode: str = "graph"


@dataclass
class StartupConfig:
    """Startup procedure configuration."""

    commands: list[str] = field(default_factory=list)
    show_situational: bool = True


@dataclass
class AwarenessConfig:
    """Situational awareness horizons."""

    emphasis_hours: int = 24
    default_horizon_days: int = 7
    strategic_horizon_days: int = 90
    secular_horizon_days: int = 365


@dataclass
class TelemetryConfig:
    """OpenTelemetry configuration."""

    enabled: bool = False
    exporter: str = "console"
    endpoint: str = "http://localhost:4317"
    service_name: str = "gaius"


@dataclass
class ProfileConfig:
    """Profile metadata."""

    name: str = "default"
    description: str = ""
    feed_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class GaiusConfig:
    """Root configuration container.

    This is the main configuration object that holds all Gaius settings.
    It can be loaded from HOCON files with profile-specific overrides.
    """

    profile: str = "default"
    app: AppConfig = field(default_factory=AppConfig)
    kb: KBConfig = field(default_factory=KBConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    vector_store: VectorStoreConfig = field(default_factory=VectorStoreConfig)
    inference: InferenceConfig = field(default_factory=InferenceConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    workers: WorkersConfig = field(default_factory=WorkersConfig)
    swarm: SwarmConfig = field(default_factory=SwarmConfig)
    tda: TDAConfig = field(default_factory=TDAConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    startup: StartupConfig = field(default_factory=StartupConfig)
    awareness: AwarenessConfig = field(default_factory=AwarenessConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)

    # Raw HOCON tree for accessing custom settings
    _raw: ConfigTree | None = field(default=None, repr=False)

    def get(self, path: str, default: Any = None) -> Any:
        """Get a config value by dotted path from raw HOCON.

        Example:
            config.get("gaius.custom.setting", "default_value")
        """
        if self._raw is None:
            return default
        try:
            return self._raw.get(path, default)
        except Exception:
            return default


def _parse_config_tree(tree: ConfigTree) -> GaiusConfig:
    """Parse a HOCON ConfigTree into a GaiusConfig dataclass."""
    g = tree.get("gaius", {})

    # Parse nested configs
    app = AppConfig(
        name=g.get("app.name", "Gaius"),
        version=g.get("app.version", "0.2.0"),
        subtitle=g.get("app.subtitle", "Spatial Intelligence Interface"),
    )

    kb = KBConfig(
        root=g.get("kb.root", "build/dev"),
        current=g.get("kb.current", "build/dev/current"),
        scratch=g.get("kb.scratch", "build/dev/scratch"),
        archive=g.get("kb.archive", "build/dev/archive"),
    )

    database = DatabaseConfig(
        url=g.get("database.url", "postgres://localhost:5438/zndx_gaius?sslmode=disable"),
        pool_size=g.get("database.pool_size", 10),
    )

    vector_store = VectorStoreConfig(
        host=g.get("vector_store.host", "localhost"),
        port=g.get("vector_store.port", 6339),
        collection=g.get("vector_store.collection", "gaius_kb"),
        embedding_model=g.get("vector_store.embedding_model", "all-MiniLM-L6-v2"),
    )

    optillm = OptillmConfig(
        url=g.get("inference.optillm.url", "http://localhost:8080/v1"),
        api_key=g.get("inference.optillm.api_key", "sk-optillm"),
        technique=g.get("inference.optillm.technique", ""),
    )

    vllm = VllmConfig(
        url=g.get("inference.vllm.url", "http://localhost:8088/v1"),
    )

    phase_models = PhaseModels(
        exploration=g.get("inference.phase_models.exploration", g.get("inference.model", "")),
        synthesis=g.get("inference.phase_models.synthesis", g.get("inference.model", "")),
        evaluation=g.get("inference.phase_models.evaluation", "claude-sonnet-4-20250514"),
    )

    inference = InferenceConfig(
        backend=g.get("inference.backend", "optillm"),
        model=g.get("inference.model", "Qwen/Qwen3-Coder-30B-A3B-Instruct"),
        fallback_model=g.get("inference.fallback_model", "gpt-4o-mini"),
        optillm=optillm,
        vllm=vllm,
        phase_models=phase_models,
        offline_mode=g.get("inference.offline_mode", False),
        timeout=float(g.get("inference.timeout", 60)),
        max_tokens=int(g.get("inference.max_tokens", 2048)),
    )

    hybrid = HybridSearchConfig(
        bm25_weight=float(g.get("search.hybrid.bm25_weight", 0.3)),
        vector_weight=float(g.get("search.hybrid.vector_weight", 0.7)),
    )

    search = SearchConfig(
        hybrid=hybrid,
        max_results=int(g.get("search.max_results", 20)),
    )

    workers = WorkersConfig(
        pool_size=int(g.get("workers.pool_size", 4)),
        poll_interval=int(g.get("workers.poll_interval", 30)),
        job_timeout=int(g.get("workers.job_timeout", 300)),
        batch_size=int(g.get("workers.batch_size", 10)),
        max_retries=int(g.get("workers.max_retries", 3)),
    )

    swarm = SwarmConfig(
        enabled=g.get("swarm.enabled", True),
        auto_trigger_on_domain=g.get("swarm.auto_trigger_on_domain", True),
        roles=list(g.get("swarm.roles", [])) or SwarmConfig().roles,
    )

    tda = TDAConfig(
        enabled=g.get("tda.enabled", True),
        compute_interval_minutes=int(g.get("tda.compute_interval_minutes", 60)),
        projection_method=g.get("tda.projection_method", "umap"),
    )

    ui = UIConfig(
        left_panel_visible=g.get("ui.left_panel_visible", True),
        right_panel_visible=g.get("ui.right_panel_visible", True),
        view_mode=g.get("ui.view_mode", "go"),
        overlay_mode=g.get("ui.overlay_mode", "none"),
        center_panel_mode=g.get("ui.center_panel_mode", "graph"),
    )

    startup = StartupConfig(
        commands=list(g.get("startup.commands", [])),
        show_situational=g.get("startup.show_situational", True),
    )

    awareness = AwarenessConfig(
        emphasis_hours=int(g.get("awareness.emphasis_hours", 24)),
        default_horizon_days=int(g.get("awareness.default_horizon_days", 7)),
        strategic_horizon_days=int(g.get("awareness.strategic_horizon_days", 90)),
        secular_horizon_days=int(g.get("awareness.secular_horizon_days", 365)),
    )

    telemetry = TelemetryConfig(
        enabled=g.get("telemetry.enabled", False),
        exporter=g.get("telemetry.exporter", "console"),
        endpoint=g.get("telemetry.endpoint", "http://localhost:4317"),
        service_name=g.get("telemetry.service_name", "gaius"),
    )

    return GaiusConfig(
        profile=g.get("profile", "default"),
        app=app,
        kb=kb,
        database=database,
        vector_store=vector_store,
        inference=inference,
        search=search,
        workers=workers,
        swarm=swarm,
        tda=tda,
        ui=ui,
        startup=startup,
        awareness=awareness,
        telemetry=telemetry,
        _raw=tree,
    )


def load_config(
    profile: str | None = None,
    config_dir: Path | None = None,
) -> GaiusConfig:
    """Load configuration from HOCON files.

    Args:
        profile: Profile name to load (e.g., "weathership", "cloudera").
                 If None, uses value from base.conf or "default".
        config_dir: Path to config directory. Defaults to project config/.

    Returns:
        GaiusConfig with merged settings from base + profile.
    """
    if config_dir is None:
        config_dir = DEFAULT_CONFIG_DIR

    base_path = config_dir / BASE_CONFIG

    # Load base config
    if base_path.exists():
        base_tree = ConfigFactory.parse_file(str(base_path))
    else:
        # Fall back to defaults
        base_tree = ConfigTree()

    # Determine profile
    if profile is None:
        profile = base_tree.get("gaius.profile", "default")

    # Load profile-specific config
    profile_path = config_dir / PROFILES_DIR / f"{profile}.conf"
    if profile_path.exists():
        profile_tree = ConfigFactory.parse_file(str(profile_path))
        # Merge: profile overrides base
        merged = ConfigTree.merge_configs(base_tree, profile_tree)
    else:
        merged = base_tree

    # Parse into dataclass
    config = _parse_config_tree(merged)

    return config


# Global singleton
_config: GaiusConfig | None = None


def get_config(
    profile: str | None = None,
    reload: bool = False,
    config_dir: Path | None = None,
) -> GaiusConfig:
    """Get the global configuration singleton.

    Args:
        profile: Profile to load. If None, uses default.
        reload: If True, reload from files even if already loaded.
        config_dir: Path to config directory.

    Returns:
        The global GaiusConfig instance.
    """
    global _config

    if _config is None or reload or profile is not None:
        _config = load_config(profile=profile, config_dir=config_dir)

    return _config


def reset_config() -> None:
    """Reset the global config singleton (for testing)."""
    global _config
    _config = None
