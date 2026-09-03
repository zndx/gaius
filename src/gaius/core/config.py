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
from typing import Any, Literal

from pyhocon import ConfigFactory, ConfigTree
from gaius.core.budgets import REASONING_MAX_TOKENS


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

    url: str = "postgres://localhost:5444/zndx_gaius?sslmode=disable"
    pool_size: int = 10


@dataclass
class VectorStoreConfig:
    """Qdrant vector store configuration.

    Uses ColNomic multi-vector embeddings (GPU-accelerated).
    NO CPU FALLBACK - GPU failures are surfaced, not hidden.
    """

    host: str = "localhost"
    port: int = 6339
    collection: str = "gaius_kb_colbert_zero"

    # Late-interaction embedder (ColBERT-Zero via pylate). ColNomic retired.
    colnomic_model: str = "lightonai/ColBERT-Zero"
    aggregation: str = "mean"  # "mean", "max", or "first" for aggregated single vector
    batch_size: int = 8  # Smaller batch size for GPU memory
    device: str = "cuda:0"  # GPU device for embeddings


@dataclass
class OptillmConfig:
    """optillm-specific settings."""

    url: str = "http://localhost:8080/v1"
    api_key: str = "sk-optillm"
    technique: str = ""


@dataclass
class VllmConfig:
    """vLLM-specific settings."""

    # Default to instruct endpoint (8082) per base.conf
    # Engine manages endpoints; this is overridden by HOCON config
    url: str = "http://localhost:8082/v1"


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
    max_tokens: int = REASONING_MAX_TOKENS


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
    projection_method: Literal["umap", "pca"] = "umap"
    max_points: int = 500  # Subsample for TDA (giotto-tda is O(n^3))


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
    """OpenTelemetry configuration.

    Telemetry is enabled by default. To disable, set OTEL_SDK_DISABLED=true
    in environment (standard OTel convention).
    """

    exporter: str = "otlp"  # otlp or console
    endpoint: str = "http://localhost:4317"
    service_name: str = "gaius"  # Base name, entry point suffix added at init


@dataclass
class CognitionConfig:
    """Background cognition agent configuration."""

    enabled: bool = True
    content_threshold: int = 10      # Items before auto-cognition
    time_threshold_hours: int = 4    # Max hours between cycles
    max_thoughts: int = 20           # Active thought limit
    greeting_thoughts: int = 3       # Thoughts to show on startup
    stale_days: int = 7              # Days before thoughts become stale
    use_llm: bool = True             # Always use LLM for generation


@dataclass
class SessionConfig:
    """Session lifecycle configuration."""

    enabled: bool = True
    gap_hours: int = 4               # Gap that defines a new session
    track_threads: bool = True       # Auto-detect research threads
    handoff_llm: bool = True         # Use LLM for handoff summaries
    max_threads: int = 10            # Max active threads to track


@dataclass
class IcebergConfig:
    """Apache Iceberg table format configuration."""

    catalog: str = "signals"
    namespace: str = "raw"
    use_minio: bool = True


@dataclass
class MinioConfig:
    """MinIO S3-compatible storage configuration."""

    endpoint: str = "127.0.0.1:9010"
    bucket: str = "signals-dataproducts"
    prefix: str = "gaius/hx/"        # Signals RustFS product prefix
    access_key: str = ""             # Set via env var
    secret_key: str = ""             # Set via env var


@dataclass
class FilesystemConfig:
    """Filesystem storage fallback configuration."""

    warehouse: str = ".iceberg"      # Hidden dir at KB root


@dataclass
class LineageConfig:
    """OpenLineage and AGE graph configuration."""

    enabled: bool = True
    graph_name: str = "gaius_hx"
    materialize_graph: bool = True   # Write to AGE graph when available


