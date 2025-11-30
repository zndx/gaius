"""Core application logic."""

from .state import AppState, ViewMode, OverlayMode, CenterPanelMode, ReasoningTrace
from .links import LinkGraph, parse_wikilinks, resolve_link, create_linked_file
from .config import (
    GaiusConfig,
    get_config,
    load_config,
    reset_config,
    AppConfig,
    KBConfig,
    DatabaseConfig,
    VectorStoreConfig,
    InferenceConfig,
    SearchConfig,
    WorkersConfig,
    SwarmConfig,
    TDAConfig,
    UIConfig,
    StartupConfig,
    AwarenessConfig,
    TelemetryConfig,
)
from .telemetry import (
    get_tracer,
    get_meter,
    trace_operation,
    init_from_config as init_telemetry,
    record_search,
    record_inference,
    record_swarm_round,
)
from .projection import (
    GridProjector,
    GridData,
    GridDataManager,
    GridPoint,
    get_grid_manager,
)
from .tda import (
    TDAComputer,
    TDAFeatures,
    TDAManager,
    BoundingBox,
    get_tda_manager,
)

__all__ = [
    # State
    "AppState",
    "ViewMode",
    "OverlayMode",
    "CenterPanelMode",
    "ReasoningTrace",
    # Links
    "LinkGraph",
    "parse_wikilinks",
    "resolve_link",
    "create_linked_file",
    # Config
    "GaiusConfig",
    "get_config",
    "load_config",
    "reset_config",
    "AppConfig",
    "KBConfig",
    "DatabaseConfig",
    "VectorStoreConfig",
    "InferenceConfig",
    "SearchConfig",
    "WorkersConfig",
    "SwarmConfig",
    "TDAConfig",
    "UIConfig",
    "StartupConfig",
    "AwarenessConfig",
    "TelemetryConfig",
    # Telemetry
    "get_tracer",
    "get_meter",
    "trace_operation",
    "init_telemetry",
    "record_search",
    "record_inference",
    "record_swarm_round",
    # Projection
    "GridProjector",
    "GridData",
    "GridDataManager",
    "GridPoint",
    "get_grid_manager",
    # TDA
    "TDAComputer",
    "TDAFeatures",
    "TDAManager",
    "BoundingBox",
    "get_tda_manager",
]