@dataclass
class HxConfig:
    """Gaius HX - Raw content data lake configuration.

    HX (history) stores high-volume raw fetched content in Apache Iceberg
    tables, separate from curated KB summaries. Supports MinIO primary
    storage with filesystem fallback.
    """

    enabled: bool = True
    iceberg: IcebergConfig = field(default_factory=IcebergConfig)
    minio: MinioConfig = field(default_factory=MinioConfig)
    filesystem: FilesystemConfig = field(default_factory=FilesystemConfig)
    lineage: LineageConfig = field(default_factory=LineageConfig)


@dataclass
class SummarizationConfig:
    """Content summarization pipeline configuration.

    Controls LLM-based summarization of raw content from HX to KB.
    Only high-value sources and compelling content are summarized;
    excluded content is tracked in lineage.
    """

    enabled: bool = True
    batch_size: int = 20                 # Items per summarization batch
    min_quality_score: float = 0.5       # Quality threshold for KB inclusion
    daily_token_limit: int = 500000      # Token budget per day
    model: str = ""                      # Override inference model (empty = use default)
    schedule_cron: str = "15 */2 * * *"  # Run every 2 hours at :15


@dataclass
class LambdaLabsConfig:
    """Lambda Labs GPU Cloud configuration."""

    enabled: bool = True
    api_key: str = ""
    api_base: str = "https://cloud.lambdalabs.com/api/v1"


@dataclass
class XAIConfig:
    """XAI (Grok) API configuration."""

    enabled: bool = True
    api_key: str = ""
    api_base: str = "https://api.x.ai/v1"
    management_key: str = ""


@dataclass
class CerebrasConfig:
    """Cerebras Inference API configuration."""

    enabled: bool = True
    api_key: str = ""
    api_base: str = "https://api.cerebras.ai/v1"


@dataclass
class BraveConfig:
    """Brave Search API configuration."""

    enabled: bool = True
    api_key: str = ""
    answers_api_key: str = ""


@dataclass
class R2Config:
    """Cloudflare R2 storage configuration."""

    access_key_id: str = ""
    secret_access_key: str = ""
    bucket: str = "gaius-viz"
    public_url: str = ""


@dataclass
class CloudflareConfig:
    """Cloudflare services configuration."""

    account_id: str = ""
    api_token: str = ""
    r2: R2Config = field(default_factory=R2Config)

    @property
    def r2_endpoint(self) -> str:
        """Derive R2 endpoint from account_id."""
        if self.account_id:
            return f"https://{self.account_id}.r2.cloudflarestorage.com"
        return ""


@dataclass
class ProvidersConfig:
    """Cloud GPU providers configuration."""

    lambdalabs: LambdaLabsConfig = field(default_factory=LambdaLabsConfig)
    xai: XAIConfig = field(default_factory=XAIConfig)
    cerebras: CerebrasConfig = field(default_factory=CerebrasConfig)
    brave: BraveConfig = field(default_factory=BraveConfig)


@dataclass
class ThemeConfig:
    """UI theme configuration.

    Themes control the visual appearance of Gaius. Built-in themes:
    - dark: Default dark theme with blue accents
    - light: Light theme for bright environments
    - terminal: Minimal, high-contrast terminal style
    - go: Muted wood-tone theme inspired by Go boards
    """

    name: str = "dark"
    # Border styling
    border_style: str = "solid"  # solid, round, double, heavy, none
    # Colors (Textual CSS color names or hex)
    primary: str = "$primary"
    secondary: str = "$secondary"
    surface: str = "$surface"
    accent: str = "$accent"
    # Component-specific
    panel_border: str = "$primary-darken-2"
    header_bg: str = "$primary-darken-3"
    status_bar_bg: str = "$primary-darken-3"


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
    theme: ThemeConfig = field(default_factory=ThemeConfig)
    cognition: CognitionConfig = field(default_factory=CognitionConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    hx: HxConfig = field(default_factory=HxConfig)
    summarization: SummarizationConfig = field(default_factory=SummarizationConfig)
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)
    cloudflare: CloudflareConfig = field(default_factory=CloudflareConfig)

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

    # Strip quotes from database URL if present (common .env issue)
    db_url = g.get("database.url", "postgres://localhost:5444/zndx_gaius?sslmode=disable")
    if isinstance(db_url, str):
        db_url = db_url.strip('"').strip("'")

    database = DatabaseConfig(
        url=db_url,
        pool_size=g.get("database.pool_size", 10),
    )

    vector_store = VectorStoreConfig(
        host=g.get("vector_store.host", "localhost"),
        port=g.get("vector_store.port", 6339),
        collection=g.get("vector_store.collection", "gaius_kb_colbert_zero"),
        colnomic_model=g.get("vector_store.colnomic_model", "lightonai/ColBERT-Zero"),
        aggregation=g.get("vector_store.aggregation", "mean"),
        batch_size=int(g.get("vector_store.batch_size", 8)),
        device=g.get("vector_store.device", "cuda:0"),
    )

    optillm = OptillmConfig(
        url=g.get("inference.optillm.url", "http://localhost:8080/v1"),
        api_key=g.get("inference.optillm.api_key", "sk-optillm"),
        technique=g.get("inference.optillm.technique", ""),
    )

    vllm = VllmConfig(
        url=g.get("inference.vllm.url", "http://localhost:8082/v1"),  # instruct endpoint
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

    # Validate projection_method is a valid literal
    raw_projection_method = g.get("tda.projection_method", "umap")
    projection_method: Literal["umap", "pca"] = (
        raw_projection_method if raw_projection_method in ("umap", "pca") else "umap"
    )  # type: ignore[assignment] - runtime check guarantees valid Literal value
    tda = TDAConfig(
        enabled=g.get("tda.enabled", True),
        compute_interval_minutes=int(g.get("tda.compute_interval_minutes", 60)),
        projection_method=projection_method,
        max_points=int(g.get("tda.max_points", 500)),
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
        exporter=g.get("telemetry.exporter", "otlp"),
        endpoint=g.get("telemetry.endpoint", "http://localhost:4317"),
        service_name=g.get("telemetry.service_name", "gaius"),
    )

    theme = ThemeConfig(
        name=g.get("theme.name", "dark"),
        border_style=g.get("theme.border_style", "solid"),
        primary=g.get("theme.primary", "$primary"),
        secondary=g.get("theme.secondary", "$secondary"),
        surface=g.get("theme.surface", "$surface"),
        accent=g.get("theme.accent", "$accent"),
        panel_border=g.get("theme.panel_border", "$primary-darken-2"),
        header_bg=g.get("theme.header_bg", "$primary-darken-3"),
        status_bar_bg=g.get("theme.status_bar_bg", "$primary-darken-3"),
    )

    cognition = CognitionConfig(
        enabled=g.get("cognition.enabled", True),
        content_threshold=int(g.get("cognition.content_threshold", 10)),
        time_threshold_hours=int(g.get("cognition.time_threshold_hours", 4)),
        max_thoughts=int(g.get("cognition.max_thoughts", 20)),
        greeting_thoughts=int(g.get("cognition.greeting_thoughts", 3)),
        stale_days=int(g.get("cognition.stale_days", 7)),
        use_llm=g.get("cognition.use_llm", True),
    )

    session = SessionConfig(
        enabled=g.get("session.enabled", True),
        gap_hours=int(g.get("session.gap_hours", 4)),
        track_threads=g.get("session.track_threads", True),
        handoff_llm=g.get("session.handoff_llm", True),
        max_threads=int(g.get("session.max_threads", 10)),
    )

    # Gaius HX - Raw content data lake
    hx_iceberg = IcebergConfig(
        catalog=g.get("hx.iceberg.catalog", "signals"),
        namespace=g.get("hx.iceberg.namespace", "raw"),
        use_minio=g.get("hx.iceberg.use_minio", True),
    )

    hx_minio = MinioConfig(
        endpoint=g.get("hx.minio.endpoint", "127.0.0.1:9010"),
        bucket=g.get("hx.minio.bucket", "signals-dataproducts"),
        prefix=g.get("hx.minio.prefix", "iceberg/"),
        access_key=g.get("hx.minio.access_key", ""),
        secret_key=g.get("hx.minio.secret_key", ""),
    )

    hx_filesystem = FilesystemConfig(
        warehouse=g.get("hx.filesystem.warehouse", ".iceberg"),
    )

    hx_lineage = LineageConfig(
        enabled=g.get("hx.lineage.enabled", True),
        graph_name=g.get("hx.lineage.graph_name", "gaius_hx"),
        materialize_graph=g.get("hx.lineage.materialize_graph", True),
    )

    hx = HxConfig(
        enabled=g.get("hx.enabled", True),
        iceberg=hx_iceberg,
        minio=hx_minio,
        filesystem=hx_filesystem,
        lineage=hx_lineage,
    )

    summarization = SummarizationConfig(
        enabled=g.get("summarization.enabled", True),
        batch_size=int(g.get("summarization.batch_size", 20)),
        min_quality_score=float(g.get("summarization.min_quality_score", 0.5)),
        daily_token_limit=int(g.get("summarization.daily_token_limit", 500000)),
        model=g.get("summarization.model", ""),
        schedule_cron=g.get("summarization.schedule_cron", "15 */2 * * *"),
    )

    # Cloud GPU providers
    lambdalabs = LambdaLabsConfig(
        enabled=g.get("providers.lambdalabs.enabled", True),
        api_key=g.get("providers.lambdalabs.api_key", ""),
        api_base=g.get("providers.lambdalabs.api_base", "https://cloud.lambdalabs.com/api/v1"),
    )

    xai = XAIConfig(
        enabled=g.get("providers.xai.enabled", True),
        api_key=g.get("providers.xai.api_key", ""),
        api_base=g.get("providers.xai.api_base", "https://api.x.ai/v1"),
        management_key=g.get("providers.xai.management_key", ""),
    )

    brave = BraveConfig(
        enabled=g.get("providers.brave.enabled", True),
        api_key=g.get("providers.brave.api_key", ""),
        answers_api_key=g.get("providers.brave.answers_api_key", ""),
    )

    cerebras = CerebrasConfig(
        enabled=g.get("providers.cerebras.enabled", True),
        api_key=g.get("providers.cerebras.api_key", ""),
        api_base=g.get("providers.cerebras.api_base", "https://api.cerebras.ai/v1"),
    )

    providers = ProvidersConfig(
        lambdalabs=lambdalabs,
        xai=xai,
        cerebras=cerebras,
        brave=brave,
    )

    # Cloudflare services
    r2 = R2Config(
        access_key_id=g.get("cloudflare.r2.access_key_id", ""),
        secret_access_key=g.get("cloudflare.r2.secret_access_key", ""),
        bucket=g.get("cloudflare.r2.bucket", "gaius-viz"),
        public_url=g.get("cloudflare.r2.public_url", ""),
    )

    cloudflare = CloudflareConfig(
        account_id=g.get("cloudflare.account_id", ""),
        api_token=g.get("cloudflare.api_token", ""),
        r2=r2,
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
        theme=theme,
        cognition=cognition,
        session=session,
        hx=hx,
        summarization=summarization,
        providers=providers,
        cloudflare=cloudflare,
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


def get_database_url() -> str:
    """Get database URL from config.

    This is a convenience function that provides a consistent way to get the
    database URL across the codebase. Previously this was defined in multiple
    places (storage/database.py, storage/grid_state.py, etc.).

    Returns:
        PostgreSQL connection URL from config.
    """
    import os

    # Check environment first (highest priority)
    env_url = os.environ.get("GAIUS_DATABASE_URL")
    if env_url:
        return env_url

    # Fall back to config
    config = get_config()
    return config.database.url
