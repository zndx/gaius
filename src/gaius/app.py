"""Gaius TUI Application.

A CLI-first terminal interface for navigating complex, graph-oriented data domains.
Renders high-dimensional embeddings and topological structures onto a constrained grid.

Usage:
    uv run gaius                    # Pure UI mode
    uv run gaius-cli --cmd "/state" # CLI mode
"""

# Suppress warnings BEFORE any imports that might trigger them
import asyncio
import os

# Suppress huggingface tokenizers parallelism warnings
# These warnings occur when tokenizers are used after process forking
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Configure joblib to use threading instead of multiprocessing
# This avoids fork() conflicts with gRPC while preserving parallelism.
# Threading works well for NumPy/sklearn/UMAP since they release the GIL.
os.environ.setdefault("LOKY_PICKLER", "pickle")  # Ensure compatibility
from joblib import parallel_config
parallel_config(backend="threading", n_jobs=-1)

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Static, Header, Footer, TextArea, Button

from .core.state import AppState, ViewMode, OverlayMode, CenterPanelMode, IsoMode
from .core.config import get_config, GaiusConfig
from .core.telemetry import init_from_config as init_telemetry
from .core.projection import get_grid_manager, GridData
# NOTE: get_tda_manager imported locally where needed (deferred for instant startup)
from .core.activity import get_activity_tracker, log_activity, ActivityType
from .core.session import get_session_manager, SessionHandoff
from .agents import get_swarm_manager
# Note: L5 CognitionAgent is deprecated - all cognition routes through Engine gRPC
from .awareness import generate_startup_report
from .widgets.grid import MainGrid
from .widgets.minigrid import MiniGrid
from .widgets.filetree import FileTree, FileTreeSelection, FileTreeHighlight
from .widgets.info_panel import InfoPanel
from .widgets.command import CommandInput, CommandSubmitted
from .widgets.location import LocationIndicator
from .widgets.note_editor import NoteEditor, EDITABLE_EXTENSIONS
from .widgets.graph_view import GraphView
from .widgets.link_preview import LinkPreview
from .widgets.think_panel import ThinkPanel
from .widgets.evolution_panel import EvolutionPanel
from .widgets.init_panel import InitPanel
from .widgets.observe_panel import ObservePanel
from .widgets.splash import SplashScreen
from .client.state_client import ConnectionStatus
from .storage.grid_state import load_current_state_fast_sync, CurrentState
from .static import (
    GRID_DATA,
    AGENT_DATA,
    DEATH_LOOPS,
    TDA_METRICS,
    get_minigrid_data,
    get_position_hint,
    generate_explanation,
)


def _generate_qr_ascii(url: str) -> str:
    """Generate ASCII QR code for the given URL.

    Uses the qrcode library to create a scannable QR code that works
    in terminal environments like a-Shell + tmux on iPad.
    """
    try:
        import io
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=1,
        )
        qr.add_data(url)
        qr.make(fit=True)

        # Capture ASCII output
        buffer = io.StringIO()
        qr.print_ascii(out=buffer, invert=True)
        return buffer.getvalue()
    except ImportError:
        return "(QR code requires 'qrcode' package: uv add qrcode)"
    except Exception as e:
        return f"(QR code generation failed: {e})"


class QRCodeModal(ModalScreen):
    """Modal displaying a QR code for easy scanning on mobile devices.

    Perfect for a-Shell + tmux setups on iPad where clipboard doesn't work.
    Scan the QR code with your device's camera app to open the URL.
    """

    DEFAULT_CSS = """
    QRCodeModal {
        align: center middle;
    }

    QRCodeModal > Vertical {
        width: auto;
        height: auto;
        max-width: 90%;
        max-height: 95%;
        background: white;
        padding: 1 2;
        border: thick $primary;
    }

    QRCodeModal #modal-title {
        text-align: center;
        text-style: bold;
        color: black;
        padding: 1 0;
        background: white;
    }

    QRCodeModal #modal-instructions {
        text-align: center;
        color: #666666;
        padding: 0 0 1 0;
        background: white;
    }

    QRCodeModal #qr-display {
        text-align: center;
        color: black;
        background: white;
        padding: 0;
        margin: 0;
    }

    QRCodeModal #url-display {
        text-align: center;
        color: #333333;
        background: #f0f0f0;
        padding: 1;
        margin: 1 0;
        height: auto;
        max-height: 3;
    }

    QRCodeModal Horizontal {
        align: center middle;
        height: auto;
        padding: 1 0;
        background: white;
    }

    QRCodeModal Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
    ]

    def __init__(self, title: str, url: str) -> None:
        super().__init__()
        self._title = title
        self._url = url
        self._qr_ascii = _generate_qr_ascii(url)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._title, id="modal-title")
            yield Static("Scan with your camera app", id="modal-instructions")
            yield Static(self._qr_ascii, id="qr-display")
            yield Static(self._url, id="url-display")
            with Horizontal():
                yield Button("Close [Esc]", id="close-button", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "close-button":
            self.dismiss()


# Keep CopyableTextModal as alias for backwards compatibility
CopyableTextModal = QRCodeModal


class GaiusApp(App):
    """Gaius: Augmented cognition through spatial visualization."""

    TITLE = "Gaius"
    SUB_TITLE = "Spatial Intelligence Interface"

    CSS = """
    /* ═══════════════════════════════════════════════════════════════════
       GAIUS TUI STYLESHEET

       Layout:
       ┌─────────┬────────────────────────────┬───────────┐
       │ Left    │  ┌──────────────┬────────┐ │ Right     │
       │ Panel   │  │              │  9×9   │ │ Panel     │
       │         │  │    19×19     │ Embed  │ │           │
       │ Files/  │  │    Main      ├────────┤ │ Content   │
       │ Agents  │  │    Grid      │  9×9   │ │           │
       │         │  │              │  Iso   │ │           │
       │         │  ├──────────────┴────────┤ │           │
       │         │  │◉ RA 12h30m Dec +45° ψ │ │           │
       │         │  ├───────────────────────┤ │           │
       │         │  │ Note Editor (Ctrl-N)  │ │           │
       │         │  └───────────────────────┘ │           │
       ├─────────┴────────────────────────────┴───────────┤
       │ Command Input                                     │
       └───────────────────────────────────────────────────┘
       ═══════════════════════════════════════════════════════════════════ */

    Screen {
        background: $surface;
        layers: base splash;
    }

    /* Splash screen overlay */
    SplashScreen {
        layer: splash;
    }

    /* ─────────────────────────────────────────────────────────────────────
       STATUS BAR
       ───────────────────────────────────────────────────────────────────── */
    #status-bar {
        dock: top;
        height: 1;
        background: $primary-darken-3;
        color: $text;
        padding: 0 1;
    }

    /* ─────────────────────────────────────────────────────────────────────
       MAIN LAYOUT
       ───────────────────────────────────────────────────────────────────── */
    #main-container {
        width: 100%;
        height: 1fr;
    }

    #main-horizontal {
        width: 100%;
        height: 100%;
    }

    /* ─────────────────────────────────────────────────────────────────────
       LEFT PANEL (Files/Agents)
       Interior border for visual separation
       ───────────────────────────────────────────────────────────────────── */
    #left-panel {
        width: 24;
        height: 100%;
        border-right: solid $primary-darken-2;
        overflow: hidden;
    }

    #left-panel.hidden {
        display: none;
    }

    #left-panel-header {
        height: 1;
        background: $primary-darken-3;
        padding: 0 1;
        text-style: bold;
    }

    /* ─────────────────────────────────────────────────────────────────────
       CENTER AREA (Grids)
       ───────────────────────────────────────────────────────────────────── */
    #center-area {
        width: 1fr;
        height: 100%;
        padding: 1;
        overflow: hidden;
    }

    /* Grid row: Main grid + right column of mini-grids */
    #grid-row {
        width: auto;
        height: auto;
    }

    #grid-row.hidden {
        display: none;
    }

    /* Main 19x19 grid wrapper */
    #main-grid-wrapper {
        width: auto;
        height: auto;
        overflow: hidden;
    }

    MainGrid {
        width: 40;
        height: 21;
        overflow: hidden;
    }

    /* Right column with two stacked mini-grids */
    #right-minigrids {
        width: auto;
        height: auto;
        margin-left: 1;
        overflow: hidden;
    }

    #minigrid-top {
        margin-bottom: 1;
    }

    /* Mini-grid styling - border-based visual separation */
    MiniGrid {
        width: 21;
        height: 11;
        padding: 0 1;
        overflow: hidden;
    }

    /* Graph wrapper (mirrors main-grid-wrapper for vertical alignment) */
    #graph-wrapper {
        width: 40;
        height: auto;
        margin-left: 1;
    }

    #graph-wrapper.hidden {
        display: none;
    }

    /* Graph view (wiki-link visualization) - 19x19 borderless grid */
    #graph-view {
        width: 40;
        height: 21;
        overflow: hidden;
    }

    /* Link preview (below graph, mirrors LocationIndicator) */
    #link-preview {
        width: 40;
        height: 1;
        margin-top: 0;
        background: #004295;
        color: #e0e0e0;
        text-align: left;
        padding: 0 1;
    }

    /* Think panel (reasoning traces) - bordered panel */
    #think-panel {
        width: 40;
        height: 21;
        margin-left: 1;
        overflow: hidden;
    }

    #think-panel.hidden {
        display: none;
    }

    /* Location indicator below main grid */
    #location-indicator {
        width: 100%;
        height: 1;
        margin-top: 0;
        background: #004295;
        color: #e0e0e0;
    }

    /* Note editor below location indicator */
    #note-editor {
        width: 100%;
        height: 1fr;
        min-height: 5;
        margin-top: 1;
    }

    #note-editor TextArea {
        width: 100%;
        height: 100%;
    }

    #note-editor.hidden {
        display: none;
    }

    #note-editor.zoomed {
        width: 100%;
        height: 1fr;
        margin: 0;
        padding: 0;
    }

    /* ─────────────────────────────────────────────────────────────────────
       RIGHT PANEL (Content)
       Border-based visual separation
       ───────────────────────────────────────────────────────────────────── */
    #right-panel {
        width: 32;
        height: 100%;
        overflow: hidden;
    }

    #right-panel.hidden {
        display: none;
    }

    InfoPanel {
        width: 100%;
        height: 100%;
        overflow: hidden auto;
    }

    /* ─────────────────────────────────────────────────────────────────────
       COMMAND INPUT (Bottom)
       Darker background for visual distinction (no borders)
       ───────────────────────────────────────────────────────────────────── */
    CommandInput {
        dock: bottom;
        height: 3;
        background: $surface-darken-1;
        padding: 0 1;
    }

    CommandInput Input {
        background: transparent;
        border: none;
    }

    CommandInput Input:focus {
        border: none;
    }

    /* ─────────────────────────────────────────────────────────────────────
       FOCUS INDICATORS
       Visual indication when widgets receive focus via Tab navigation.
       Uses existing interior borders - just changes color to $accent.
       ───────────────────────────────────────────────────────────────────── */

    /* Left panel - change interior border color on focus */
    #left-panel:focus-within {
        border-right: solid $accent;
    }

    /* Right panel (content) - change interior border color on focus */
    InfoPanel:focus {
        border-left: solid $accent;
    }

    /* Note editor focus - border around the editor area */
    #note-editor:focus-within {
        border: solid $accent;
    }
    """

    BINDINGS = [
        # Navigation
        Binding("h", "move(-1, 0)", "Left", show=False),
        Binding("j", "move(0, 1)", "Down", show=False),
        Binding("k", "move(0, -1)", "Up", show=False),
        Binding("l", "move(1, 0)", "Right", show=False),

        # View controls
        Binding("v", "cycle_view", "View"),
        Binding("o", "cycle_overlay", "Overlay"),
        Binding("i", "cycle_iso", "Iso Mode"),
        Binding("c", "toggle_candidates", "Candidates"),

        # Panel controls
        Binding("bracketleft", "toggle_left", "Files", show=False),  # [
        Binding("bracketright", "toggle_right", "Content", show=False),  # ]
        Binding("backslash", "toggle_both", "Panels"),  # \

        # Commands
        Binding("slash", "command_mode", "Command"),
        Binding("question_mark", "show_help", "Help"),

        # Tenuki (play elsewhere - jump to strategic point)
        Binding("t", "tenuki", "Tenuki"),

        # Notes
        Binding("ctrl+n", "new_note", "New Note"),
        Binding("ctrl+z", "zoom_editor", "Zoom", show=False),

        # Graph view (wiki-links) - 'g' cycles modes
        Binding("g", "toggle_graph", "Graph"),

        # Evolution panel - direct access
        Binding("e", "show_evolution", "Evolution"),

        # Quit hint (actual quit via /q or /exit command)
        Binding("q", "quit_hint", "Quit", show=False),
    ]

    def __init__(self, profile: str | None = None) -> None:
        super().__init__()
        self.config = get_config(profile=profile)
        init_telemetry(self.config, entry_point="tui")  # Initialize OpenTelemetry

        # Configure gRPC client for TUI: infinite retries, poll every 5 seconds
        # Must be done before any get_grpc_client() calls
        from .client.grpc_client import configure_grpc_client, GrpcClientConfig
        configure_grpc_client(GrpcClientConfig.for_tui())

        self.state = AppState()
        self._graph_update_timer: Timer | None = None
        self._connection_status: ConnectionStatus = ConnectionStatus.PENDING
        self._state_generation: int = 0
        self._apply_config()
        self._load_test_data()

    def _apply_config(self) -> None:
        """Apply HOCON configuration to app state."""
        ui = self.config.ui

        # Apply UI state from config
        self.state.left_panel_visible = ui.left_panel_visible
        self.state.right_panel_visible = ui.right_panel_visible

        # Apply view mode
        try:
            self.state.view_mode = ViewMode(ui.view_mode)
        except ValueError:
            pass  # Keep default

        # Apply overlay mode
        try:
            self.state.overlay_mode = OverlayMode(ui.overlay_mode)
        except ValueError:
            pass  # Keep default

        # Apply center panel mode
        try:
            self.state.center_panel_mode = CenterPanelMode(ui.center_panel_mode)
        except ValueError:
            pass  # Keep default

    def _load_test_data(self) -> None:
        """Initialize grid state on startup.

        Priority:
        1. Load from Postgres cache (instant, ~25ms)
        2. If KB has content but no cache, show empty grid + schedule auto-init
        3. Empty grid for fresh install

        Note: Static test data is no longer used - empty grid is cleaner.
        """
        # Try to load from cache first (fast Postgres path)
        if self._try_load_cached_state():
            return

        # No cache available - show empty grid with loading indicator
        self.state.black_stones = set()
        self.state.white_stones = set()
        self.state.allocations = [[0] * 19 for _ in range(19)]
        self.state.h1_cycles = []
        self.state.h2_voids = []
        self.state.tda_entropy = 0.0
        self._cache_source = "none"

        # Check if KB has real content - if so, schedule auto-init
        if self._kb_has_content():
            self._schedule_auto_init()

    def _kb_has_content(self) -> bool:
        """Check if KB has real content worth indexing."""
        try:
            kb_root = Path(self.config.kb.root)
            # Check for markdown files in allowed directories
            for allowed_dir in ("current", "scratch", "archive"):
                dir_path = kb_root / allowed_dir
                if dir_path.exists():
                    md_files = list(dir_path.rglob("*.md"))
                    if len(md_files) >= 3:  # At least 3 docs to make init worthwhile
                        return True
            return False
        except Exception:
            return False

    def _schedule_auto_init(self) -> None:
        """Schedule auto-initialization after app mount.

        Uses call_later to run init after the UI is fully rendered,
        keeping the app responsive during startup.
        """
        import asyncio

        async def run_auto_init():
            # Brief delay to let UI render first
            await asyncio.sleep(0.5)

            # Show notification
            content = self.query_one("#info-panel", InfoPanel)
            content.show_file(
                "auto-init.txt",
                "# Auto-Initializing\n\n"
                "KB content detected but no cache found.\n"
                "Running initialization in background...\n\n"
                "Press 'g' to toggle ThinkPanel for progress."
            )

            # Run the init
            await self._async_full_init()

        # Schedule to run after mount
        self.call_later(lambda: asyncio.create_task(run_auto_init()))

    def _populate_state_from_cache(self, cached: "CurrentState") -> bool:
        """Populate AppState from Postgres cache for instant startup.

        This converts the denormalized CurrentState (from current_state table)
        to AppState fields for immediate grid rendering.

        Args:
            cached: CurrentState loaded from Postgres cache

        Returns:
            True if state was populated successfully
        """
        try:
            # Grid positions - documents as black stones, clusters as white
            self.state.black_stones = {(d["x"], d["y"]) for d in cached.documents}
            self.state.white_stones = set(cached.clusters)
            self.state.allocations = cached.allocations

            # TDA features - convert bbox dicts to tuples
            self.state.h1_cycles = [
                (b["x_min"], b["y_min"], b["x_max"], b["y_max"])
                for b in cached.h1_cycles
            ]
            self.state.h2_voids = [
                (b["x_min"], b["y_min"], b["x_max"], b["y_max"])
                for b in cached.h2_voids
            ]
            self.state.tda_entropy = cached.entropy

            # Geometry features for dynamics overlay
            # gradient_field is list of [x, y, gx, gy]
            if cached.gradient_field:
                self.state.gradient_field = cached.gradient_field
                self.log.debug(f"Loaded {len(cached.gradient_field)} gradient vectors")

            # Curvature map for geometry overlay (convert flat to 19x19 if needed)
            if cached.curvature_map:
                if len(cached.curvature_map) == 361:
                    # Flat list - convert to 19x19
                    self.state.curvature_map = [
                        cached.curvature_map[i*19:(i+1)*19] for i in range(19)
                    ]
                else:
                    self.state.curvature_map = cached.curvature_map

            # Divergence map for dynamics overlay (convert flat to 19x19 if needed)
            if cached.divergence_map:
                if len(cached.divergence_map) == 361:
                    self.state.divergence_map = [
                        cached.divergence_map[i*19:(i+1)*19] for i in range(19)
                    ]
                else:
                    self.state.divergence_map = cached.divergence_map

            # Store generation for sync protocol
            self._state_generation = cached.generation

            # Mark cache as source
            self._cache_source = "postgres"

            self.log.info(
                f"Loaded from Postgres cache: {cached.n_documents} docs, "
                f"generation={cached.generation}"
            )
            return True

        except Exception as e:
            self.log.error(f"Failed to populate state from cache: {e}")
            return False

    def _try_load_cached_state(self) -> bool:
        """Try to load cached grid/TDA state for instant startup.

        Priority:
        1. Fast Postgres cache (denormalized current_state table, ~25ms)
        2. Legacy file-based cache (slower, for backwards compatibility)

        Returns:
            True if cache was loaded successfully
        """
        try:
            # Check if we're inside a running event loop (e.g., Textual tests)
            # The sync cache functions create new event loops, which fails in async context
            try:
                asyncio.get_running_loop()
                # Running inside event loop - skip cache loading
                # Auto-init will handle it via async path
                return False
            except RuntimeError:
                pass  # No running loop, safe to proceed

            # === Priority 1: Fast Postgres cache (denormalized JSON, ~25ms) ===
            # Note: load_current_state_fast_sync imported at module level
            cached = load_current_state_fast_sync(self.config.kb.root)
            if cached and cached.n_documents > 0:
                if self._populate_state_from_cache(cached):
                    return True
                # If populate failed, fall through to legacy cache

            # === Priority 2: Legacy file-based cache (backwards compatibility) ===
            from .core.cache import load_cached_state, check_cache_validity

            # Check if cache is valid for current config
            if not check_cache_validity(
                self.config.kb.root,
                self.config.vector_store.colnomic_model,
                self.config.tda.projection_method,
            ):
                return False

            # Load cached data (returns 4 values: grid_data, tda_features, metadata, iso_features)
            grid_data, tda_features, metadata, iso_features = load_cached_state(self.config.kb.root)

            if grid_data is None or tda_features is None:
                return False

            # Apply cached grid data to state
            self.state.black_stones = grid_data.document_positions
            self.state.white_stones = grid_data.cluster_centers
            self.state.allocations = grid_data.allocations
            self.state.iso_features = iso_features or grid_data.iso_features  # Multi-vector TDA

            # Apply cached TDA features
            self.state.h1_cycles = [dl.to_tuple() for dl in tda_features.h1_cycles]
            self.state.h2_voids = [v.to_tuple() for v in tda_features.h2_voids]
            self.state.tda_entropy = tda_features.entropy

            # Compute risk map from cached TDA
            if grid_data.embedding_to_grid and tda_features.risk_scores:
                self._compute_risk_map(tda_features, grid_data.embedding_to_grid)

            # Compute geometry from cached embeddings (for Iso view)
            # Skip if running inside event loop (e.g., Textual tests) - can't create nested loops
            if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) >= 15:
                try:
                    asyncio.get_running_loop()
                    # Running inside event loop - skip sync geometry computation
                    # Geometry will be computed later via async path
                except RuntimeError:
                    # No running loop - safe to create one for sync computation
                    try:
                        import numpy as np
                        from .core.geometry import GeometryComputer

                        grid_coords = np.array([(p.x, p.y) for p in grid_data.points])
                        gc = GeometryComputer(k_neighbors=min(15, len(grid_data.raw_embeddings) - 1))

                        # Run async geometry computation
                        loop = asyncio.new_event_loop()
                        geom_features = loop.run_until_complete(
                            gc.compute_features(grid_data.raw_embeddings, grid_coords)
                        )
                        loop.close()

                        # Populate geometry state
                        if geom_features:
                            self._populate_geometry_state(geom_features, grid_data)
                    except Exception:
                        # Geometry failed - Iso view will be empty but app still works
                        pass

            # Load agent positions from static data for now
            for agent in AGENT_DATA:
                self.state.agent_positions.append((
                    agent["name"],
                    agent["pos"][0],
                    agent["pos"][1],
                    agent["color"],
                ))

            return True

        except Exception as e:
            import traceback
            import logging
            logging.getLogger(__name__).warning(
                f"_try_load_cached_state failed: {e}\n{traceback.format_exc()}"
            )
            return False

    def _try_load_real_grid_data(self) -> bool:
        """Try to load real grid data from embeddings.

        Returns:
            True if real data was loaded, False to use fallback
        """
        try:
            # Get grid manager with config settings
            grid_manager = get_grid_manager(
                method=self.config.tda.projection_method,
                kb_root=self.config.kb.root,
            )

            # Try to get grid data (will be empty if Qdrant unavailable)
            grid_data = grid_manager.get_grid_data()

            if grid_data.n_documents == 0:
                return False  # No data, use fallback

            # Apply real data to state
            self.state.black_stones = grid_data.document_positions
            self.state.white_stones = grid_data.cluster_centers
            self.state.allocations = grid_data.allocations
            self.state.iso_features = grid_data.iso_features  # Multi-vector TDA

            # Try to compute TDA on 768-dim embeddings (not 2D projections)
            try:
                from .core.tda import get_tda_manager
                tda_manager = get_tda_manager()
                if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) >= 3:
                    import numpy as np
                    grid_coords = np.array([(p.x, p.y) for p in grid_data.points])
                    # Pass 768-dim embeddings for TDA, grid_coords for bounding boxes
                    features = tda_manager.compute_features(
                        grid_data.raw_embeddings,  # High-dim for real topology
                        grid_coords,               # 2D for visualization mapping
                    )
                    self.state.h1_cycles = [
                        dl.to_tuple() for dl in features.h1_cycles
                    ]
                    self.state.h2_voids = [
                        v.to_tuple() for v in features.h2_voids
                    ]
                    self.state.tda_entropy = features.entropy
                    # Compute risk map from per-point scores
                    self._compute_risk_map(features, grid_data.embedding_to_grid)
            except Exception:
                # TDA computation failed, use defaults
                self.state.h1_cycles = []
                self.state.h2_voids = []
                self.state.risk_map = []
                self.state.tda_entropy = 0.0

            # Compute geometry for Iso view
            if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) >= 15:
                try:
                    import asyncio
                    from .core.geometry import GeometryComputer

                    gc = GeometryComputer(k_neighbors=min(15, len(grid_data.raw_embeddings) - 1))
                    loop = asyncio.new_event_loop()
                    geom_features = loop.run_until_complete(
                        gc.compute_features(grid_data.raw_embeddings, grid_coords)
                    )
                    loop.close()

                    if geom_features:
                        self._populate_geometry_state(geom_features, grid_data)
                except Exception:
                    pass  # Geometry failed, Iso view will be empty

            # Still load agent positions from static data
            for agent in AGENT_DATA:
                self.state.agent_positions.append((
                    agent["name"],
                    agent["pos"][0],
                    agent["pos"][1],
                    agent["color"],
                ))

            return True

        except Exception:
            return False  # Any error, use fallback

    def _run_full_init(self) -> bool:
        """Run full initialization pipeline and cache results.

        Steps:
        1. Index KB documents with embeddings
        2. Project to 19x19 grid (UMAP/PCA)
        3. Compute TDA features on 768-dim embeddings
        4. Save to cache for fast startup

        Returns:
            True if initialization succeeded
        """
        try:
            from .inference.search import get_vector_search
            from .core.cache import save_cached_state
            import numpy as np

            # Step 1: Ensure KB is indexed (will skip if already done)
            vector_search = get_vector_search(self.config.kb.root)
            vector_search.index_kb()  # Index any new documents

            # Verify we have embeddings in Qdrant
            try:
                info = vector_search.client.get_collection(vector_search.collection_name)
                if info.points_count == 0:
                    return False  # No data to work with
            except Exception:
                return False

            # Step 2: Get grid manager and project embeddings
            grid_manager = get_grid_manager(
                method=self.config.tda.projection_method,
                kb_root=self.config.kb.root,
            )
            grid_manager.invalidate_cache()  # Force fresh projection
            grid_data = grid_manager.reindex_and_project()

            if grid_data.n_documents == 0:
                return False

            # Step 3: Compute TDA on 768-dim embeddings
            if grid_data.raw_embeddings is None or len(grid_data.raw_embeddings) < 3:
                return False

            from .core.tda import get_tda_manager
            tda_manager = get_tda_manager()
            tda_manager.invalidate_cache()

            grid_coords = np.array([(p.x, p.y) for p in grid_data.points])
            tda_features = tda_manager.compute_features(
                grid_data.raw_embeddings,  # High-dim for real topology
                grid_coords,               # 2D for visualization mapping
                force_refresh=True,
            )

            # Step 3.5: Compute differential geometry features
            try:
                from .core.geometry import GeometryComputer
                geom_computer = GeometryComputer(k_neighbors=15)

                # Compute curvature, gradients, divergence
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                geom_features = loop.run_until_complete(
                    geom_computer.compute_features(
                        grid_data.raw_embeddings,
                        grid_coords
                    )
                )
                loop.close()
            except Exception as e:
                print(f"Geometry computation failed (skipping): {e}")
                geom_features = None

            # Step 4: Save to cache
            save_cached_state(
                self.config.kb.root,
                grid_data,
                tda_features,
                self.config.vector_store.colnomic_model,
                self.config.tda.projection_method,
            )

            # Step 5: Apply to UI state
            self.state.black_stones = grid_data.document_positions
            self.state.white_stones = grid_data.cluster_centers
            self.state.allocations = grid_data.allocations
            self.state.iso_features = grid_data.iso_features  # Multi-vector TDA

            self.state.h1_cycles = [dl.to_tuple() for dl in tda_features.h1_cycles]
            self.state.h2_voids = [v.to_tuple() for v in tda_features.h2_voids]
            self.state.tda_entropy = tda_features.entropy

            # Populate geometry state
            if geom_features:
                self._populate_geometry_state(geom_features, grid_data)

            # Compute risk map
            self._compute_risk_map(tda_features, grid_data.embedding_to_grid)

            # Refresh UI
            self._refresh_grid()

            return True

        except Exception as e:
            import traceback
            print(f"Init error: {e}")
            traceback.print_exc()
            return False

    async def _async_full_init(self) -> None:
        """Async wrapper for _run_full_init with progress tracking."""
        from datetime import datetime
        from .core.state import BackgroundTask

        # Create background task
        task = BackgroundTask(
            id="init",
            name="Platform Init",
            status="running",
            started_at=datetime.now(),
        )
        self.state.background_tasks = [task]

        # Force ThinkPanel refresh
        try:
            think_panel = self.query_one("#think-panel", ThinkPanel)
            think_panel.refresh()
        except Exception:
            pass

        # Run in thread pool with stderr suppression
        import asyncio
        import sys
        import io

        def run_init():
            # Suppress stderr to prevent warnings from flooding the TUI
            # (tokenizers, transformers, etc. write warnings to stderr)
            old_stderr = sys.stderr
            sys.stderr = io.StringIO()

            # Track workload for resource management
            workload_id = None

            try:
                from .inference.search import get_vector_search
                from .core.cache import save_cached_state
                import numpy as np

                # Request GPU resources from engine (triggers preemption if needed)
                task.message = "Step 0/6: Requesting GPU resources..."
                task.progress = 0.05
                try:
                    from .client.engine_proxy import (
                        begin_workload_sync,
                        complete_workload_sync,
                        use_engine_proxy,
                    )
                    if use_engine_proxy():
                        workload_id = f"init-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                        result = begin_workload_sync(
                            workload_id=workload_id,
                            workload_type="INIT",
                            required_capabilities=["TEXT_EMBEDDING"],
                            priority="CRITICAL",
                            estimated_duration_s=300,
                            estimated_memory_mb=2000,
                        )
                        if result.evicted_endpoints:
                            task.message = f"Evicted {len(result.evicted_endpoints)} endpoints for init"
                except Exception as e:
                    # If workload request fails, continue anyway (may still work)
                    print(f"Workload request failed: {e}")

                task.message = "Step 1/6: Indexing KB documents..."
                task.progress = 0.1

                vector_search = get_vector_search(self.config.kb.root)
                vector_search.index_kb()

                try:
                    info = vector_search.client.get_collection(vector_search.collection_name)
                    if info.points_count == 0:
                        task.status = "failed"
                        task.error = "No documents in Qdrant"
                        return False
                except Exception as e:
                    task.status = "failed"
                    task.error = f"Qdrant error: {e}"
                    return False

                task.message = "Step 2/5: Loading embeddings..."
                task.progress = 0.25

                grid_manager = get_grid_manager(
                    method=self.config.tda.projection_method,
                    kb_root=self.config.kb.root,
                )
                grid_manager.invalidate_cache()

                task.message = "Step 3/5: Projecting to 19x19 grid (UMAP)..."
                task.progress = 0.4
                grid_data = grid_manager.reindex_and_project()

                if grid_data.n_documents == 0:
                    task.status = "failed"
                    task.error = "Projection failed"
                    return False

                if grid_data.raw_embeddings is None or len(grid_data.raw_embeddings) < 3:
                    task.status = "failed"
                    task.error = "No embeddings"
                    return False

                task.message = "Step 4/6: Computing TDA (H0/H1/H2)..."
                task.progress = 0.6

                from .core.tda import get_tda_manager
                tda_manager = get_tda_manager()
                tda_manager.invalidate_cache()

                grid_coords = np.array([(p.x, p.y) for p in grid_data.points])
                tda_features = tda_manager.compute_features(
                    grid_data.raw_embeddings,
                    grid_coords,
                    force_refresh=True,
                )

                task.message = "Step 5/6: Computing differential geometry (κ, ∇)..."
                task.progress = 0.75

                # Compute geometry features
                try:
                    from .core.geometry import GeometryComputer
                    geom_computer = GeometryComputer(k_neighbors=15)

                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    geom_features = loop.run_until_complete(
                        geom_computer.compute_features(
                            grid_data.raw_embeddings,
                            grid_coords
                        )
                    )
                    loop.close()
                except Exception as e:
                    print(f"Geometry computation failed (skipping): {e}")
                    geom_features = None

                task.message = "Step 6/6: Saving to cache..."
                task.progress = 0.9

                save_cached_state(
                    self.config.kb.root,
                    grid_data,
                    tda_features,
                    self.config.vector_store.colnomic_model,
                    self.config.tda.projection_method,
                )

                # Apply to state
                self.state.black_stones = grid_data.document_positions
                self.state.white_stones = grid_data.cluster_centers
                self.state.allocations = grid_data.allocations
                self.state.iso_features = grid_data.iso_features  # Multi-vector TDA
                self.state.h1_cycles = [dl.to_tuple() for dl in tda_features.h1_cycles]
                self.state.h2_voids = [v.to_tuple() for v in tda_features.h2_voids]
                self.state.tda_entropy = tda_features.entropy
                self._compute_risk_map(tda_features, grid_data.embedding_to_grid)

                # Populate geometry state
                if geom_features:
                    self._populate_geometry_state(geom_features, grid_data)

                self._refresh_grid()

                task.progress = 1.0
                task.status = "completed"
                task.completed_at = datetime.now()
                task.message = f"Complete: {grid_data.n_documents} docs, entropy={tda_features.entropy:.2f}"
                return True

            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                task.completed_at = datetime.now()
                return False
            finally:
                # Release workload resources (restores evicted endpoints)
                if workload_id:
                    try:
                        complete_workload_sync(workload_id)
                    except Exception:
                        pass  # Best effort

                # Restore stderr
                sys.stderr = old_stderr

        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, run_init)

        # Show result
        content = self.query_one("#info-panel", InfoPanel)
        if success:
            content.show_file(
                "init.txt",
                f"Platform initialized!\n\n"
                f"Documents: {len(self.state.black_stones)}\n"
                f"H1 cycles (loops): {len(self.state.h1_cycles)}\n"
                f"H2 voids (cavities): {len(self.state.h2_voids)}\n"
                f"Entropy: {self.state.tda_entropy:.2f}\n\n"
                f"Cache saved - future startups instant.\n"
                f"Press 'o' to cycle overlays."
            )
        else:
            content.show_file("init.txt", f"Init failed: {task.error}")

        # Keep task visible for a bit
        await asyncio.sleep(5)
        if task in self.state.background_tasks:
            self.state.background_tasks.remove(task)

    def _refresh_from_embeddings(self) -> bool:
        """Refresh grid data from KB embeddings and update cache.

        Called by /reindex command.

        Returns:
            True if refresh succeeded
        """
        try:
            from .core.cache import save_cached_state
            import numpy as np

            grid_manager = get_grid_manager(
                method=self.config.tda.projection_method,
                kb_root=self.config.kb.root,
            )

            # Reindex and project
            grid_data = grid_manager.reindex_and_project()

            if grid_data.n_documents > 0:
                self.state.black_stones = grid_data.document_positions
                self.state.allocations = grid_data.allocations
                self.state.iso_features = grid_data.iso_features  # Multi-vector TDA

                # Refresh TDA on 768-dim embeddings (not 2D projections)
                tda_features = None
                try:
                    from .core.tda import get_tda_manager
                    tda_manager = get_tda_manager()
                    if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) >= 3:
                        grid_coords = np.array([(p.x, p.y) for p in grid_data.points])
                        # Pass 768-dim embeddings for TDA, grid_coords for bounding boxes
                        tda_features = tda_manager.compute_features(
                            grid_data.raw_embeddings,  # High-dim for real topology
                            grid_coords,               # 2D for visualization mapping
                            force_refresh=True,
                        )
                        self.state.h1_cycles = [
                            dl.to_tuple() for dl in tda_features.h1_cycles
                        ]
                        self.state.h2_voids = [v.to_tuple() for v in tda_features.h2_voids]
                        self.state.tda_entropy = tda_features.entropy
                        # Compute risk map from per-point scores
                        self._compute_risk_map(tda_features, grid_data.embedding_to_grid)
                except Exception:
                    pass

                # Update cache with new data
                if tda_features is not None:
                    try:
                        save_cached_state(
                            self.config.kb.root,
                            grid_data,
                            tda_features,
                            self.config.vector_store.colnomic_model,
                            self.config.tda.projection_method,
                        )
                    except Exception:
                        pass  # Cache update is non-critical

                self._refresh_grid()
                return True

            return False

        except Exception:
            return False

    async def _async_refresh_from_embeddings(self) -> None:
        """Async wrapper for _refresh_from_embeddings with progress tracking."""
        from datetime import datetime
        from .core.state import BackgroundTask

        # Create background task
        task = BackgroundTask(
            id="reindex",
            name="Reindexing KB",
            status="running",
            started_at=datetime.now(),
        )
        self.state.background_tasks = [task]

        # Force ThinkPanel refresh
        try:
            think_panel = self.query_one("#think-panel", ThinkPanel)
            think_panel.refresh()
        except Exception:
            pass

        # Run in thread pool to avoid blocking
        import asyncio
        from functools import partial

        def run_reindex():
            try:
                task.message = "Step 1/4: Loading embeddings from Qdrant..."
                task.progress = 0.1

                from .core.cache import save_cached_state
                import numpy as np

                grid_manager = get_grid_manager(
                    method=self.config.tda.projection_method,
                    kb_root=self.config.kb.root,
                )

                task.message = "Step 2/4: Projecting to 19x19 grid (UMAP)..."
                task.progress = 0.3
                grid_data = grid_manager.reindex_and_project()

                if grid_data.n_documents == 0:
                    task.status = "failed"
                    task.error = "No documents found"
                    return False

                self.state.black_stones = grid_data.document_positions
                self.state.allocations = grid_data.allocations
                self.state.iso_features = grid_data.iso_features  # Multi-vector TDA

                # Refresh TDA
                task.message = "Step 3/4: Computing TDA features (H0/H1/H2)..."
                task.progress = 0.6

                tda_features = None
                try:
                    from .core.tda import get_tda_manager
                    tda_manager = get_tda_manager()
                    if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) >= 3:
                        grid_coords = np.array([(p.x, p.y) for p in grid_data.points])
                        tda_features = tda_manager.compute_features(
                            grid_data.raw_embeddings,
                            grid_coords,
                            force_refresh=True,
                        )
                        self.state.h1_cycles = [dl.to_tuple() for dl in tda_features.h1_cycles]
                        self.state.h2_voids = [v.to_tuple() for v in tda_features.h2_voids]
                        self.state.tda_entropy = tda_features.entropy
                        self._compute_risk_map(tda_features, grid_data.embedding_to_grid)
                except Exception as e:
                    task.error = f"TDA failed: {e}"

                # Update cache
                task.message = "Step 4/4: Saving to cache..."
                task.progress = 0.9

                if tda_features is not None:
                    try:
                        save_cached_state(
                            self.config.kb.root,
                            grid_data,
                            tda_features,
                            self.config.vector_store.colnomic_model,
                            self.config.tda.projection_method,
                        )
                    except Exception:
                        pass

                self._refresh_grid()
                task.progress = 1.0
                task.status = "completed"
                task.completed_at = datetime.now()
                task.message = f"Complete: {grid_data.n_documents} docs, H1={len(self.state.h1_cycles)}"
                return True

            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                task.completed_at = datetime.now()
                return False

        # Run in thread pool
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, run_reindex)

        # Show result in content panel
        content = self.query_one("#info-panel", InfoPanel)
        if success:
            content.show_file(
                "reindex.txt",
                f"Reindex complete!\n\n"
                f"Documents: {len(self.state.black_stones)}\n"
                f"H1 cycles (loops): {len(self.state.h1_cycles)}\n"
                f"H2 voids (cavities): {len(self.state.h2_voids)}\n"
                f"Entropy: {self.state.tda_entropy:.2f}\n\n"
                f"Press 'o' to cycle overlays."
            )
        else:
            content.show_file("reindex.txt", f"Reindex failed: {task.error}")

        # Keep task in history for a bit
        await asyncio.sleep(5)
        if task in self.state.background_tasks:
            self.state.background_tasks.remove(task)

    def _compute_risk_map(
        self,
        features,  # TDAFeatures
        embedding_to_grid: dict[int, tuple[int, int]],
    ) -> None:
        """Compute 19x19 risk map from TDA per-point risk scores.

        Maps risk_scores from embedding indices to grid positions,
        averaging when multiple embeddings map to the same cell.

        Args:
            features: TDAFeatures with risk_scores list
            embedding_to_grid: Mapping from embedding index to (x, y) grid position
        """
        if not features.risk_scores:
            self.state.risk_map = []
            return

        # Accumulate risk per cell (for averaging)
        risk_sum = [[0.0] * 19 for _ in range(19)]
        risk_count = [[0] * 19 for _ in range(19)]

        for idx, risk in enumerate(features.risk_scores):
            if idx in embedding_to_grid:
                x, y = embedding_to_grid[idx]
                if 0 <= x < 19 and 0 <= y < 19:
                    risk_sum[y][x] += risk
                    risk_count[y][x] += 1

        # Compute average risk per cell
        risk_map = []
        for y in range(19):
            row = []
            for x in range(19):
                if risk_count[y][x] > 0:
                    row.append(risk_sum[y][x] / risk_count[y][x])
                else:
                    row.append(0.0)  # No data for this cell
            risk_map.append(row)

        self.state.risk_map = risk_map

    def _populate_geometry_state(
        self,
        geom_features,  # GeometricFeatures
        grid_data: GridData,
    ) -> None:
        """Populate geometry state from differential geometry features.

        Maps curvature, gradients, and divergence to grid positions.

        Args:
            geom_features: GeometricFeatures with curvatures, gradients, divergence
            grid_data: GridData with embedding_to_grid mapping
        """
        import numpy as np

        # Build 19x19 curvature map
        curvature_sum = [[0.0] * 19 for _ in range(19)]
        curvature_count = [[0] * 19 for _ in range(19)]

        for idx, kappa in enumerate(geom_features.curvatures):
            if idx in grid_data.embedding_to_grid:
                x, y = grid_data.embedding_to_grid[idx]
                if 0 <= x < 19 and 0 <= y < 19:
                    curvature_sum[y][x] += kappa
                    curvature_count[y][x] += 1

        # Average curvature per cell
        curvature_map = []
        for y in range(19):
            row = []
            for x in range(19):
                if curvature_count[y][x] > 0:
                    row.append(curvature_sum[y][x] / curvature_count[y][x])
                else:
                    row.append(0.0)  # No data
            curvature_map.append(row)

        self.state.curvature_map = curvature_map

        # Store raw per-point curvatures for Iso view
        self.state.curvatures_raw = [float(k) for k in geom_features.curvatures]

        # Build gradient field (list of (x, y, gx, gy) tuples)
        gradient_field = []
        for idx, (gx, gy) in enumerate(geom_features.gradients):
            if idx in grid_data.embedding_to_grid:
                x, y = grid_data.embedding_to_grid[idx]
                if 0 <= x < 19 and 0 <= y < 19:
                    gradient_field.append([x, y, float(gx), float(gy)])

        self.state.gradient_field = gradient_field

        # Build 19x19 divergence map
        divergence_sum = [[0.0] * 19 for _ in range(19)]
        divergence_count = [[0] * 19 for _ in range(19)]

        for idx, div in enumerate(geom_features.divergence):
            if idx in grid_data.embedding_to_grid:
                x, y = grid_data.embedding_to_grid[idx]
                if 0 <= x < 19 and 0 <= y < 19:
                    divergence_sum[y][x] += div
                    divergence_count[y][x] += 1

        # Average divergence per cell
        divergence_map = []
        for y in range(19):
            row = []
            for x in range(19):
                if divergence_count[y][x] > 0:
                    row.append(divergence_sum[y][x] / divergence_count[y][x])
                else:
                    row.append(0.0)  # No data
            divergence_map.append(row)

        self.state.divergence_map = divergence_map

    def _run_swarm_analysis(self, domain_override: str | None = None) -> None:
        """Run swarm analysis on current domain.

        Args:
            domain_override: Override domain (otherwise uses state.domain)
        """
        import asyncio

        content = self.query_one("#info-panel", InfoPanel)
        domain = domain_override or self.state.domain or "general"

        # Update domain if override provided
        if domain_override:
            self.state.domain = domain_override
            self._update_status()

        # Show starting message
        content.show_file("swarm.txt", f"Running swarm analysis on: {domain}\n\nAgents: Leader, Risk, Optimizer, Planner, Critic, Executor, Adversary\n\nPlease wait...")

        try:
            # Run in event loop - always use async gRPC path
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule as task
                asyncio.create_task(self._complete_swarm_analysis(domain))
            else:
                # For non-running loop, use run_until_complete with the async method
                loop.run_until_complete(self._complete_swarm_analysis(domain))
        except Exception as e:
            content.show_file("error.txt", f"Swarm error: {e}")

    async def _complete_swarm_analysis(self, domain: str) -> None:
        """Complete CLT-based swarm analysis via Engine gRPC.

        Uses Cross-Layer Transcoders for interpretable agent collaboration:
        - Agents share sparse features (~115 active per layer)
        - Semantic positioning on same grid as KB documents
        - Time-delay trace embedding for exploration visualization

        All CLT processing happens in the Engine - no fallbacks.
        """
        from .client.engine_proxy import get_scheduler_proxy, use_engine_proxy
        from .agents.swarm import SwarmRoundResult, AgentResponse
        from .agents.roles import AgentRole
        from datetime import datetime

        content = self.query_one("#info-panel", InfoPanel)

        def on_progress(message: str, progress: float) -> None:
            """Update content panel with streaming progress."""
            pct = int(progress * 100)
            status_text = f"CLT Swarm Analysis: {domain}\n\n"
            status_text += f"Progress: {pct}%\n"
            status_text += f"Status: {message}\n"
            bar_width = 30
            filled = int(progress * bar_width)
            bar = "[" + "=" * filled + ">" + " " * (bar_width - filled - 1) + "]"
            status_text += f"\n{bar}\n"
            content.show_file("swarm.txt", status_text)

        try:
            if not use_engine_proxy():
                raise RuntimeError(
                    "Gaius engine not running.\n"
                    "  Try: devenv up -d\n"
                    "  #EN.00000001.NOTRUNNING"
                )

            scheduler = await get_scheduler_proxy()

            # Run CLT swarm via engine (CLT is the default, no fallback)
            raw_results, saved_path = await scheduler.run_swarm_clt(
                domain=domain,
                on_progress=on_progress,
            )

            # Convert engine response to SwarmRoundResult
            responses = []
            total_tokens = 0
            total_latency = 0
            consensus = ""

            for role_name, data in raw_results.items():
                try:
                    role_enum = AgentRole(role_name)
                except ValueError:
                    role_enum = AgentRole.LEADER

                response = AgentResponse(
                    role=role_enum,
                    name=role_name,
                    content=data.get("content", ""),
                    tokens=data.get("input_tokens", 0) + data.get("output_tokens", 0),
                    latency_ms=data.get("latency_ms", 0),
                    model=data.get("model", ""),
                    error=data.get("error") if data.get("status") == "failed" else None,
                )
                responses.append(response)
                total_tokens += response.tokens
                total_latency += response.latency_ms

                if role_name == "Leader" and response.succeeded:
                    consensus = response.content

            result = SwarmRoundResult(
                domain=domain,
                timestamp=datetime.now(),
                responses=responses,
                total_tokens=total_tokens,
                total_latency_ms=total_latency,
                consensus=consensus,
            )

            # Apply results with CLT-specific data from engine
            self._apply_clt_swarm_results(
                result,
                clt_data=raw_results.get("_clt", {}),
                saved_path=saved_path,
            )
        except Exception as e:
            content.show_file("error.txt", f"Swarm error: {e}")

    def _apply_swarm_results(self, result, saved_path: str = "") -> None:
        """Apply swarm results to state and UI."""
        import asyncio

        content = self.query_one("#info-panel", InfoPanel)
        think = self.query_one("#think-panel", ThinkPanel)

        # Log swarm activity
        asyncio.create_task(
            log_activity(
                ActivityType.SWARM_RUN,
                profile_name=self.config.profile,
                domain=result.domain,
                details={
                    "agents": len(result.responses),
                    "tokens": result.total_tokens,
                    "latency_ms": result.total_latency_ms,
                    "success_rate": result.success_rate,
                    "saved_to": saved_path,
                },
            )
        )

        # Update agent positions
        swarm_manager = get_swarm_manager()
        self.state.agent_positions = swarm_manager.get_agent_positions()

        # Add reasoning trace
        from datetime import datetime
        from .core.state import ReasoningTrace

        trace = ReasoningTrace(
            timestamp=datetime.now(),
            operation="swarm",
            query=result.domain,
            summary=f"Swarm round: {result.success_rate:.0%} success",
            tokens=result.total_tokens,
            sources=len(result.responses),
            technique="parallel",
            duration_ms=result.total_latency_ms,
        )
        self.state.add_reasoning_trace(trace)
        think.update_state(self.state)

        # Build result summary
        lines = [
            f"# Swarm Analysis: {result.domain}",
            "",
            f"**Success Rate:** {result.success_rate:.0%}",
            f"**Total Tokens:** {result.total_tokens}",
            f"**Latency:** {result.total_latency_ms}ms",
        ]
        if saved_path:
            lines.append(f"**Saved to:** {saved_path}")
        lines.extend([
            "",
            "## Agent Responses",
            "",
        ])

        for response in result.responses:
            status = "✓" if response.succeeded else "✗"
            lines.append(f"### {status} {response.name}")
            if response.succeeded:
                # Show first 300 chars of response
                preview = response.content[:300]
                if len(response.content) > 300:
                    preview += "..."
                lines.append(f"\n{preview}\n")
            else:
                lines.append(f"\n*Error: {response.error}*\n")

        if result.consensus:
            lines.extend([
                "",
                "## Consensus (Leader)",
                "",
                result.consensus,
            ])

        self._show_output("swarm_result", "\n".join(lines))
        self._refresh_grid()
        self._update_status()

    def _apply_clt_swarm_results(
        self,
        result,
        clt_data: dict | None = None,
        saved_path: str = "",
    ) -> None:
        """Apply CLT swarm results to state and UI with traces.

        All CLT data comes from the Engine via gRPC - no local CLT processing.

        Args:
            result: SwarmRoundResult with agent responses
            clt_data: CLT-specific data from engine (_clt field in response)
            saved_path: Path where results were saved in KB
        """
        import asyncio
        from .core.state import ViewMode

        content = self.query_one("#info-panel", InfoPanel)
        think = self.query_one("#think-panel", ThinkPanel)

        clt_data = clt_data or {}
        positions = clt_data.get("positions", [])
        traces = clt_data.get("traces", {})
        consensus_features = clt_data.get("consensus_features", {})
        feature_overlap = clt_data.get("feature_overlap", {})
        agent_features = clt_data.get("agent_features", {})

        # Log swarm activity
        asyncio.create_task(
            log_activity(
                ActivityType.SWARM_RUN,
                profile_name=self.config.profile,
                domain=result.domain,
                details={
                    "mode": "clt",
                    "agents": len(result.responses),
                    "tokens": result.total_tokens,
                    "latency_ms": result.total_latency_ms,
                    "success_rate": result.success_rate,
                    "consensus_features": len(consensus_features),
                    "saved_to": saved_path,
                },
            )
        )

        # Update agent positions from Engine's CLT projection
        self.state.agent_positions = [
            (p["name"], p["x"], p["y"], p["color"])
            for p in positions
        ]

        # Update agent traces for exploration visualization
        self.state.agent_traces = {
            name: [(pos["x"], pos["y"]) for pos in trace_positions]
            for name, trace_positions in traces.items()
        }

        # Switch to SWARM view to show traces
        self.state.view_mode = ViewMode.SWARM

        # Add reasoning trace
        from datetime import datetime
        from .core.state import ReasoningTrace

        trace = ReasoningTrace(
            timestamp=datetime.now(),
            operation="swarm",
            query=result.domain,
            summary=f"CLT swarm: {result.success_rate:.0%} success, {len(consensus_features)} consensus features",
            tokens=result.total_tokens,
            sources=len(result.responses),
            technique="clt-latent",
            duration_ms=result.total_latency_ms,
        )
        self.state.add_reasoning_trace(trace)
        think.update_state(self.state)

        # Build CLT-specific result summary
        lines = [
            f"# CLT Swarm Analysis: {result.domain}",
            "",
            "**Mode:** Cross-Layer Transcoder (interpretable features)",
            f"**Success Rate:** {result.success_rate:.0%}",
            f"**Total Tokens:** {result.total_tokens}",
            f"**Latency:** {result.total_latency_ms}ms",
        ]
        if saved_path:
            lines.append(f"**Saved to:** {saved_path}")

        lines.extend([
            "",
            "## Agent Positions (semantic projection)",
            "",
        ])

        # Show agent positions
        for name, x, y, color in self.state.agent_positions:
            lines.append(f"- **{name}**: ({x}, {y}) [{color}]")

        lines.extend([
            "",
            "## Agent Responses",
            "",
        ])

        for response in result.responses:
            status = "✓" if response.succeeded else "✗"
            lines.append(f"### {status} {response.name}")

            # Show top features for this agent (from engine CLT data)
            feats = agent_features.get(response.role.value, [])
            if feats:
                top_5 = [str(f["idx"]) for f in feats[:5]]
                lines.append(f"*Top features: {', '.join(top_5)}*")

            if response.succeeded:
                preview = response.content[:300]
                if len(response.content) > 300:
                    preview += "..."
                lines.append(f"\n{preview}\n")
            else:
                lines.append(f"\n*Error: {response.error}*\n")

        # Show consensus features
        if consensus_features:
            lines.extend([
                "",
                "## Feature Consensus",
                "",
            ])
            top_consensus = sorted(
                consensus_features.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]
            for feat_idx, score in top_consensus:
                lines.append(f"- Feature {feat_idx}: {score:.3f}")

        # Show feature overlap matrix
        if feature_overlap:
            lines.extend([
                "",
                "## Agent Alignment (feature overlap)",
                "",
            ])
            for key, sim in sorted(feature_overlap.items()):
                lines.append(f"- {key}: {sim:.3f}")

        if result.consensus:
            lines.extend([
                "",
                "## Consensus (Leader)",
                "",
                result.consensus,
            ])

        self._show_output("swarm_result", "\n".join(lines))
        self._refresh_grid()
        self._update_status()

    async def _resolve_broken_link(
        self,
        link_text: str,
        source_file: str | None,
        kb_root: Path,
    ) -> None:
        """Resolve a broken wiki link via search + synthesis.

        When a wiki link target doesn't exist:
        1. Run hybrid search (BM25 + vector + web) on link text
        2. Synthesize a zettelkasten note from results
        3. Update the original wiki link to point to the new note
        4. Open the new note in the editor

        Args:
            link_text: The wiki link content (verbatim, used as search query)
            source_file: Path to the file containing the wiki link (for backlink)
            kb_root: Knowledge base root directory
        """
        from datetime import datetime
        from .core.links import rewrite_link
        from .inference.synthesis import ZettelkastenSynthesizer, ZettelkastenNote

        content = self.query_one("#info-panel", InfoPanel)
        editor = self.query_one("#note-editor", NoteEditor)
        file_tree = self.query_one("#file-tree", FileTree)
        graph_view = self.query_one("#graph-view", GraphView)

        try:
            # Step 1: Run hybrid search
            content.show_file(
                "resolving.txt",
                f"Resolving [[{link_text}]]...\n\n"
                f"Step 1/3: Searching KB and web..."
            )

            # Import search components
            kb_results = []
            web_results = []
            errors = []

            # BM25 lexical search
            try:
                from .inference.search import get_kb_search
                kb_search = get_kb_search()
                if kb_search.index_size == 0:
                    kb_search.build_index()
                bm25_hits = kb_search.search(link_text, top_k=10)
                kb_results = [
                    {
                        "source": "bm25",
                        "path": r.path,
                        "title": r.title,
                        "snippet": r.snippet[:150],
                        "score": round(r.score, 2),
                    }
                    for r in bm25_hits
                ]
            except ImportError:
                errors.append("BM25 not available")
            except Exception as e:
                errors.append(f"BM25 error: {e}")

            # Web search
            try:
                from .inference import get_search
                search = get_search()
                web_hits = await search.search(link_text, count=5)
                web_results = [
                    {
                        "source": "web",
                        "url": r.url,
                        "title": r.title,
                        "snippet": r.snippet[:150],
                    }
                    for r in web_hits
                ]
            except ImportError:
                errors.append("Web search not available")
            except Exception as e:
                errors.append(f"Web search error: {e}")

            # Step 2: Synthesize note
            content.show_file(
                "resolving.txt",
                f"Resolving [[{link_text}]]...\n\n"
                f"Step 2/3: Synthesizing note from {len(kb_results)} KB + {len(web_results)} web results..."
            )

            synthesizer = ZettelkastenSynthesizer(kb_root)

            # Try to synthesize with LLM
            try:
                note = await synthesizer.synthesize(
                    query=link_text,
                    kb_results=kb_results,
                    web_results=web_results,
                )
                # Add origin metadata
                note.origin_file = source_file
                note.resolved_from = link_text
            except Exception as e:
                # Fallback: create basic note without LLM synthesis
                now = datetime.now()
                note = ZettelkastenNote(
                    query=link_text,
                    content=f"Search results for: {link_text}\n\n(LLM synthesis unavailable: {e})",
                    citations=[],
                    wiki_links=[],
                    created_at=now,
                    origin_file=source_file,
                    resolved_from=link_text,
                )

            # Save the note
            saved_path = note.save(kb_root)

            # Step 3: Update original wiki link
            content.show_file(
                "resolving.txt",
                f"Resolving [[{link_text}]]...\n\n"
                f"Step 3/3: Updating links..."
            )

            # Compute new link path (relative to kb_root, without .md)
            new_link_path = str(saved_path.relative_to(kb_root)).removesuffix(".md")

            if source_file:
                source_path = Path(source_file)
                rewrite_link(source_path, link_text, new_link_path)

            # Refresh UI
            file_tree.refresh_tree()

            # Open the new note in editor
            editor.remove_class("hidden")
            editor.open_note(str(saved_path))

            # Update graph view to show the new file
            graph_view.update_for_file(str(saved_path))

            # Show success message
            content.show_file(
                "resolved.txt",
                f"✓ Resolved [[{link_text}]]\n\n"
                f"Created: {saved_path.name}\n"
                f"Sources: {len(kb_results)} KB + {len(web_results)} web\n\n"
                f"The original link has been updated to point to the new note."
            )

        except Exception as e:
            content.show_file(
                "error.txt",
                f"Failed to resolve [[{link_text}]]\n\n"
                f"Error: {e}\n\n"
                f"You can manually create the file or try /search {link_text}"
            )

    def _show_agent_status(self) -> None:
        """Show current agent positions and status."""
        content = self.query_one("#info-panel", InfoPanel)

        lines = [
            "# Agent Status",
            "",
            "| Agent | Position | Color |",
            "|-------|----------|-------|",
        ]

        for name, x, y, color in self.state.agent_positions:
            coord = self._grid_to_coord(x, y)
            lines.append(f"| {name} | {coord} ({x},{y}) | {color} |")

        if not self.state.agent_positions:
            lines.append("| (no agents) | - | - |")

        lines.extend([
            "",
            "## Commands",
            "- `/swarm` - Run swarm analysis on current domain",
            "- `/swarm <domain>` - Run on specified domain",
            "- `/domain <name>` - Change domain",
        ])

        # Show last swarm summary if available
        swarm_manager = get_swarm_manager()
        last_round = swarm_manager.get_last_round()
        if last_round:
            lines.extend([
                "",
                "## Last Round",
                f"- Domain: {last_round.domain}",
                f"- Time: {last_round.timestamp.strftime('%H:%M:%S')}",
                f"- Success: {last_round.success_rate:.0%}",
            ])

        content.show_file("agents.md", "\n".join(lines))

    def _grid_to_coord(self, x: int, y: int) -> str:
        """Convert grid position to Go coordinate string."""
        col = chr(65 + x + (1 if x >= 8 else 0))  # Skip 'I'
        row = 19 - y
        return f"{col}{row}"

    def _show_daily_summary(self) -> None:
        """Generate and show daily summary."""
        import asyncio

        content = self.query_one("#info-panel", InfoPanel)
        think = self.query_one("#think-panel", ThinkPanel)

        content.show_file("summary.md", "Generating daily summary...\n\n*This may take a moment.*")
        think.stream_reasoning("Generating daily summary...")

        async def generate():
            try:
                from .agents import generate_daily_summary
                from datetime import datetime

                start_time = datetime.now()
                note = await generate_daily_summary(
                    profile=self.config.profile,
                    use_llm=True,
                    write_to_kb=True,
                )
                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                self._show_output("summary", note.to_markdown())

                # Record trace
                think.complete_trace(
                    operation="synthesis",
                    query="daily summary",
                    summary=f"Generated summary for {note.summary_date}",
                    tokens=0,
                    sources=len(note.key_entries),  # Number of KB entries in summary
                    duration_ms=duration_ms,
                )
            except Exception as e:
                think.clear_active()
                content.show_file("error.txt", f"Summary generation failed: {e}")

        asyncio.create_task(generate())

    def _show_activity(self) -> None:
        """Show recent activity log."""
        import asyncio

        content = self.query_one("#info-panel", InfoPanel)

        async def show():
            try:
                tracker = get_activity_tracker()

                # Get summaries
                today = await tracker.get_today()
                yesterday = await tracker.get_yesterday()
                week = await tracker.get_this_week()

                # Get recent events
                recent = await tracker.get_recent_events(limit=15)

                lines = [
                    "# Activity",
                    "",
                    today.to_markdown(),
                    "",
                ]

                if yesterday.total_events > 0:
                    lines.extend([
                        yesterday.to_markdown(),
                        "",
                    ])

                lines.extend([
                    "## This Week",
                    f"**Total events:** {week.total_events}",
                    f"**Queries:** {week.queries}",
                    f"**Swarm runs:** {week.swarm_runs}",
                    "",
                    "## Recent Events",
                ])

                for event in recent[:10]:
                    time_str = event.created_at.strftime("%H:%M")
                    domain_str = f" [{event.domain}]" if event.domain else ""
                    lines.append(f"- `{time_str}` **{event.event_type.value}**{domain_str}")

                if not recent:
                    lines.append("*No events recorded yet.*")

                content.show_file("activity.md", "\n".join(lines))

            except Exception as e:
                content.show_file("error.txt", f"Activity query failed: {e}")

        asyncio.create_task(show())

    def _explain_grid_view(self, args: str = "") -> None:
        """Explain current grid view using Engine gRPC (all computation server-side).

        Args:
            args: Optional arguments: [position] [--no-save]
                  position: Go notation like K10 (default: cursor position)
                  --no-save: Don't save explanation to KB (default: save)
        """
        import asyncio
        import math

        content = self.query_one("#info-panel", InfoPanel)
        think = self.query_one("#think-panel", ThinkPanel)
        editor = self.query_one("#note-editor", NoteEditor)
        file_tree = self.query_one("#file-tree", FileTree)

        # Parse args - save by default, --no-save to disable
        save_to_kb = "--no-save" not in args
        args = args.replace("--no-save", "").replace("--save", "").strip()

        # Determine position (from args or cursor)
        cx, cy = self.state.cursor_x, self.state.cursor_y
        if args:
            # Parse Go notation (e.g., K10)
            try:
                col = args[0].upper()
                row = int(args[1:])
                # Convert to grid coords (A=0, skip I, 1=bottom)
                col_idx = ord(col) - ord('A')
                if col >= 'I':
                    col_idx -= 1
                cx = col_idx
                cy = 19 - row
            except (ValueError, IndexError):
                pass  # Use cursor position

        # Convert to Go notation for display
        col_letter = chr(ord('A') + cx + (1 if cx >= 8 else 0))
        position_str = f"{col_letter}{19 - cy}"

        # Show immediate feedback in InfoPanel
        save_text = "saving to KB" if save_to_kb else "not saving"
        content.show_file(
            "explain.md",
            f"# Explain: {position_str}\n\n"
            f"*Generating explanation for position {position_str} ({cx}, {cy})...*\n\n"
            f"*Mode: {save_text}*\n\n"
            f"This may take 10-20 seconds while the LLM generates an interpretation."
        )

        async def generate():
            from .client.grpc_client import get_grpc_client

            try:
                think.start_trace(
                    operation="explanation",
                    query="grid interpretation",
                    model="Engine gRPC"
                )

                # Update status - connecting
                content.show_file(
                    "explain.md",
                    f"# Explain: {position_str}\n\n"
                    f"*Connecting to Engine...*"
                )

                client = await get_grpc_client()
                if not client:
                    raise RuntimeError(
                        "Engine not available.\n"
                        "Guru Meditation: #EXP.00000001.NOENGINE\n"
                        "Try: /health fix engine\n"
                        "Or: devenv tasks run restart:clean"
                    )

                # Update status - generating
                content.show_file(
                    "explain.md",
                    f"# Explain: {position_str}\n\n"
                    f"*Computing geometry, TDA features, and generating LLM interpretation...*\n\n"
                    f"This typically takes 10-20 seconds."
                )

                # Call Engine - all heavy lifting happens server-side
                response = await client.explain(
                    kb_root="build/dev",
                    x=cx,
                    y=cy,
                    save_to_kb=save_to_kb,
                    max_tokens=800,
                    client_id="tui",
                )

                if not response.success:
                    raise RuntimeError(response.error or "Explain request failed")

                # Build output from response
                output = [
                    f"# Grid Explanation: {response.position}",
                    "",
                    f"**Position:** {response.position} ({response.x}, {response.y})",
                    f"**Document:** {response.document_title or 'Empty cell'}",
                    "",
                ]

                # Add geometric features summary
                if response.curvature != 0:
                    output.append("## Differential Geometry")
                    output.append("")
                    output.append(f"- **Ricci curvature κ:** {response.curvature:.3f}")
                    if response.gradient_x != 0 or response.gradient_y != 0:
                        mag = math.sqrt(response.gradient_x**2 + response.gradient_y**2)
                        output.append(f"- **Gradient magnitude:** {mag:.3f}")
                    if response.divergence != 0:
                        output.append(f"- **Divergence:** {response.divergence:.3f}")
                    output.append("")

                # TDA context
                if response.h0_count or response.h1_count or response.h2_count:
                    output.append("## Topological Context")
                    output.append("")
                    output.append(f"- **H0 (components):** {response.h0_count}")
                    output.append(f"- **H1 (loops):** {response.h1_count}")
                    output.append(f"- **H2 (voids):** {response.h2_count}")
                    if response.tda_entropy:
                        output.append(f"- **Entropy:** {response.tda_entropy:.3f}")
                    if response.risk_score:
                        output.append(f"- **Risk score:** {response.risk_score:.3f}")
                    output.append("")

                output.extend([
                    "## LLM Interpretation",
                    "",
                    response.explanation,
                ])

                # Display results (following /ambient buffer pattern)
                from pathlib import Path
                import os

                if response.saved_path:
                    saved_file = Path(response.saved_path)

                    # Show status summary in InfoPanel (like /ambient buffer)
                    nbsp = "\u00a0"
                    status_lines = [
                        f"# Explain: {response.position}",
                        "",
                        f"Document{nbsp * 3}{response.document_title or 'Empty cell'}  ",
                        f"Curvature{nbsp * 2}κ = {response.curvature:.3f}  ",
                        f"Duration{nbsp * 3}{response.duration_ms}ms  ",
                        f"Model{nbsp * 6}{response.model or 'unknown'}  ",
                        "",
                        f"Saved{nbsp * 6}`{os.path.basename(response.saved_path)}`  ",
                        "",
                        "---",
                        "",
                        "*File opened in Editor panel with full minigrid visualizations.*",
                    ]
                    content.show_file("explain.md", "\n".join(status_lines))

                    # Open the saved file in Editor (has proper minigrids)
                    if saved_file.exists():
                        editor.remove_class("hidden")
                        editor.open_note(str(saved_file))
                        file_tree.refresh_tree()
                    else:
                        content.show_file(
                            "error.txt",
                            f"Saved file not found: {response.saved_path}\n\n"
                            f"The Engine reported saving but file doesn't exist."
                        )
                else:
                    # No save (--no-save mode) - show in InfoPanel only
                    output.extend([
                        "",
                        "---",
                        "",
                        "*Not saved to KB (--no-save mode)*",
                    ])
                    content.show_file("explain.md", "\n".join(output))

                # Record trace
                summary = f"Generated explanation in {response.duration_ms}ms"
                if response.saved_path:
                    import os
                    summary += f" (saved to {os.path.basename(response.saved_path)})"
                think.complete_trace(
                    operation="explanation",
                    query="grid interpretation",
                    summary=summary,
                    tokens=0,
                    sources=1,
                    duration_ms=response.duration_ms,
                )

            except Exception as e:
                import traceback
                think.clear_active()
                error_detail = traceback.format_exc()
                content.show_file(
                    "error.txt",
                    f"Explanation failed: {e}\n\n"
                    f"Ensure Engine is running with inference endpoints.\n\n"
                    f"Details:\n{error_detail}"
                )

        asyncio.create_task(generate())

    def _handle_inference_command(self, args: str) -> None:
        """Handle /inference subcommands.

        Usage:
            /inference status              - Show all endpoints and queue status
            /inference start <endpoint>    - Start specific endpoint
            /inference stop <endpoint>     - Stop specific endpoint
            /inference restart <endpoint>  - Restart specific endpoint
            /inference ensure              - Ensure default model (nvidia/Orchestrator-8B) running
        """
        import asyncio
        from .inference.manager import get_inference_manager
        from .engine.backends.vllm_controller import ProcessStatus

        content = self.query_one("#info-panel", InfoPanel)

        if not args or args == "status":
            # Show status
            async def show_status():
                try:
                    manager = get_inference_manager()
                    status = await manager.get_status()

                    # Format endpoint status
                    endpoint_lines = []
                    for name, proc_status in status.endpoints_running.items():
                        status_icon = "✓" if proc_status == ProcessStatus.HEALTHY else "✗"
                        endpoint_lines.append(f"  {status_icon} **{name}**: {proc_status.value}")

                    endpoints_text = "\n".join(endpoint_lines) if endpoint_lines else "  *No endpoints running*"

                    output = f"""# Inference Stack Status

**Orchestrator**: {'Running' if status.orchestrator_running else 'Stopped'}
**Scheduler**: {'Healthy' if status.scheduler_healthy else 'Unhealthy'}
**Default Model** (nvidia/Orchestrator-8B): {'Ready' if status.default_model_ready else 'Not Ready'}

## Endpoints

{endpoints_text}

## Metrics

**Total Requests**: {status.total_requests}
**Queue Depth**: {status.queue_depth}

---

Use `/inference ensure` to start the default model (nvidia/Orchestrator-8B).
Use `/inference start <endpoint>` to start an endpoint.
Use `/inference stop <endpoint>` to stop an endpoint.
"""
                    content.show_file("inference.md", output)

                except Exception as e:
                    content.show_file("error.txt", f"Failed to get status: {e}")

            asyncio.create_task(show_status())

        elif args.startswith("start "):
            endpoint = args[6:].strip()
            if not endpoint:
                content.show_file("error.txt", "Usage: /inference start <endpoint>")
                return

            content.show_file("inference.txt", f"Starting {endpoint}...")

            async def start():
                try:
                    manager = get_inference_manager()
                    success = await manager.start_endpoint(endpoint)

                    if success:
                        content.show_file("inference.txt", f"Started {endpoint} successfully.")
                    else:
                        content.show_file("error.txt", f"Failed to start {endpoint}.")

                except Exception as e:
                    content.show_file("error.txt", f"Error starting {endpoint}: {e}")

            asyncio.create_task(start())

        elif args.startswith("stop "):
            endpoint = args[5:].strip()
            if not endpoint:
                content.show_file("error.txt", "Usage: /inference stop <endpoint>")
                return

            content.show_file("inference.txt", f"Stopping {endpoint}...")

            async def stop():
                try:
                    manager = get_inference_manager()
                    success = await manager.stop_endpoint(endpoint)

                    if success:
                        content.show_file("inference.txt", f"Stopped {endpoint} successfully.")
                    else:
                        content.show_file("error.txt", f"Failed to stop {endpoint}.")

                except Exception as e:
                    content.show_file("error.txt", f"Error stopping {endpoint}: {e}")

            asyncio.create_task(stop())

        elif args.startswith("restart "):
            endpoint = args[8:].strip()
            if not endpoint:
                content.show_file("error.txt", "Usage: /inference restart <endpoint>")
                return

            content.show_file("inference.txt", f"Restarting {endpoint}...")

            async def restart():
                try:
                    manager = get_inference_manager()
                    success = await manager.restart_endpoint(endpoint)

                    if success:
                        content.show_file("inference.txt", f"Restarted {endpoint} successfully.")
                    else:
                        content.show_file("error.txt", f"Failed to restart {endpoint}.")

                except Exception as e:
                    content.show_file("error.txt", f"Error restarting {endpoint}: {e}")

            asyncio.create_task(restart())

        elif args == "ensure":
            # Ensure default model (nvidia/Orchestrator-8B) is running
            content.show_file("inference.txt", "Ensuring nvidia/Orchestrator-8B is running...")

            async def ensure():
                try:
                    manager = get_inference_manager()

                    # Track progress in content panel
                    progress_lines = ["# Starting nvidia/Orchestrator-8B", ""]

                    def update_progress(task_name: str, progress: float, message: str):
                        progress_lines.append(f"[{progress:.0%}] {message}")
                        content.show_file("inference.md", "\n".join(progress_lines))

                    success = await manager.ensure_orchestrator_running(update_progress)

                    if success:
                        progress_lines.append("")
                        progress_lines.append("✓ nvidia/Orchestrator-8B is ready")
                        content.show_file("inference.md", "\n".join(progress_lines))
                    else:
                        content.show_file("error.txt", "Failed to ensure default model is running.")

                except Exception as e:
                    content.show_file("error.txt", f"Error ensuring default model: {e}")

            asyncio.create_task(ensure())

        else:
            content.show_file("error.txt", f"Unknown inference subcommand: {args}\n\nUsage:\n  /inference status\n  /inference start <endpoint>\n  /inference stop <endpoint>\n  /inference restart <endpoint>\n  /inference ensure")

    def _handle_evolve_command(self, args: str) -> None:
        """Handle /evolve subcommands for evolution daemon.

        Usage:
            /evolve                     - Start orchestrator-managed evolution (default)
            /evolve orchestrated        - Start orchestrator-managed evolution
            /evolve start [--parallel]  - Start simple daemon (legacy)
            /evolve stop                - Stop evolution
            /evolve status              - Show daemon status
            /evolve trigger [agent]     - Force an evolution cycle
            /evolve budget              - Show XAI evaluation budget

        Options:
            --parallel: Start 6 parallel vLLM instances for faster evolution
        """
        import asyncio

        content = self.query_one("#info-panel", InfoPanel)

        parts = args.split() if args else []
        subcmd = parts[0].lower() if parts else "orchestrated"  # Default to orchestrated
        subargs = parts[1:] if len(parts) > 1 else []

        if subcmd == "start":
            # Parse options
            parallel = "--parallel" in subargs or "-p" in subargs

            if parallel:
                endpoints = ["evo0", "evo1", "evo2", "evo3", "evo4", "evo5"]
                mode_text = "**6 parallel GPUs**"
            else:
                endpoints = ["fast"]
                mode_text = "single endpoint"

            content.show_file("evolve.md", f"# Evolution Daemon\n\nStarting clean start with {mode_text}...\n\nPhase 1: Cleaning stale GPU processes...")

            async def start():
                try:
                    from .client.engine_proxy import get_orchestrator_proxy, use_engine_proxy
                    from .agents.evolution import get_evolution_daemon

                    # Engine Federation Architecture: GPU operations require engine gRPC
                    if not use_engine_proxy():
                        content.show_file("error.txt", """# Engine Not Available

GPU operations require the engine gRPC service.

## Guru Meditation
`#GR.00000001.ENGINEOFF`

## Remediation
- Start the engine: `devenv up gaius-engine`
- Or: `uv run python -m gaius.engine`
""")
                        return

                    orch = await get_orchestrator_proxy()
                    result = await orch.clean_start(endpoints)

                    if not result["success"]:
                        content.show_file("error.txt", f"Failed to start GPU endpoints: {result['startup']}")
                        return

                    # Phase 2: Start daemon with parallel mode
                    content.show_file("evolve.md", f"# Evolution Daemon\n\nPhase 1: ✓ GPUs ready ({len(endpoints)} endpoints)\nPhase 2: Starting daemon...")

                    daemon = get_evolution_daemon()
                    await daemon.start(parallel=parallel)

                    status = daemon.get_status()
                    endpoints_text = '\n'.join(f"- {ep}: ✓" for ep in endpoints)
                    content.show_file("evolve.md", f"""# Evolution Daemon

**Status**: Running ✓
**Mode**: {'Parallel (6 GPUs)' if parallel else 'Single GPU'}
**Next Agent**: {status.get('next_agent', 'unknown')}
**Strategy**: {status.get('config', {}).get('strategy', 'unknown')}

## GPU Cleanup
- Processes found: {result['cleanup']['processes_found']}
- Processes killed: {result['cleanup']['processes_killed']}

## Endpoints Started
{endpoints_text}

Press `e` to view the Evolution panel for monitoring.
""")

                    # Show evolution panel
                    self.action_show_evolution()

                except Exception as e:
                    content.show_file("error.txt", f"Error starting evolution: {e}")

            asyncio.create_task(start())

        elif subcmd == "stop":
            async def stop():
                try:
                    from .agents.evolution import get_evolution_daemon

                    # Stop simple daemon
                    daemon = get_evolution_daemon()
                    await daemon.stop()

                    # Also stop orchestrated evolution if running
                    try:
                        from .agents.evolution.orchestrated import get_orchestrated_evolution
                        orch_evo = get_orchestrated_evolution()
                        if orch_evo.running:
                            await orch_evo.stop()
                    except Exception:
                        pass  # Orchestrated evolution not available

                    content.show_file("evolve.md", "# Evolution\n\n**Status**: Stopped\n\nBoth simple and orchestrated evolution have been stopped.")

                except Exception as e:
                    content.show_file("error.txt", f"Error stopping evolution: {e}")

            asyncio.create_task(stop())

        elif subcmd == "status":
            try:
                from .agents.evolution import get_evolution_daemon

                daemon = get_evolution_daemon()
                status = daemon.get_status()

                config = status.get("config", {})
                parallel_info = ""
                if status.get("parallel"):
                    parallel_info = f"\n**Parallel Mode**: ✓ ({status.get('parallel_endpoints', 0)} endpoints)"
                content.show_file("evolve.md", f"""# Evolution Daemon Status

**Running**: {'✓ Yes' if status['running'] else '✗ No'}
**Enabled**: {'Yes' if status['enabled'] else 'No'}{parallel_info}
**Cycles Completed**: {status['cycles_completed']}
**Total Improvement**: {status.get('total_improvement_percent', 0):.1f}%
**Next Agent**: {status.get('next_agent', 'unknown')}

## Configuration

- **Strategy**: {config.get('strategy', 'unknown')}
- **Idle Threshold**: {config.get('idle_threshold', 0)}%
- **Max Cycles/Hour**: {config.get('max_cycles_per_hour', 0)}
- **Agents**: {', '.join(config.get('agents', []))}

---

Use `/evolve start` to start the daemon (single GPU).
Use `/evolve start --parallel` to start with 6 parallel GPUs.
Use `/evolve stop` to stop the daemon.
Press `e` to view the Evolution panel.
""")

            except Exception as e:
                content.show_file("error.txt", f"Error getting status: {e}")

        elif subcmd == "trigger":
            async def trigger():
                try:
                    from .agents.evolution import get_evolution_daemon

                    daemon = get_evolution_daemon()

                    if not daemon.running:
                        content.show_file("error.txt", "Daemon not running. Use `/evolve start` first.")
                        return

                    agent_id = subargs[0] if subargs else None
                    content.show_file("evolve.md", f"# Evolution Daemon\n\nTriggering cycle for {agent_id or 'next agent'}...")

                    result = await daemon.force_evolution_cycle(agent_id)

                    content.show_file("evolve.md", f"""# Evolution Cycle Result

**Agent**: {result.agent_id}
**Success**: {'✓' if result.success else '✗'}
**Improvement**: {result.improvement_percent:.1f}%

{f'**Error**: {result.error}' if result.error else ''}
""")

                except Exception as e:
                    content.show_file("error.txt", f"Error triggering cycle: {e}")

            asyncio.create_task(trigger())

        elif subcmd == "budget":
            try:
                from .models.tiered_evaluation import get_tiered_evaluator

                evaluator = get_tiered_evaluator()
                budget = evaluator.get_budget_status()

                content.show_file("evolve.md", f"""# XAI Evaluation Budget

## Daily Usage
- **Used**: {budget['daily_used']} / {budget['daily_limit']}
- **Remaining**: {budget['daily_remaining']}

## Weekly Usage
- **Used**: {budget['weekly_used']} / {budget['weekly_limit']}
- **Remaining**: {budget['weekly_remaining']}

## Status
- **XAI Available**: {'✓ Yes' if budget['xai_available'] else '✗ No (budget exhausted)'}
- **Total Tokens**: {budget['total_tokens']}

---

Budget resets daily at midnight UTC.
Use local evaluation for routine checks to conserve budget.
""")

            except Exception as e:
                content.show_file("error.txt", f"Error getting budget: {e}")

        elif subcmd == "orchestrated" or subcmd == "orch":
            # Start orchestrator-managed evolution
            content.show_file("evolve.md", """# Orchestrated Evolution

Starting **orchestrator-managed** evolution...

The Orchestrator model will:
- Observe GPU health, agent state, and cycle history
- Diagnose failures and adapt strategy
- Coordinate resources intelligently
- Maintain system health overnight

Phase 1: Starting orchestration endpoint...
""")

            async def start_orchestrated():
                try:
                    from .inference.manager import get_inference_manager
                    from .agents.evolution.orchestrated import get_orchestrated_evolution

                    # Use InferenceManager to check/ensure endpoint is available
                    # This discovers external processes (devenv, MCP, etc.)
                    manager = get_inference_manager()
                    status = await manager.get_status()

                    if not status.default_model_ready:
                        content.show_file("evolve.md", """# Orchestrated Evolution

Phase 1: Starting inference endpoint...
""")
                        # Try to ensure an endpoint is running
                        success = await manager.ensure_orchestrator_running()
                        if not success:
                            content.show_file("error.txt", "Failed to start inference endpoint for evolution.")
                            return
                        await asyncio.sleep(2)  # Brief wait for stability

                    # Start orchestrated evolution
                    content.show_file("evolve.md", """# Orchestrated Evolution

Phase 1: ✓ Inference endpoint ready
Phase 2: Starting orchestrator-managed evolution...
""")

                    orch_evo = get_orchestrated_evolution()
                    await orch_evo.start()

                    orch_status = orch_evo.get_status()

                    content.show_file("evolve.md", f"""# Orchestrated Evolution

**Status**: Running ✓
**Mode**: Orchestrator-managed (meta-cognitive)

The Orchestrator model is now managing evolution autonomously.
It will:
- Select which agents to optimize based on available examples
- Skip agents that fail repeatedly
- Adapt strategy based on outcomes
- Handle failures gracefully

## Session Info
- Started: {orch_status.get('session_start', 'now')}
- Cycles: {orch_status.get('cycles_completed', 0)}
- Improvement: {orch_status.get('total_improvement', 0):.1f}%

Press `e` to view the Evolution panel for monitoring.
Use `/evolve stop` to stop orchestrated evolution.
""")

                    # Show evolution panel
                    self.action_show_evolution()

                except Exception as e:
                    import traceback
                    content.show_file("error.txt", f"Error starting orchestrated evolution: {e}\n\n{traceback.format_exc()}")

            asyncio.create_task(start_orchestrated())

        else:
            content.show_file("error.txt", f"Unknown evolve subcommand: {subcmd}\n\nUsage:\n  /evolve                     - Start orchestrator-managed (default)\n  /evolve start [--parallel]  - Start simple daemon\n  /evolve stop\n  /evolve status\n  /evolve trigger [agent]\n  /evolve budget")

    def _handle_thoughts_command(self, args: str) -> None:
        """Handle /thoughts command for cognition.

        Usage:
            /thoughts           - Trigger cognition cycle and open new thought note
            /thoughts recent    - Open most recent thought note (no generation)
            /thoughts recent N  - Open Nth most recent thought note
            /thoughts self      - Trigger self-observation
            /thoughts audit     - Trigger engine audit
        """
        import asyncio

        content = self.query_one("#info-panel", InfoPanel)
        editor = self.query_one("#note-editor", NoteEditor)

        parts = args.split() if args else []
        subcmd = parts[0].lower() if parts else ""

        if subcmd == "recent" or subcmd == "":
            # Open most recent thought note (or Nth recent)
            scratch_path = Path(self.config.kb.scratch)
            n = 0  # Default to most recent (0-indexed)

            if subcmd == "recent" and len(parts) > 1:
                try:
                    n = int(parts[1]) - 1  # Convert 1-indexed to 0-indexed
                except ValueError:
                    pass

            thought_files = self._get_sorted_thought_files(scratch_path)

            if not thought_files:
                content.show_file("thoughts.md", "# No Thoughts Found\n\n*No thought notes found in scratch/.*\n\n*Use `/thoughts trigger` to generate thoughts.*")
                return

            if n >= len(thought_files):
                n = len(thought_files) - 1

            recent_thought = thought_files[n]

            try:
                # If no subcmd, trigger generation first
                if subcmd == "":
                    self._trigger_cognition_and_show(content, editor)
                else:
                    # Just show the recent thought
                    editor.remove_class("hidden")
                    editor.open_note(str(recent_thought))

                    rel_path = recent_thought.relative_to(scratch_path)
                    content.show_file(
                        "thoughts.md",
                        f"# Recent Thought\n\n"
                        f"**Showing:** `{rel_path}`\n"
                        f"**Position:** {n + 1} of {len(thought_files)}\n\n"
                        f"*Use `/thoughts recent N` to view older thoughts.*"
                    )

                    # Refresh file tree
                    file_tree = self.query_one("#file-tree", FileTree)
                    file_tree.refresh_tree()

            except Exception as e:
                content.show_file("error.txt", f"Error opening thought: {e}")

        elif subcmd == "trigger":
            # Explicitly trigger cognition
            self._trigger_cognition_and_show(content, editor)

        elif subcmd == "self":
            # Trigger self-observation via Engine gRPC
            content.show_file("thoughts.md", "# Self-Observation\n\n*Generating self-observation thoughts via Engine...*")

            async def run_self_observation():
                try:
                    from .client.grpc_client import get_grpc_client

                    client = await get_grpc_client()
                    if not client:
                        raise RuntimeError(
                            "Engine not available.\n"
                            "Guru Meditation: #COG.00000025.NOENGINE\n"
                            "Check: devenv processes up"
                        )

                    # Call SelfObservation via gRPC
                    result = await client.call(
                        "Cognition",
                        "self_observation",
                        {"max_observations": 5},
                        timeout=120.0,
                    )

                    observations_generated = result.get("observations_generated", 0)

                    if observations_generated > 0:
                        # Open the most recent thought note
                        scratch_path = Path(self.config.kb.scratch)
                        recent = self._find_most_recent_thought(scratch_path)
                        if recent:
                            editor.remove_class("hidden")
                            editor.open_note(str(recent))

                        content.show_file(
                            "thoughts.md",
                            f"# Self-Observation Complete\n\n"
                            f"**Generated:** {observations_generated} self-observation thoughts\n\n"
                            f"*Thoughts about own thought patterns have been recorded.*"
                        )

                        # Refresh ThinkPanel immediately
                        try:
                            think_panel = self.query_one("#think-panel", ThinkPanel)
                            await think_panel.refresh_now()
                        except Exception:
                            pass
                    else:
                        content.show_file("thoughts.md", "# Self-Observation\n\n*No new self-observations generated.*")

                except Exception as e:
                    content.show_file("error.txt", f"Self-observation failed: {e}")

            asyncio.create_task(run_self_observation())

        elif subcmd == "audit":
            # Trigger engine audit via Engine gRPC
            content.show_file("thoughts.md", "# Engine Audit\n\n*Auditing engine health via Engine...*")

            async def run_audit():
                try:
                    from .client.grpc_client import get_grpc_client

                    client = await get_grpc_client()
                    if not client:
                        raise RuntimeError(
                            "Engine not available.\n"
                            "Guru Meditation: #COG.00000026.NOENGINE\n"
                            "Check: devenv processes up"
                        )

                    # Call EngineAudit via gRPC
                    result = await client.call(
                        "Cognition",
                        "engine_audit",
                        {"include_metrics": True},
                        timeout=120.0,
                    )

                    observations_recorded = result.get("observations_recorded", 0)
                    anomalies_found = result.get("anomalies_found", 0)

                    if observations_recorded > 0:
                        # Open the most recent thought note
                        scratch_path = Path(self.config.kb.scratch)
                        recent = self._find_most_recent_thought(scratch_path)
                        if recent:
                            editor.remove_class("hidden")
                            editor.open_note(str(recent))

                        content.show_file(
                            "thoughts.md",
                            f"# Engine Audit Complete\n\n"
                            f"**Observations:** {observations_recorded}\n"
                            f"**Anomalies:** {anomalies_found}\n\n"
                            f"*Engine health observations have been recorded.*"
                        )

                        # Refresh ThinkPanel immediately
                        try:
                            think_panel = self.query_one("#think-panel", ThinkPanel)
                            await think_panel.refresh_now()
                        except Exception:
                            pass
                    else:
                        content.show_file("thoughts.md", "# Engine Audit\n\n*No audit observations generated.*")

                except Exception as e:
                    content.show_file("error.txt", f"Engine audit failed: {e}")

            asyncio.create_task(run_audit())

        else:
            content.show_file("error.txt", f"Unknown thoughts subcommand: {subcmd}\n\nUsage:\n  /thoughts          - Trigger cognition and show thoughts\n  /thoughts recent   - Show most recent thought\n  /thoughts self     - Trigger self-observation\n  /thoughts audit    - Trigger engine audit")

    def _trigger_cognition_and_show(self, content: "InfoPanel", editor: "NoteEditor") -> None:
        """Trigger a cognition cycle via Engine gRPC and show the resulting thought note.

        Uses gRPC to route through the Engine (L3) rather than calling the L5 agent
        directly. This ensures all inference is properly managed by the Engine.
        """
        import asyncio

        content.show_file("thoughts.md", "# Cognition\n\n*Generating thoughts via Engine...*")

        async def run_cognition():
            try:
                from .client.grpc_client import get_grpc_client

                client = await get_grpc_client()
                if not client:
                    raise RuntimeError(
                        "Engine not available.\n"
                        "Guru Meditation: #COG.00000017.NOENGINE\n"
                        "Check: devenv processes up"
                    )

                # Call TriggerCognition via gRPC (routes to cognition_logic.py)
                max_thoughts = getattr(self.config.cognition, "greeting_thoughts", 5)
                result = await client.call(
                    "Cognition",
                    "trigger",
                    {"max_thoughts": max_thoughts, "trigger_reason": "manual"},
                    timeout=120.0,
                )

                # Open the thought note using kb_path from gRPC response
                kb_path = result.get("kb_path", "")
                if kb_path:
                    # kb_path is relative to KB root (e.g. "scratch/2025-12-31/...")
                    kb_root = Path(self.config.kb.root)
                    full_path = kb_root / kb_path
                    if full_path.exists():
                        editor.remove_class("hidden")
                        editor.open_note(str(full_path))

                        # Refresh file tree
                        file_tree = self.query_one("#file-tree", FileTree)
                        file_tree.refresh_tree()

                # Parse results from gRPC response
                thoughts_generated = result.get("thoughts_generated", 0)
                patterns = result.get("patterns_detected", 0)
                connections = result.get("connections_found", 0)
                curiosities = result.get("curiosities_generated", 0)
                self_obs = result.get("self_observations", 0)

                tokens_out = result.get("tokens_out", 0)
                content.show_file(
                    "thoughts.md",
                    f"# Cognition Complete\n\n"
                    f"**Generated:** {thoughts_generated} thoughts ({tokens_out} tokens)\n"
                    f"- Patterns: {patterns}\n"
                    f"- Connections: {connections}\n"
                    f"- Curiosities: {curiosities}\n"
                    f"- Self-observations: {self_obs}\n"
                    + (f"\n**Saved:** `{kb_path}`" if kb_path else "")
                )

                # Refresh ThinkPanel immediately so new thoughts appear
                try:
                    think_panel = self.query_one("#think-panel", ThinkPanel)
                    await think_panel.refresh_now()
                except Exception:
                    pass  # Panel may not exist in all layouts

            except Exception as e:
                content.show_file("error.txt", f"Cognition failed: {e}")

        asyncio.create_task(run_cognition())

    def _get_sorted_thought_files(self, scratch_path: Path) -> list[Path]:
        """Get all thought files sorted by modification time (newest first)."""
        if not scratch_path.exists():
            return []

        thought_files = []
        thought_files.extend(scratch_path.rglob("*_thought_*.md"))
        thought_files.extend(scratch_path.rglob("*_thoughts.md"))

        thought_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return thought_files

    def _handle_health_command(self, args: str) -> None:
        """Handle /health command for comprehensive system diagnostics.

        Usage:
            /health           - Run full health check
            /health quick     - Run critical checks only
            /health engine    - Check engine/gRPC health
            /health data      - Check database/KB health
            /health cognition - Check cognition daemon
            /health inference - Check inference endpoints
        """
        import asyncio
        from pathlib import Path

        from .health import HealthChecker, CheckStatus, CheckResult

        content = self.query_one("#info-panel", InfoPanel)

        parts = args.split() if args else []
        subcmd = parts[0].lower() if parts else ""

        # Determine title and check_type based on subcmd (matches CLI pattern)
        if subcmd == "quick":
            title = "Quick Health Check"
            check_type = "quick"
        elif subcmd in ("engine", "data", "cognition", "inference"):
            title = f"{subcmd.title()} Health Check"
            check_type = subcmd
        else:
            title = "System Health Check"
            check_type = "full"

        # Show initial status
        content.show_file("health.md", f"# {title}\n\n*Starting diagnostics...*")

        async def run_health_check():
            try:
                import time

                kb_root = Path(self.config.kb.root) if hasattr(self.config.kb, "root") else Path("build/dev")
                checker = HealthChecker(kb_root)

                # Progress tracking for info panel updates
                completed_checks: list[CheckResult] = []
                last_update = 0.0
                UPDATE_INTERVAL = 0.2  # Max 5 updates/sec to keep TUI responsive

                # Status indicators for compact display
                status_icons = {
                    CheckStatus.PASS: "[OK]",
                    CheckStatus.WARN: "[!]",
                    CheckStatus.FAIL: "[X]",
                    CheckStatus.SKIP: "[-]",
                }

                async def on_progress(result: CheckResult, completed: int, total: int) -> None:
                    nonlocal last_update
                    completed_checks.append(result)

                    now = time.monotonic()
                    if now - last_update >= UPDATE_INTERVAL:
                        # Build compact progress display
                        lines = [
                            f"# {title}",
                            "",
                            f"*Checking {completed}/{total}...*",
                            "",
                        ]

                        # Show last 6 completed checks (compact - fits in ~2/3 panel)
                        for check in completed_checks[-6:]:
                            icon = status_icons.get(check.status, "[?]")
                            lines.append(f"{icon} {check.name}")

                        content.show_file("health.md", "\n".join(lines))
                        last_update = now
                        await asyncio.sleep(0)  # Yield to TUI event loop

                # Run appropriate checks with progress callback
                if subcmd == "quick":
                    report = await checker.run_quick(progress_callback=on_progress)
                elif subcmd in ("engine", "data", "cognition", "inference"):
                    report = await checker.run_category(subcmd, progress_callback=on_progress)
                else:
                    report = await checker.run_all(progress_callback=on_progress)

                # Show compact completion summary in info panel
                summary_lines = [
                    f"# {title}",
                    "",
                    f"{report.status_indicator} {report.passed}/{len(report.checks)} passed",
                    "",
                    f"Duration: {report.duration_ms}ms",
                    f"Data points: {len(report.checks)} checks",
                    "",
                ]

                # Add warning/failure count if any
                if report.warnings > 0 or report.failures > 0:
                    issues = []
                    if report.warnings > 0:
                        issues.append(f"{report.warnings} warnings")
                    if report.failures > 0:
                        issues.append(f"{report.failures} failures")
                    summary_lines.append(f"Issues: {', '.join(issues)}")
                    summary_lines.append("")

                summary_lines.append("*Report saved to editor*")

                content.show_file("health.md", "\n".join(summary_lines))

                # Format full report for saved file
                lines = [
                    f"# {title}",
                    "",
                    report.summary(),
                    "",
                    f"*Completed in {report.duration_ms}ms at {report.timestamp.strftime('%H:%M:%S')}*",
                    "",
                ]

                # Fetch and display active incidents prominently at the top
                try:
                    from .client.engine_proxy import use_engine_proxy
                    from .client.grpc_client import get_grpc_client

                    if use_engine_proxy():
                        client = await get_grpc_client()
                        incidents_result = await client.call(
                            "HealthObserver", "incidents", {"status": "active"}, timeout=5.0
                        )
                        incidents = incidents_result.get("incidents", [])

                        if incidents:
                            # Get GitHub repo for issue links
                            try:
                                observer_status = await client.call(
                                    "HealthObserver", "status", {}, timeout=5.0
                                )
                                github_repo = observer_status.get("github_repo", "")
                            except Exception:
                                github_repo = ""

                            lines.extend([
                                "## Active Incidents",
                                "",
                                f"**{len(incidents)} incident(s) require attention:**",
                                "",
                            ])

                            for inc in incidents:
                                fingerprint = inc.get("fingerprint", "unknown")
                                endpoint = inc.get("endpoint", "unknown")
                                failure_mode = inc.get("failure_mode_id", "unknown")
                                status = inc.get("status", "active")
                                rpn = inc.get("rpn_score", 0)
                                created_at = inc.get("created_at", "")
                                github_issue = inc.get("github_issue", 0)
                                attempts = inc.get("attempts", 0)

                                # Status icon (matching health check style)
                                incident_status_icons = {
                                    "active": "[X]",
                                    "healing": "[~]",
                                    "recovering": "[+]",
                                    "manual_required": "[!]",
                                }
                                icon = incident_status_icons.get(status, "[?]")

                                # Format incident entry
                                lines.append(f"### {icon} {fingerprint}")
                                lines.append("")
                                lines.append(f"- **Endpoint:** `{endpoint}`")
                                lines.append(f"- **Failure Mode:** `{failure_mode}`")
                                lines.append(f"- **Status:** {status}")
                                lines.append(f"- **RPN Score:** {rpn}")
                                lines.append(f"- **Attempts:** {attempts}")

                                # Format created_at timestamp
                                if created_at:
                                    try:
                                        from datetime import datetime as dt
                                        created = dt.fromisoformat(created_at.replace("Z", "+00:00"))
                                        age = dt.now(created.tzinfo) - created if created.tzinfo else dt.now() - created
                                        age_hours = age.total_seconds() / 3600
                                        if age_hours < 1:
                                            age_str = f"{int(age.total_seconds() / 60)} minutes"
                                        elif age_hours < 24:
                                            age_str = f"{age_hours:.1f} hours"
                                        else:
                                            age_str = f"{age_hours / 24:.1f} days"
                                        lines.append(f"- **Age:** {age_str}")
                                    except (ValueError, TypeError):
                                        lines.append(f"- **Created:** {created_at}")

                                # Add GitHub issue link if available
                                if github_issue and github_issue > 0:
                                    if github_repo:
                                        # Handle on-prem GitHub (github.example.com/org/repo)
                                        if "/" in github_repo and "." in github_repo.split("/")[0]:
                                            # Full URL format: github.example.com/org/repo
                                            issue_url = f"https://{github_repo}/issues/{github_issue}"
                                        else:
                                            # Standard GitHub: org/repo
                                            issue_url = f"https://github.com/{github_repo}/issues/{github_issue}"
                                        lines.append(f"- **GitHub Issue:** [#{github_issue}]({issue_url})")
                                    else:
                                        lines.append(f"- **GitHub Issue:** #{github_issue}")

                                lines.append("")

                            lines.append("---")
                            lines.append("")

                except Exception as e:
                    # Log but don't fail the health report - record via OTel for observability
                    import logging
                    logging.getLogger(__name__).debug(f"Failed to fetch incidents: {e}")
                    try:
                        from .core.telemetry import get_tracer
                        tracer = get_tracer()
                        with tracer.start_as_current_span("health.fetch_incidents.error") as span:
                            span.set_attribute("error.type", type(e).__name__)
                            span.set_attribute("error.message", str(e))
                            span.record_exception(e)
                    except Exception:
                        pass  # Don't fail on telemetry errors

                lines.extend([
                    "## Check Results",
                    "",
                ])

                for check in report.checks:
                    icon = status_icons.get(check.status, "[?]")
                    line = f"{icon} **{check.name}**: {check.message}"
                    lines.append(line)

                    # Show details for non-passing checks
                    if check.status != CheckStatus.PASS and check.details:
                        for key, value in check.details.items():
                            if not isinstance(value, (list, dict)) or len(str(value)) < 50:
                                lines.append(f"   - {key}: `{value}`")

                # Add interventions section
                if report.interventions:
                    lines.extend([
                        "",
                        "## Suggested Interventions",
                        "",
                    ])
                    for i, intervention in enumerate(report.interventions, 1):
                        lines.append(f"{i}. {intervention}")

                # Add metrics if available
                if report.metrics:
                    lines.extend([
                        "",
                        "## Metrics",
                        "",
                    ])
                    for key, value in report.metrics.items():
                        lines.append(f"- **{key}**: {value}")

                # Usage hint
                lines.extend([
                    "",
                    "---",
                    "*Commands: `/health`, `/health quick`, `/health <category>`*",
                    "*Categories: engine, data, cognition, inference*",
                ])

                self._show_output(f"health_{check_type}", "\n".join(lines))

                # Refresh ThinkPanel to show any updates
                try:
                    think_panel = self.query_one("#think-panel", ThinkPanel)
                    await think_panel.refresh_now()
                except Exception:
                    pass

            except Exception as e:
                import traceback
                content.show_file("error.txt", f"Health check failed: {e}\n\n{traceback.format_exc()}")

        asyncio.create_task(run_health_check())

    def _handle_ambient_command(self, args: str) -> None:
        """Handle /ambient command for ambient computing cycles.

        Usage:
            /ambient                         - Show status (if no --cycle) or start
            /ambient start                   - Start continuous cycling daemon
            /ambient start --cycle 4         - Run exactly 4 cycles then stop
            /ambient start --baseline-only   - Skip reasoning phases
            /ambient --cycle 4               - Same as start --cycle 4 (start implied)
            /ambient stop                    - Stop daemon gracefully
            /ambient status                  - Show daemon status
            /ambient cycle                   - (Legacy) Run single cycle
        """
        import asyncio

        content = self.query_one("#info-panel", InfoPanel)

        parts = args.split() if args else []

        # Parse --cycle N option
        max_cycles = None
        if "--cycle" in parts:
            idx = parts.index("--cycle")
            if idx + 1 < len(parts):
                try:
                    max_cycles = int(parts[idx + 1])
                    parts = [p for i, p in enumerate(parts) if i not in (idx, idx + 1)]
                except ValueError:
                    content.show_file(
                        "error.txt",
                        f"Invalid --cycle value: {parts[idx + 1]}\n\n"
                        "Usage: /ambient --cycle 4"
                    )
                    return

        baseline_only = "--baseline-only" in parts
        parts = [p for p in parts if p != "--baseline-only"]

        # Determine subcommand - if --cycle given, default to start
        if max_cycles:
            subcmd = parts[0].lower() if parts else "start"
        else:
            subcmd = parts[0].lower() if parts else "status"

        if subcmd == "start" or max_cycles:
            self._run_ambient_start(content, baseline_only, max_cycles)
        elif subcmd == "stop":
            self._run_ambient_stop(content)
        elif subcmd == "status":
            self._run_ambient_status(content)
        elif subcmd == "cycle":
            # Legacy single-shot cycle
            self._run_ambient_cycle(content, baseline_only)
        elif subcmd == "buffer":
            self._run_ambient_buffer(content)
        else:
            content.show_file(
                "error.txt",
                f"Unknown ambient subcommand: {subcmd}\n\n"
                "Usage:\n"
                "  /ambient start               - Start continuous cycling\n"
                "  /ambient start --cycle 4     - Run 4 cycles then stop\n"
                "  /ambient start --baseline-only - Skip reasoning\n"
                "  /ambient stop                - Stop gracefully\n"
                "  /ambient status              - Show status\n"
                "  /ambient buffer              - Export buffer to zettelkasten\n"
                "  /ambient cycle               - (Legacy) Single cycle"
            )

    def _run_ambient_start(
        self,
        content: "InfoPanel",
        baseline_only: bool = False,
        max_cycles: int | None = None,
    ) -> None:
        """Start ambient cycling daemon and subscribe to events.

        Fire and forget - starts the daemon and attaches InfoPanel to event stream.
        """
        import asyncio
        import time

        # Show initial status
        mode = "baseline-only" if baseline_only else "full"
        cycles_text = f" ({max_cycles} cycles)" if max_cycles else " (continuous)"
        content.show_file("ambient.md", f"# Ambient Cycle\n\n*Starting {mode}{cycles_text}...*")

        async def start_and_subscribe():
            try:
                from .client.grpc_client import get_grpc_client

                client = await get_grpc_client()

                # Start daemon (fire-and-forget)
                result = await client.call("Ambient", "start", {
                    "baseline_only": baseline_only,
                    "max_cycles": max_cycles or 0,
                })

                if not result.get("success"):
                    # Already running - just re-subscribe
                    pass

                # Subscribe to event stream
                lines = ["# Ambient Cycle"]
                if max_cycles:
                    lines.append(f"*{max_cycles} cycles*")
                lines.append("")

                last_update = 0.0
                UPDATE_INTERVAL = 0.2

                async for event in client.ambient_subscribe_stream():
                    phase = event.get("phase", "").replace("AMBIENT_PHASE_", "")
                    message = event.get("message", "")
                    progress = event.get("progress", 0.0)
                    metrics = event.get("metrics", {})
                    daemon_cycle = metrics.get("daemon_cycle", "")

                    # Update cycle header if new cycle started
                    if phase == "BASELINE_HEALTH" and progress == 0.0 and daemon_cycle:
                        # Clear old lines for new cycle, keep header
                        lines = ["# Ambient Cycle", f"*Cycle {daemon_cycle}*", ""]

                    # Handle COMPLETE with "Completed" - final message
                    if phase == "COMPLETE" and "Completed" in message:
                        lines.append("")
                        lines.append(f"✓ {message}")
                        content.show_file("ambient.md", "\n".join(lines))
                        break

                    # Handle COMPLETE with cooldown
                    if phase == "COMPLETE" and "Next cycle" in message:
                        lines.append(f"⏳ {message}")

                    # Regular phase progress
                    elif progress >= 1.0:
                        lines.append(f"✓ **{phase}**: {message}")
                        if metrics and phase != "COMPLETE":
                            for key, value in metrics.items():
                                if key not in ("daemon_cycle", "cooldown_s"):
                                    lines.append(f"  - {key}: {value}")

                    # Debounced UI updates
                    now = time.monotonic()
                    if now - last_update >= UPDATE_INTERVAL:
                        display_lines = lines[-15:]  # Last 15 lines
                        if progress < 1.0 and phase not in ("COMPLETE",):
                            display_lines.append(f"\n*{phase}: {message}...*")
                        content.show_file("ambient.md", "\n".join(display_lines))
                        last_update = now
                        await asyncio.sleep(0)

            except Exception as e:
                import traceback
                content.show_file("error.txt", f"Ambient start failed: {e}\n\n{traceback.format_exc()}")

        asyncio.create_task(start_and_subscribe())

    def _run_ambient_stop(self, content: "InfoPanel") -> None:
        """Stop ambient daemon and show summary."""
        import asyncio

        content.show_file("ambient.md", "# Ambient Cycle\n\n*Stopping...*")

        async def stop_daemon():
            try:
                from .client.grpc_client import get_grpc_client

                client = await get_grpc_client()
                result = await client.call("Ambient", "stop", {})

                if result.get("success"):
                    cycles = result.get("cycles_completed", 0)
                    tasks = result.get("total_tasks", 0)
                    successful = result.get("successful_tasks", 0)
                    message = result.get("message", "Stopped")
                    # Chrome-free format with trailing spaces for line breaks
                    stop_lines = [
                        "# Ambient Cycle",
                        "",
                        f"✓ {message}",
                        "",
                        f"Cycles     {cycles}  ",
                        f"Tasks      {tasks}  ",
                        f"Successful {successful}",
                    ]
                    content.show_file("ambient.md", "\n".join(stop_lines))
                else:
                    content.show_file("ambient.md", f"""# Ambient Cycle

{result.get('message', 'Not running')}

*Use `/ambient start` to begin cycling.*
""")

            except Exception as e:
                import traceback
                content.show_file("error.txt", f"Ambient stop failed: {e}\n\n{traceback.format_exc()}")

        asyncio.create_task(stop_daemon())

    def _run_ambient_cycle(self, content: "InfoPanel", skip_reasoning: bool = False) -> None:
        """Run ambient computing cycle with streaming progress (legacy single-shot).

        Uses debounced updates to prevent blocking the TUI event loop.
        Updates at most every 200ms to keep UI responsive while showing progress.
        """
        import asyncio
        import time

        # Show initial status
        mode = "baseline-only" if skip_reasoning else "full"
        content.show_file("ambient.md", f"# Ambient Computing\n\n*Starting {mode} cycle...*")

        async def run_cycle():
            try:
                from .client.grpc_client import get_grpc_client

                think_panel = self.query_one("#think-panel", ThinkPanel)

                client = await get_grpc_client()
                lines = [f"# Ambient Cycle ({mode})"]
                completed_phases = []
                last_update = 0.0
                UPDATE_INTERVAL = 0.2  # Max 5 updates/sec to keep TUI responsive

                async for event in client.ambient_cycle_stream(
                    skip_reasoning=skip_reasoning,
                    baseline_task_count=1,
                ):
                    # Extract event data
                    phase = event.get("phase", "").replace("AMBIENT_PHASE_", "")
                    message = event.get("message", "")
                    progress = event.get("progress", 0.0)
                    metrics = event.get("metrics", {})

                    # Track completed phases
                    if progress >= 1.0 and phase not in completed_phases:
                        completed_phases.append(phase)
                        lines.append(f"✓ **{phase}**: {message}")

                        # Add metrics if present
                        if metrics:
                            for key, value in metrics.items():
                                lines.append(f"  - {key}: {value}")

                    # Debounce UI updates to prevent blocking TUI event loop
                    now = time.monotonic()
                    if now - last_update >= UPDATE_INTERVAL:
                        progress_text = "\n".join(lines)
                        if progress < 1.0:
                            progress_text += f"\n\n*In progress: {phase} ({progress:.0%})...*"
                        content.show_file("ambient.md", progress_text)
                        last_update = now
                        await asyncio.sleep(0)  # Yield control to TUI event loop

                # Final summary
                lines.append("")
                lines.append("---")
                lines.append(f"*Completed {len(completed_phases)} phases*")
                content.show_file("ambient.md", "\n".join(lines))

                # Refresh ThinkPanel
                try:
                    await think_panel.refresh_now()
                except Exception:
                    pass

            except Exception as e:
                import traceback
                content.show_file("error.txt", f"Ambient cycle failed: {e}\n\n{traceback.format_exc()}")

        asyncio.create_task(run_cycle())

    def _run_ambient_buffer(self, content: "InfoPanel") -> None:
        """Export ambient buffer to zettelkasten file and open in Editor Panel."""
        import asyncio
        from pathlib import Path

        content.show_file("ambient.md", "# Buffer Export\n\n*Exporting buffer...*")

        async def export_buffer():
            try:
                from .client.grpc_client import get_grpc_client
                from .widgets.note_editor import NoteEditor

                client = await get_grpc_client()
                result = await client.call("Ambient", "buffer_export", {"kb_root": "build/dev"})

                if result.get("error"):
                    content.show_file("error.txt", f"Buffer export failed: {result.get('error')}")
                    return

                path = result.get("path", "")
                entry_count = result.get("entry_count", 0)
                total_bytes = result.get("total_bytes", 0)

                if not path:
                    content.show_file("ambient.md", "# Buffer Export\n\n*Buffer is empty.*")
                    return

                full_path = Path("build/dev") / path

                # Show status in InfoPanel (same style as /ambient status)
                nbsp = "\u00a0"
                lines = [
                    "# Buffer Export",
                    "",
                    f"Path{nbsp * 7}{path}  ",
                    f"Entries{nbsp * 4}{entry_count}  ",
                    f"Size{nbsp * 7}{total_bytes:,} bytes  ",
                    "",
                    "---",
                    "",
                    "`/ambient start`  ",
                    "`/ambient stop`  ",
                    "`/ambient status`  ",
                    "`/ambient buffer`",
                ]
                content.show_file("ambient.md", "\n".join(lines))

                # Open the exported file in the Editor Panel
                if full_path.exists():
                    editor = self.query_one("#note-editor", NoteEditor)
                    editor.remove_class("hidden")
                    editor.open_note(str(full_path))

            except Exception as e:
                import traceback
                content.show_file("error.txt", f"Buffer export failed: {e}\n\n{traceback.format_exc()}")

        asyncio.create_task(export_buffer())

    def _run_ambient_status(self, content: "InfoPanel") -> None:
        """Show ambient computing status with live updates when daemon is running."""
        import asyncio
        import time

        content.show_file("ambient.md", "# Ambient Status\n\n*Fetching...*")

        async def get_status_and_subscribe():
            try:
                from .client.grpc_client import get_grpc_client
                from datetime import datetime as dt

                client = await get_grpc_client()
                status = await client.call("Ambient", "status", {})

                daemon_running = status.get("daemon_running", False)

                def fmt_time_ms(ms: int) -> str:
                    if not ms or ms == 0:
                        return "--:--"
                    try:
                        return dt.fromtimestamp(ms / 1000).strftime("%H:%M")
                    except Exception:
                        return "--:--"

                def format_status_display(status: dict, phase_override: str | None = None, message: str | None = None) -> str:
                    """Format status dict into display string."""
                    running = status.get("daemon_running", False)
                    current_cycle = status.get("current_cycle", 0)
                    max_cycles = status.get("max_cycles", 0)
                    current_phase = phase_override or status.get("current_phase", "idle")
                    cycles_completed = status.get("cycles_completed", 0)
                    baseline_endpoints = status.get("baseline_endpoints", [])
                    daemon_started_at_ms = status.get("daemon_started_at", 0)
                    daemon_stopped_at_ms = status.get("daemon_stopped_at", 0)

                    started_str = fmt_time_ms(daemon_started_at_ms)
                    stopped_str = fmt_time_ms(daemon_stopped_at_ms) if not running else "--:--"

                    if running:
                        mode = "RUNNING"
                        if max_cycles:
                            cycle_str = f"{current_cycle}/{max_cycles}"
                        else:
                            cycle_str = f"{current_cycle}"
                    else:
                        mode = "STOPPED"
                        cycle_str = str(cycles_completed)

                    phase_str = current_phase.split('_')[-1] if current_phase else 'UNKNOWN'

                    # Format endpoints
                    nbsp = "\u00a0"
                    if baseline_endpoints:
                        indent = nbsp * 11
                        endpoints_lines = []
                        for i, ep in enumerate(baseline_endpoints):
                            if i == 0:
                                endpoints_lines.append(f"Endpoints{nbsp}{nbsp}{ep}")
                            else:
                                endpoints_lines.append(f"{indent}{ep}")
                        endpoints_block = "  \n".join(endpoints_lines)
                    else:
                        endpoints_block = "Endpoints  NONE"

                    lines = [
                        "# Ambient Cycle",
                        "",
                        f"Started    {started_str}  ",
                        f"Stopped    {stopped_str}",
                        "",
                        "---",
                        "",
                        f"Daemon     {mode}  ",
                        f"Phase      {phase_str}  ",
                        f"Cycles     {cycles_completed}  ",
                        endpoints_block,
                    ]

                    # Add live message if provided
                    if message and running:
                        lines.extend(["", f"*{message}*"])

                    lines.extend([
                        "",
                        "---",
                        "`/ambient start`  ",
                        "`/ambient stop`  ",
                        "`/ambient status`  ",
                        "`/ambient buffer`",
                    ])

                    return "\n".join(lines)

                # Show initial status
                content.show_file("ambient.md", format_status_display(status))

                # If daemon is running, subscribe to event stream for live updates
                if daemon_running:
                    last_update = 0.0
                    UPDATE_INTERVAL = 0.5  # Update every 500ms max

                    async for event in client.ambient_subscribe_stream():
                        phase = event.get("phase", "").replace("AMBIENT_PHASE_", "")
                        message = event.get("message", "")
                        metrics = event.get("metrics", {})

                        # Update status with current cycle info from metrics
                        if metrics.get("daemon_cycle"):
                            status["current_cycle"] = int(metrics["daemon_cycle"])
                        if metrics.get("cycles_completed"):
                            status["cycles_completed"] = int(metrics["cycles_completed"])
                        status["current_phase"] = f"AMBIENT_PHASE_{phase}"

                        # Handle daemon stopped
                        if phase == "COMPLETE" and "Completed" in message:
                            status["daemon_running"] = False
                            content.show_file("ambient.md", format_status_display(status))
                            break

                        # Debounced UI updates
                        now = time.monotonic()
                        if now - last_update >= UPDATE_INTERVAL:
                            content.show_file("ambient.md", format_status_display(status, phase, message))
                            last_update = now
                            await asyncio.sleep(0)

            except Exception as e:
                content.show_file("error.txt", f"Failed to get ambient status: {e}")

        asyncio.create_task(get_status_and_subscribe())

    def _handle_x_bookmarks_command(self, args: str) -> None:
        """Handle /x-bookmarks command for X bookmarks sync.

        Usage:
            /x-bookmarks sync     - Trigger sync (Iceberg + work queue)
            /x-bookmarks status   - Show sync status
            /x-bookmarks auth     - Show auth status or start auth flow
        """
        import asyncio

        content = self.query_one("#info-panel", InfoPanel)

        parts = args.strip().split(maxsplit=1)
        subcommand = parts[0] if parts else "status"

        if subcommand == "sync":
            self._x_bookmarks_sync(content)
        elif subcommand == "status":
            self._x_bookmarks_status(content)
        elif subcommand == "auth":
            self._x_bookmarks_auth(content, parts[1] if len(parts) > 1 else "")
        else:
            content.show_file("x-bookmarks.md", f"""# X Bookmarks

Unknown subcommand: {subcommand}

**Usage:**
- `/x-bookmarks sync` - Sync bookmarks to Iceberg and KB work queue
- `/x-bookmarks status` - Show sync status and token info
- `/x-bookmarks auth` - Start OAuth flow (shows QR code)
- `/x-bookmarks auth complete <code>` - Complete OAuth with callback code
- `/xb` - Shortcut alias
""")

    def _x_bookmarks_sync(self, content: "InfoPanel") -> None:
        """Execute bookmarks sync via gRPC."""
        import asyncio

        content.show_file("x-bookmarks.md", "# X Bookmarks Sync\n\nStarting sync...")

        async def do_sync():
            try:
                from .client.grpc_client import get_grpc_client

                client = await get_grpc_client()
                result = await client.call("XBookmarks", "trigger_sync", {})

                # Check for action required
                if result.get("action_required"):
                    output = f"""# X Bookmarks Sync

**Status:** {result.get('status', 'unknown')}
**Action Required:** {result.get('action_required')}

{result.get('guidance_message', '')}

{result.get('message', '')}
"""
                    content.show_file("x-bookmarks.md", output)
                    return

                # Format success result
                output = f"""# X Bookmarks Sync Complete

| Metric | Value |
|--------|-------|
| Status | {result.get('status', 'unknown')} |
| Bookmarks fetched | {result.get('bookmarks_fetched', 0)} |
| Written to Iceberg | {result.get('iceberg_written', 0)} |
| KB work queue items | {result.get('queue_items', 0)} |

{result.get('message', '')}
"""
                content.show_file("x-bookmarks.md", output)

            except Exception as e:
                content.show_file("x-bookmarks.md", f"# Sync Error\n\n{e}")

        asyncio.create_task(do_sync())

    def _x_bookmarks_status(self, content: "InfoPanel") -> None:
        """Show bookmarks sync status via gRPC."""
        import asyncio

        content.show_file("x-bookmarks.md", "# X Bookmarks Status\n\nFetching...")

        async def do_status():
            try:
                from .client.grpc_client import get_grpc_client

                client = await get_grpc_client()
                result = await client.call("XBookmarks", "sync_status", {})

                # Check for guidance message
                guidance = ""
                if result.get("action_required"):
                    guidance = f"\n**Action Required:** {result.get('action_required')}\n\n{result.get('message', '')}\n"

                output = f"""# X Bookmarks Status

| Field | Value |
|-------|-------|
| Configured | {'Yes' if result.get('configured') else 'No'} |
| User | @{result.get('username', 'N/A')} |
| Token Status | {result.get('token_status', 'N/A')} |
| Folders | {result.get('folder_count', 0)} |
| Bookmarks | {result.get('bookmark_count', 0)} |
| Queued Requests | {result.get('queued_requests', 0)} |
| Last Sync | {result.get('last_sync_at', 'Never')} |
{guidance}
"""
                content.show_file("x-bookmarks.md", output)

            except Exception as e:
                content.show_file("x-bookmarks.md", f"# Status Error\n\n{e}")

        asyncio.create_task(do_status())

    def _x_bookmarks_auth(self, content: "InfoPanel", args: str) -> None:
        """Show auth status or initiate OAuth flow via gRPC.

        Usage:
            /x-bookmarks auth              - Start OAuth flow (shows QR code)
            /x-bookmarks auth complete <code> - Complete OAuth with callback code
        """
        import asyncio

        # Check for 'complete' subcommand
        parts = args.strip().split(maxsplit=1)
        if parts and parts[0] == "complete":
            code = parts[1] if len(parts) > 1 else ""
            self._x_bookmarks_auth_complete(content, code)
            return

        content.show_file("x-bookmarks.md", "# X Bookmarks Auth\n\nStarting OAuth flow...")

        # Keep reference to self for use in async function
        app = self

        async def do_auth():
            try:
                from .client.grpc_client import get_grpc_client
                import urllib.parse

                client = await get_grpc_client()
                result = await client.call("XBookmarks", "get_auth_url", {})

                if "error" in result:
                    content.show_file("x-bookmarks.md", f"# Auth Error\n\n{result['error']}")
                    return

                auth_url = result.get("auth_url", "")

                # Extract redirect_uri from auth_url for display
                parsed = urllib.parse.urlparse(auth_url)
                params = urllib.parse.parse_qs(parsed.query)
                redirect_uri = params.get('redirect_uri', [''])[0]
                is_localhost = "localhost" in redirect_uri or "127.0.0.1" in redirect_uri

                if is_localhost:
                    callback_instructions = """3. After clicking 'Authorize', X will redirect to localhost.
   The page will fail to load, but that's OK!

   Look at your browser's address bar - it will show:
   `http://localhost:8765/callback?code=XXXXX&state=YYYYY`

   Copy the value after `code=` (up to the & or end of URL)."""
                else:
                    callback_instructions = "3. After authorization, copy the code from the callback page."

                output = f"""# X Bookmarks OAuth Authentication

**1. Open this URL in your browser:**

```
{auth_url}
```

**2. Log in to X and authorize Gaius**

**{callback_instructions}**

**4. Complete authentication:**

Run: `/x-bookmarks auth complete <YOUR_CODE>`

---

**Note:** Authorization expires in 10 minutes.

**Callback:** `{redirect_uri}`

**Troubleshooting:**
- "You weren't able to give access": Your X app needs OAuth 2.0 configured.
  Go to https://developer.x.com/en/portal/dashboard
- `bookmark.read` requires X API Pro tier or higher.
"""
                content.show_file("x-bookmarks.md", output)

                # Show a QR code modal for easy scanning on mobile devices
                app.push_screen(QRCodeModal(
                    title="X OAuth Authorization URL",
                    url=auth_url,
                ))

            except Exception as e:
                content.show_file("x-bookmarks.md", f"# Auth Error\n\n{e}")

        asyncio.create_task(do_auth())

    def _x_bookmarks_auth_complete(self, content: "InfoPanel", code: str) -> None:
        """Complete OAuth flow with authorization code."""
        import asyncio

        if not code:
            content.show_file("x-bookmarks.md", """# X Bookmarks Auth Complete

**Error:** Missing authorization code.

**Usage:** `/x-bookmarks auth complete <YOUR_CODE>`

The code is provided after you authorize Gaius in your browser.
Copy it from the callback page or URL bar.
""")
            return

        content.show_file("x-bookmarks.md", f"# X Bookmarks Auth\n\nCompleting authentication with code: `{code[:20]}...`")

        async def do_complete():
            try:
                from .client.grpc_client import get_grpc_client

                client = await get_grpc_client()
                result = await client.call("XBookmarks", "complete_auth", {"code": code, "verifier": ""})

                if "error" in result:
                    content.show_file("x-bookmarks.md", f"""# Auth Error

{result.get('error', 'Unknown error')}

{result.get('message', '')}

**Troubleshooting:**
- The authorization code may have expired (valid for 10 minutes)
- Try starting the flow again with `/x-bookmarks auth`
""")
                    return

                # Success!
                username = result.get("username", "Unknown")
                output = f"""# X Bookmarks Auth Complete

**Successfully authenticated as @{username}**

Your X bookmarks sync is now configured. You can:

- `/x-bookmarks sync` - Sync your bookmarks now
- `/x-bookmarks status` - View sync status

Tokens have been saved securely and will auto-refresh.
"""
                content.show_file("x-bookmarks.md", output)

            except Exception as e:
                content.show_file("x-bookmarks.md", f"# Auth Error\n\n{e}")

        asyncio.create_task(do_complete())

    def _handle_datasets_command(self, args: str) -> None:
        """Handle /datasets command for HuggingFace dataset discovery.

        Usage:
            /datasets list [limit]     - List trending HuggingFace datasets
            /datasets add <id> [notes] - Add external dataset to KB
            /datasets info <id>        - Get detailed info about a dataset
            /datasets kb               - List datasets in KB (internal + external)
            /ds                        - Shortcut alias
        """
        import asyncio

        content = self.query_one("#info-panel", InfoPanel)

        parts = args.strip().split(maxsplit=2)
        subcommand = parts[0] if parts else "kb"

        if subcommand == "list":
            limit = 5  # Default to 5 for meaningful context per item
            if len(parts) > 1:
                try:
                    limit = int(parts[1])
                except ValueError:
                    pass
            self._datasets_list(content, limit)
        elif subcommand == "add":
            if len(parts) < 2:
                content.show_file("datasets.md", """# Add Dataset

**Usage:** `/datasets add <dataset_id> [notes]`

**Example:**
```
/datasets add nvidia/OpenMathReasoning-Nemotron
/datasets add nvidia/OpenMathReasoning-Nemotron "For reasoning training"
```
""")
                return
            dataset_id = parts[1]
            notes = parts[2] if len(parts) > 2 else ""
            self._datasets_add(content, dataset_id, notes)
        elif subcommand == "info":
            if len(parts) < 2:
                content.show_file("datasets.md", """# Dataset Info

**Usage:** `/datasets info <dataset_id>`

**Example:**
```
/datasets info nvidia/OpenMathReasoning-Nemotron
```
""")
                return
            dataset_id = parts[1]
            self._datasets_info(content, dataset_id)
        elif subcommand in ("kb", ""):
            self._datasets_kb(content)
        else:
            content.show_file("datasets.md", f"""# HuggingFace Dataset Discovery

Unknown subcommand: {subcommand}

**Usage:**
- `/datasets list [limit]` - List trending HuggingFace datasets
- `/datasets add <id> [notes]` - Add external dataset to KB
- `/datasets info <id>` - Get detailed info about a dataset
- `/datasets kb` - List datasets in KB (internal + external)
- `/ds` - Shortcut alias
""")

    def _datasets_list(self, content: "InfoPanel", limit: int) -> None:
        """List trending HuggingFace datasets via gRPC."""
        import asyncio

        content.show_file("datasets.md", "# HuggingFace Datasets\n\n*Fetching...*")

        async def do_list():
            try:
                from .client.grpc_client import get_grpc_client

                client = await get_grpc_client()
                result = await client.call("Datasets", "list", {"limit": limit})

                if "error" in result and result["error"]:
                    content.show_file("datasets.md", f"# Error\n\n{result['error']}")
                    return

                datasets = result.get("datasets", [])
                count = result.get("count", 0)
                saved_to = result.get("saved_to", "")

                if not datasets:
                    content.show_file("datasets.md", "# HuggingFace Datasets\n\n*No datasets found.*")
                    return

                # Show brief status in InfoPanel
                nbsp = "\u00a0"
                status_lines = [
                    "# Datasets List",
                    "",
                    f"Count{nbsp * 6}{count}  ",
                    "",
                    "---",
                    "",
                    "`/datasets add <id>`  ",
                    "`/datasets info <id>`  ",
                    "`/datasets kb`",
                ]
                content.show_file("datasets.md", "\n".join(status_lines))

                # Build prose format for zettelkasten with action links
                lines = ["# Trending HuggingFace Datasets", ""]
                lines.append(f"*{count} recent datasets from HuggingFace Hub*")
                lines.append("")

                for ds in datasets:
                    ds_id = ds.get("id", "unknown")
                    downloads = ds.get("downloads", 0)
                    likes = ds.get("likes", 0)
                    desc = ds.get("description", "") or "No description available."
                    author = ds.get("author", "") or ds_id.split("/")[0] if "/" in ds_id else ""
                    tags = ds.get("tags", [])

                    lines.append(f"## {ds_id}")
                    lines.append("")
                    if author:
                        lines.append(f"**Author:** {author}")
                    lines.append(f"**Downloads:** {downloads:,} | **Likes:** {likes}")
                    if tags:
                        # Show first few meaningful tags
                        display_tags = [t for t in tags[:5] if not t.startswith("region:")]
                        if display_tags:
                            lines.append(f"**Tags:** {', '.join(display_tags)}")
                    lines.append("")
                    lines.append(desc[:300] + ("..." if len(desc) > 300 else ""))
                    lines.append("")
                    # Action links for graph panel execution
                    lines.append(f"- [action:/datasets info {ds_id}]")
                    lines.append(f"- [action:/datasets add {ds_id}]")
                    lines.append("")

                # Open in NoteEditor
                self._show_output("hf_datasets", "\n".join(lines))

            except Exception as e:
                content.show_file("datasets.md", f"# Error\n\n{e}")

        asyncio.create_task(do_list())

    def _datasets_add(self, content: "InfoPanel", dataset_id: str, notes: str) -> None:
        """Add external dataset to KB via gRPC."""
        import asyncio

        content.show_file("datasets.md", f"# Adding Dataset\n\nFetching `{dataset_id}`...")

        async def do_add():
            try:
                from .client.grpc_client import get_grpc_client

                client = await get_grpc_client()
                result = await client.call("Datasets", "add", {"dataset_id": dataset_id, "notes": notes})

                if "error" in result and result["error"]:
                    content.show_file("datasets.md", f"# Error\n\n{result['error']}")
                    return

                saved_to = result.get("saved_to", "")
                downloads = result.get("downloads", 0)
                likes = result.get("likes", 0)
                description = result.get("description", "")

                output = f"""# Dataset Added

**Dataset:** `{dataset_id}`
**Saved to:** `{saved_to}`

| Metric | Value |
|--------|-------|
| Downloads | {downloads:,} |
| Likes | {likes} |

**Description:**
{description}

---

Use `/datasets kb` to see all KB datasets.
"""
                content.show_file("datasets.md", output)

            except Exception as e:
                content.show_file("datasets.md", f"# Error\n\n{e}")

        asyncio.create_task(do_add())

    def _datasets_info(self, content: "InfoPanel", dataset_id: str) -> None:
        """Get detailed info about a dataset via gRPC."""
        import asyncio

        content.show_file("datasets.md", f"# Dataset Info\n\nFetching `{dataset_id}`...")

        async def do_info():
            try:
                from .client.grpc_client import get_grpc_client

                client = await get_grpc_client()
                result = await client.call("Datasets", "info", {"dataset_id": dataset_id})

                if "error" in result and result["error"]:
                    content.show_file("datasets.md", f"# Error\n\n{result['error']}")
                    return

                # Client returns flat dict with info fields directly
                url = result.get("url", "")

                ds_id = result.get("id", dataset_id)
                author = result.get("author", "")
                description = result.get("description", "")
                downloads = result.get("downloads", 0)
                likes = result.get("likes", 0)
                created_at = result.get("created_at", "")
                last_modified = result.get("last_modified", "")
                tags = result.get("tags", [])

                output = f"""# {ds_id}

**Author:** {author}
**URL:** {url}

| Metric | Value |
|--------|-------|
| Downloads | {downloads:,} |
| Likes | {likes} |
| Created | {created_at} |
| Modified | {last_modified} |

**Tags:** {', '.join(tags) if tags else 'None'}

**Description:**
{description}

---

**Actions:** `/datasets add {dataset_id}` to add to KB
"""
                content.show_file("datasets.md", output)

            except Exception as e:
                content.show_file("datasets.md", f"# Error\n\n{e}")

        asyncio.create_task(do_info())

    def _datasets_kb(self, content: "InfoPanel") -> None:
        """List datasets in KB via gRPC."""
        import asyncio

        content.show_file("datasets.md", "# KB Datasets\n\n*Loading...*")

        async def do_list_kb():
            try:
                from .client.grpc_client import get_grpc_client

                client = await get_grpc_client()
                result = await client.call("Datasets", "list_kb", {})

                internal = result.get("internal", [])
                external = result.get("external", [])
                internal_count = result.get("internal_count", 0)
                external_count = result.get("external_count", 0)

                # Show brief status in InfoPanel
                nbsp = "\u00a0"
                status_lines = [
                    "# KB Datasets",
                    "",
                    f"Internal{nbsp * 3}{internal_count}  ",
                    f"External{nbsp * 3}{external_count}  ",
                    "",
                    "---",
                    "",
                    "`/datasets list`  ",
                    "`/datasets add <id>`  ",
                    "`/datasets info <id>`",
                ]
                content.show_file("datasets.md", "\n".join(status_lines))

                # Build full table for zettelkasten
                lines = ["# KB Datasets", ""]
                lines.append(f"*{internal_count} internal, {external_count} external*")
                lines.append("")

                if internal:
                    lines.append(f"## Internal Datasets ({internal_count})")
                    lines.append("")
                    lines.append("| ID | Type | Path |")
                    lines.append("|----|------|------|")
                    for ds in internal:
                        lines.append(f"| `{ds.get('id', '')}` | {ds.get('type', '')} | `{ds.get('path', '')}` |")
                    lines.append("")

                if external:
                    lines.append(f"## External Datasets ({external_count})")
                    lines.append("")
                    lines.append("| ID | Type | Path |")
                    lines.append("|----|------|------|")
                    for ds in external:
                        lines.append(f"| `{ds.get('id', '')}` | {ds.get('type', '')} | `{ds.get('path', '')}` |")
                    lines.append("")

                if not internal and not external:
                    lines.append("No datasets in KB yet.")
                    lines.append("")
                    lines.append("**Actions:**")
                    lines.append("- `/datasets list` - Browse HuggingFace datasets")
                    lines.append("- `/datasets add <id>` - Add external dataset")

                lines.append("")
                lines.append("---")
                lines.append("**Actions:** `/datasets list` to browse HuggingFace, `/datasets add <id>` to add external")

                # Open in NoteEditor
                self._show_output("kb_datasets", "\n".join(lines))

            except Exception as e:
                content.show_file("datasets.md", f"# Error\n\n{e}")

        asyncio.create_task(do_list_kb())

    def _handle_models_command(self, args: str) -> None:
        """Handle /models command for HuggingFace model discovery.

        Usage:
            /models list [limit]     - List trending HuggingFace models
            /models add <id> [notes] - Add external model to KB
            /models info <id>        - Get detailed info about a model
            /models kb               - List models in KB (internal + external)
            /m                       - Shortcut alias
        """
        import asyncio

        content = self.query_one("#info-panel", InfoPanel)

        parts = args.strip().split(maxsplit=2)
        subcommand = parts[0] if parts else "kb"

        if subcommand == "list":
            limit = 5  # Default to 5 for meaningful context per item
            filter_str = ""
            if len(parts) > 1:
                try:
                    limit = int(parts[1])
                except ValueError:
                    # Could be a filter like "text-generation"
                    filter_str = parts[1]
            self._models_list(content, limit, filter_str)
        elif subcommand == "add":
            if len(parts) < 2:
                content.show_file("models.md", """# Add Model

**Usage:** `/models add <model_id> [notes]`

**Example:**
```
/models add meta-llama/Llama-3.3-70B-Instruct
/models add meta-llama/Llama-3.3-70B-Instruct "Main reasoning model"
```
""")
                return
            model_id = parts[1]
            notes = parts[2] if len(parts) > 2 else ""
            self._models_add(content, model_id, notes)
        elif subcommand == "info":
            if len(parts) < 2:
                content.show_file("models.md", """# Model Info

**Usage:** `/models info <model_id>`

**Example:**
```
/models info meta-llama/Llama-3.3-70B-Instruct
```
""")
                return
            model_id = parts[1]
            self._models_info(content, model_id)
        elif subcommand in ("kb", ""):
            self._models_kb(content)
        else:
            content.show_file("models.md", f"""# HuggingFace Model Discovery

Unknown subcommand: {subcommand}

**Usage:**
- `/models list [limit]` - List trending HuggingFace models
- `/models add <id> [notes]` - Add external model to KB
- `/models info <id>` - Get detailed info about a model
- `/models kb` - List models in KB (internal + external)
- `/m` - Shortcut alias
""")

    def _models_list(self, content: "InfoPanel", limit: int, filter_str: str = "") -> None:
        """List trending HuggingFace models via gRPC."""
        import asyncio
        from pathlib import Path

        content.show_file("models.md", "# HuggingFace Models\n\n*Fetching...*")

        async def do_list():
            try:
                from .client.grpc_client import get_grpc_client

                client = await get_grpc_client()
                result = await client.call("Models", "list", {"limit": limit, "filter": filter_str})

                if "error" in result and result["error"]:
                    content.show_file("models.md", f"# Error\n\n{result['error']}")
                    return

                models = result.get("models", [])
                count = result.get("count", 0)
                saved_to = result.get("saved_to", "")

                if not models:
                    content.show_file("models.md", "# HuggingFace Models\n\n*No models found.*")
                    return

                # Show brief status in InfoPanel
                nbsp = "\u00a0"
                status_lines = [
                    "# Models List",
                    "",
                    f"Count{nbsp * 6}{count}  ",
                    f"Filter{nbsp * 5}{filter_str or 'all'}  ",
                    "",
                    "---",
                    "",
                    "`/models add <id>`  ",
                    "`/models info <id>`  ",
                    "`/models kb`",
                ]
                content.show_file("models.md", "\n".join(status_lines))

                # Build prose format for zettelkasten with action links
                lines = ["# Trending HuggingFace Models", ""]
                filter_note = f" (filter: {filter_str})" if filter_str else ""
                lines.append(f"*{count} models from HuggingFace Hub{filter_note}*")
                lines.append("")

                for m in models:
                    m_id = m.get("id", "unknown")
                    downloads = m.get("downloads", 0)
                    likes = m.get("likes", 0)
                    pipeline = m.get("pipeline_tag", "")
                    author = m.get("author", "") or (m_id.split("/")[0] if "/" in m_id else "")
                    model_type = m.get("model_type", "")
                    library = m.get("library_name", "")
                    tags = m.get("tags", [])

                    lines.append(f"## {m_id}")
                    lines.append("")
                    if author:
                        lines.append(f"**Author:** {author}")
                    lines.append(f"**Downloads:** {downloads:,} | **Likes:** {likes}")
                    if pipeline:
                        lines.append(f"**Pipeline:** {pipeline}")
                    if library:
                        lines.append(f"**Library:** {library}")
                    if model_type:
                        lines.append(f"**Type:** {model_type}")
                    if tags:
                        # Show first few meaningful tags
                        display_tags = [t for t in tags[:5] if not t.startswith("region:") and not t.startswith("license:")]
                        if display_tags:
                            lines.append(f"**Tags:** {', '.join(display_tags)}")
                    lines.append("")
                    # Action links for graph panel execution
                    lines.append(f"- [action:/models info {m_id}]")
                    lines.append(f"- [action:/models add {m_id}]")
                    lines.append("")

                # Open in NoteEditor
                self._show_output("hf_models", "\n".join(lines))

            except Exception as e:
                content.show_file("models.md", f"# Error\n\n{e}")

        asyncio.create_task(do_list())

    def _models_add(self, content: "InfoPanel", model_id: str, notes: str) -> None:
        """Add external model to KB via gRPC."""
        import asyncio

        content.show_file("models.md", f"# Adding Model\n\nFetching `{model_id}`...")

        async def do_add():
            try:
                from .client.grpc_client import get_grpc_client

                client = await get_grpc_client()
                result = await client.call("Models", "add", {"model_id": model_id, "notes": notes})

                if "error" in result and result["error"]:
                    content.show_file("models.md", f"# Error\n\n{result['error']}")
                    return

                saved_to = result.get("saved_to", "")
                downloads = result.get("downloads", 0)
                likes = result.get("likes", 0)
                pipeline_tag = result.get("pipeline_tag", "")

                output = f"""# Model Added

**Model:** `{model_id}`
**Saved to:** `{saved_to}`

| Metric | Value |
|--------|-------|
| Downloads | {downloads:,} |
| Likes | {likes} |
| Pipeline | {pipeline_tag} |

---

Use `/models kb` to see all KB models.
"""
                content.show_file("models.md", output)

            except Exception as e:
                content.show_file("models.md", f"# Error\n\n{e}")

        asyncio.create_task(do_add())

    def _models_info(self, content: "InfoPanel", model_id: str) -> None:
        """Get detailed info about a model via gRPC."""
        import asyncio

        content.show_file("models.md", f"# Model Info\n\nFetching `{model_id}`...")

        async def do_info():
            try:
                from .client.grpc_client import get_grpc_client

                client = await get_grpc_client()
                result = await client.call("Models", "info", {"model_id": model_id})

                if "error" in result and result["error"]:
                    content.show_file("models.md", f"# Error\n\n{result['error']}")
                    return

                # Client returns flat dict with info fields directly
                url = result.get("url", "")

                m_id = result.get("id", model_id)
                author = result.get("author", "")
                pipeline_tag = result.get("pipeline_tag", "")
                downloads = result.get("downloads", 0)
                likes = result.get("likes", 0)
                created_at = result.get("created_at", "")
                last_modified = result.get("last_modified", "")
                tags = result.get("tags", [])
                gated = result.get("gated", False)
                library_name = result.get("library_name", "")

                output = f"""# {m_id}

**Author:** {author}
**URL:** {url}

| Metric | Value |
|--------|-------|
| Downloads | {downloads:,} |
| Likes | {likes} |
| Pipeline | {pipeline_tag} |
| Library | {library_name} |
| Gated | {"Yes" if gated else "No"} |
| Created | {created_at} |
| Modified | {last_modified} |

**Tags:** {', '.join(tags) if tags else 'None'}

---

**Actions:** `/models add {model_id}` to add to KB
"""
                content.show_file("models.md", output)

            except Exception as e:
                content.show_file("models.md", f"# Error\n\n{e}")

        asyncio.create_task(do_info())

    def _models_kb(self, content: "InfoPanel") -> None:
        """List models in KB via gRPC."""
        import asyncio

        content.show_file("models.md", "# KB Models\n\n*Loading...*")

        async def do_list_kb():
            try:
                from .client.grpc_client import get_grpc_client

                client = await get_grpc_client()
                result = await client.call("Models", "list_kb", {})

                internal = result.get("internal", [])
                external = result.get("external", [])
                internal_count = result.get("internal_count", 0)
                external_count = result.get("external_count", 0)
                total_cache_bytes = result.get("total_cache_bytes", 0)
                cache_gb = total_cache_bytes / (1024 ** 3)

                # Show brief status in InfoPanel
                nbsp = "\u00a0"
                status_lines = [
                    "# KB Models",
                    "",
                    f"Internal{nbsp * 3}{internal_count}  ",
                    f"External{nbsp * 3}{external_count}  ",
                    f"Cache{nbsp * 6}{cache_gb:.1f} GB  ",
                    "",
                    "---",
                    "",
                    "`/models list`  ",
                    "`/models add <id>`  ",
                    "`/models info <id>`",
                ]
                content.show_file("models.md", "\n".join(status_lines))

                # Build full table for zettelkasten
                lines = ["# KB Models", ""]
                lines.append(f"*{internal_count} internal, {external_count} external - {cache_gb:.1f} GB cached*")
                lines.append("")

                if internal:
                    lines.append(f"## Internal Models ({internal_count})")
                    lines.append("")
                    lines.append("| ID | Pipeline | Size |")
                    lines.append("|----|----------|------|")
                    for m in internal:
                        m_id = m.get("id", "")
                        pipeline = m.get("pipeline_tag", "")
                        size_bytes = m.get("size_bytes", 0)
                        size_gb = size_bytes / (1024 ** 3)
                        lines.append(f"| `{m_id}` | {pipeline} | {size_gb:.1f} GB |")
                    lines.append("")

                if external:
                    lines.append(f"## External Models ({external_count})")
                    lines.append("")
                    lines.append("| ID | Pipeline | Path |")
                    lines.append("|----|----------|------|")
                    for m in external:
                        lines.append(f"| `{m.get('id', '')}` | {m.get('pipeline_tag', '')} | `{m.get('path', '')}` |")
                    lines.append("")

                if not internal and not external:
                    lines.append("No models in KB yet.")
                    lines.append("")
                    lines.append("**Actions:**")
                    lines.append("- `/models list` - Browse HuggingFace models")
                    lines.append("- `/models add <id>` - Add external model")

                lines.append("")
                lines.append("---")
                lines.append("**Actions:** `/models list` to browse HuggingFace, `/models add <id>` to add external")

                # Open in NoteEditor
                self._show_output("kb_models", "\n".join(lines))

            except Exception as e:
                content.show_file("models.md", f"# Error\n\n{e}")

        asyncio.create_task(do_list_kb())

    def _handle_iso_command(self, args: str, content: "InfoPanel") -> None:
        """Handle /iso command for Iso view mode control.

        Usage:
            /iso              - Show current mode and available modes
            /iso <mode>       - Set Iso mode (curvature, persistence, complexity, boundary)
            /iso cycle        - Cycle to next mode
            /iso info         - Show detailed info about current mode
        """
        from .core.state import IsoMode
        from .core.iso_features import ISO_MODE_SYMBOLS

        if not args:
            # Show current mode and options
            symbol = ISO_MODE_SYMBOLS.get(self.state.iso_mode, "?")
            has_features = self.state.iso_features is not None

            modes_list = "\n".join([
                f"- **{mode.value}** ({ISO_MODE_SYMBOLS[mode]}): {self._iso_mode_description(mode)}"
                for mode in IsoMode
            ])

            content.show_file("iso.md", f"""# Iso View Mode

**Current**: {self.state.iso_mode.value} ({symbol})
**Features**: {'✓ Loaded' if has_features else '○ Using fallback'}

## Available Modes

{modes_list}

---

**Usage**:
- Press `i` to cycle modes
- `/iso <mode>` to set directly
- `/iso cycle` to cycle to next
- `/iso info` for detailed information
""")
            return

        parts = args.split()
        subcmd = parts[0].lower()

        if subcmd == "cycle":
            self.action_cycle_iso()
        elif subcmd == "info":
            self._show_iso_info(content)
        else:
            # Try to set mode directly
            try:
                self.state.iso_mode = IsoMode(subcmd)
                self._update_minigrids()
                symbol = ISO_MODE_SYMBOLS.get(self.state.iso_mode, "?")
                self.notify(f"Iso: {self.state.iso_mode.value} ({symbol})")
            except ValueError:
                content.show_file("error.txt", f"Unknown Iso mode: {subcmd}\n\nValid modes: curvature, persistence, complexity, boundary")

    def _iso_mode_description(self, mode: IsoMode) -> str:
        """Get human-readable description for an Iso mode."""
        descriptions = {
            IsoMode.CURVATURE: "Semantic boundaries via Ricci curvature",
            IsoMode.PERSISTENCE: "Topological complexity from H0+H1+H2",
            IsoMode.COMPLEXITY: "Semantic diversity within documents",
            IsoMode.BOUNDARY: "Documents forming semantic loops",
        }
        return descriptions.get(mode, mode.value)

    def _show_iso_info(self, content: "InfoPanel") -> None:
        """Show detailed information about current Iso mode and features."""
        from .core.state import IsoMode
        from .core.iso_features import ISO_MODE_SYMBOLS

        mode = self.state.iso_mode
        symbol = ISO_MODE_SYMBOLS.get(mode, "?")
        features = self.state.iso_features

        if features is None:
            content.show_file("iso.md", f"""# Iso View: {mode.value} ({symbol})

## Status

**IsoFeatures**: Not computed

The Iso view is using density fallback visualization.
Run `/reindex` to compute full IsoFeatures including:
- Per-document persistent homology (H0+H1+H2)
- Multi-vector complexity analysis
- Cocycle-based boundary attribution

---

Press `i` to cycle modes or `/iso <mode>` to switch.
""")
            return

        # Show detailed feature info
        content.show_file("iso.md", f"""# Iso View: {mode.value} ({symbol})

## IsoFeatures

- **Documents**: {features.n_documents}
- **Embedding Type**: {features.embedding_type}
- **Computation Time**: {features.computation_time:.2f}s
- **Diagrams**: {len(features.diagrams)} persistence diagrams

## Feature Arrays

| Mode | Symbol | Min | Max | Mean | Std |
|------|--------|-----|-----|------|-----|
| Curvature | κ | {features.curvatures.min():.3f} | {features.curvatures.max():.3f} | {features.curvatures.mean():.3f} | {features.curvatures.std():.3f} |
| Persistence | π | {features.persistence.min():.3f} | {features.persistence.max():.3f} | {features.persistence.mean():.3f} | {features.persistence.std():.3f} |
| Complexity | σ | {features.complexity.min():.3f} | {features.complexity.max():.3f} | {features.complexity.mean():.3f} | {features.complexity.std():.3f} |
| Boundary | β | {features.boundary.min():.3f} | {features.boundary.max():.3f} | {features.boundary.mean():.3f} | {features.boundary.std():.3f} |

## Mode Description

**{mode.value}**: {self._iso_mode_description(mode)}

---

Press `i` to cycle modes or `/iso <mode>` to switch.
""")

    def _run_search(self, query: str) -> None:
        """Search KB and optionally web for a query."""
        import asyncio
        from datetime import datetime

        content = self.query_one("#info-panel", InfoPanel)
        think = self.query_one("#think-panel", ThinkPanel)

        if not query:
            content.show_file("error.txt", "Usage: /search <query>\n\nSearches KB files and content.")
            return

        content.show_file("search.md", f"Searching for: **{query}**\n\n*Searching KB...*")
        think.stream_reasoning(f"Searching KB for: {query}")

        async def search():
            start_time = datetime.now()
            kb_root = Path(self.config.kb.root)
            results = []

            # Search KB files
            for allowed_dir in ("archive", "current", "scratch"):
                dir_path = kb_root / allowed_dir
                if not dir_path.exists():
                    continue

                for md_file in dir_path.rglob("*.md"):
                    # Check filename
                    if query.lower() in md_file.name.lower():
                        rel_path = md_file.relative_to(kb_root)
                        results.append({
                            "path": str(rel_path),
                            "match": "filename",
                            "preview": md_file.name,
                        })
                        continue

                    # Check content
                    try:
                        file_content = md_file.read_text()
                        if query.lower() in file_content.lower():
                            idx = file_content.lower().find(query.lower())
                            start = max(0, idx - 50)
                            end = min(len(file_content), idx + len(query) + 50)
                            preview = file_content[start:end].replace("\n", " ")
                            if start > 0:
                                preview = "..." + preview
                            if end < len(file_content):
                                preview = preview + "..."

                            rel_path = md_file.relative_to(kb_root)
                            results.append({
                                "path": str(rel_path),
                                "match": "content",
                                "preview": preview,
                            })
                    except Exception:
                        continue

                    if len(results) >= 20:
                        break
                if len(results) >= 20:
                    break

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            # Format results
            lines = [
                f"# Search: {query}",
                "",
                f"**Found:** {len(results)} results in KB",
                "",
            ]

            if results:
                lines.append("## KB Results")
                lines.append("")
                for r in results:
                    match_type = "[FILE]" if r["match"] == "filename" else "[TEXT]"
                    lines.append(f"- {match_type} **{r['path']}**")
                    lines.append(f"  {r['preview'][:100]}")
                    lines.append("")
            else:
                lines.append("*No results in KB.*")
                lines.append("")
                lines.append("Try `/research <topic>` to search the web and save to KB.")

            self._show_output("search", "\n".join(lines))

            # Record trace
            think.complete_trace(
                operation="search",
                query=query,
                summary=f"Found {len(results)} KB results",
                tokens=0,
                sources=len(results),
                duration_ms=duration_ms,
            )

        asyncio.create_task(search())

    def _run_research(self, topic: str) -> None:
        """Research a topic using web search and LLM synthesis."""
        import asyncio
        from datetime import datetime

        content = self.query_one("#info-panel", InfoPanel)
        think = self.query_one("#think-panel", ThinkPanel)

        if not topic:
            content.show_file("error.txt", "Usage: /research <topic>\n\nSearches web and synthesizes results to KB.")
            return

        domain = self.state.domain or "open"
        content.show_file("research.md", f"Researching: **{topic}**\n\nDomain: {domain}\n\n*Searching web...*")
        think.stream_reasoning(f"Researching: {topic}")

        async def research():
            start_time = datetime.now()
            try:
                from .inference import get_client, get_search, Message

                # Search for information
                think.stream_reasoning("Searching web sources...")
                search = get_search()
                results = await search.search_for_kb(topic, domain, count=5)

                if not results:
                    content.show_file("research.md", f"# Research: {topic}\n\n*No search results found.*\n\nTry a different query or check your internet connection.")
                    think.clear_active()
                    return

                # Show search progress
                content.show_file("research.md", f"Researching: **{topic}**\n\nDomain: {domain}\n\nFound {len(results)} sources, synthesizing...")
                think.stream_reasoning(f"Found {len(results)} sources, synthesizing...")

                # Format sources for synthesis
                sources_text = "\n".join(
                    f"- [{r['title']}]({r['source']}): {r['summary']}" for r in results
                )

                # Synthesize with LLM
                client = get_client()
                synthesis_prompt = f"""Topic: {topic}
Domain: {domain}

Sources:
{sources_text}

Create a structured markdown note with:
1. Key points and facts
2. Implications or applications
3. Related concepts (as wiki-links using [[concept]] syntax)

Be concise but thorough."""

                synthesis = await client.complete(
                    messages=[
                        Message(
                            role="system",
                            content=f"You are a research assistant specializing in {domain}.",
                        ),
                        Message(role="user", content=synthesis_prompt),
                    ],
                    technique="cot_reflection",
                    max_tokens=2048,
                )

                # Save to KB
                today = datetime.now().strftime("%Y-%m-%d")
                timestamp = datetime.now().strftime("%H%M%S")
                safe_topic = topic.replace(" ", "_").replace("/", "-")[:50]
                kb_path = f"scratch/{today}/{timestamp}_{safe_topic}.md"

                full_content = f"""# {topic}

Created: {datetime.now().isoformat()}
Domain: {domain}

---

{synthesis.content}

---

## Sources

{sources_text}
"""
                kb_root = Path(self.config.kb.root)
                full_path = kb_root / kb_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(full_content)

                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                # Show result
                result_text = f"""# Research: {topic}

**Domain:** {domain}
**Saved to:** `{kb_path}`

---

{synthesis.content}

---

## Sources

{sources_text}
"""
                self._show_output("research", result_text)

                # Record trace
                think.complete_trace(
                    operation="research",
                    query=topic,
                    summary=f"Synthesized {len(results)} sources → {kb_path}",
                    tokens=synthesis.input_tokens + synthesis.output_tokens,
                    sources=len(results),
                    duration_ms=duration_ms,
                )

                # Refresh file tree
                file_tree = self.query_one("#file-tree", FileTree)
                file_tree.refresh_tree()

            except Exception as e:
                think.clear_active()
                content.show_file("error.txt", f"Research failed: {e}\n\nCheck that inference services are running.")

        asyncio.create_task(research())

    def _run_ask(self, args: str) -> None:
        """General-purpose agentic query - /ask away!

        Routes queries to appropriate mode:
        - --reason: Chain-of-thought reasoning
        - --search: Hybrid search + synthesis
        - --swarm: Multi-agent analysis
        - --platform: Platform diagnostics
        - --save: Save response to KB
        """
        import asyncio
        import os
        from datetime import datetime

        content = self.query_one("#info-panel", InfoPanel)
        think = self.query_one("#think-panel", ThinkPanel)

        if not args:
            content.show_file("ask.md", """# /ask away!

The general-purpose agentic query interface.

## Usage

```
/ask <question>              Auto-route based on query
/ask --reason <question>     Force reasoning mode
/ask --search <question>     Force search + synthesis
/ask --swarm <question>      Force multi-agent analysis
/ask --platform <error>      Diagnose platform issues
/ask --save                  Save response to KB
```

## Examples

```
/ask what is 2+2?
/ask --search distributed consensus
/ask --platform no documents found
/ask --reason --save explain CAP theorem
```
""")
            return

        # Parse flags
        force_reason = "--reason" in args
        force_search = "--search" in args
        force_swarm = "--swarm" in args
        is_platform = "--platform" in args
        save_to_kb = "--save" in args

        # Clean up flags from query
        query = args
        for flag in ["--reason", "--search", "--swarm", "--platform", "--save"]:
            query = query.replace(flag, "").strip()

        if not query:
            content.show_file("error.txt", "Usage: /ask <question>\n\n/ask away!")
            return

        # Determine mode
        if force_swarm:
            mode = "swarm"
        elif force_search:
            mode = "search"
        elif force_reason:
            mode = "reasoning"
        elif is_platform:
            mode = "platform"
        else:
            # Auto-route based on query
            query_lower = query.lower()
            platform_patterns = ["error", "failed", "not found", "exception", "no documents", "timeout"]
            research_patterns = ["what is", "how does", "explain", "compare", "difference"]
            domain_patterns = ["analyze", "assess", "evaluate", "implications", "strategy"]

            if any(p in query_lower for p in platform_patterns):
                mode = "platform"
            elif any(p in query_lower for p in research_patterns):
                mode = "search"
            elif any(p in query_lower for p in domain_patterns):
                mode = "swarm"
            else:
                mode = "reasoning"

        content.show_file("ask.md", f"# /ask\n\n**Query:** {query}\n**Mode:** {mode}\n\n*Processing...*")
        think.start_trace("ask", query, model="auto")

        async def run_ask():
            start_time = datetime.now()
            try:
                from .cli import GaiusCLI

                # Use CLI implementation for consistency
                cli = GaiusCLI()
                cli.state = self.state

                # Call the appropriate CLI method
                if mode == "platform":
                    engine_client = await cli._get_engine_client_cached()
                    result = await cli._ask_platform(query, engine_client, save_to_kb)
                elif mode == "search":
                    engine_client = await cli._get_engine_client_cached()
                    result = await cli._ask_search(query, engine_client, save_to_kb)
                elif mode == "swarm":
                    engine_client = await cli._get_engine_client_cached()
                    result = await cli._ask_swarm(query, engine_client, save_to_kb)
                else:  # reasoning
                    engine_client = await cli._get_engine_client_cached()
                    result = await cli._ask_reason(query, engine_client, save_to_kb)

                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                # Format response for display
                response = result.get("response", "No response")
                model = result.get("model", "unknown")
                tokens = result.get("tokens", "0+0")

                result_text = f"""# /ask - {mode}

**Query:** {query}
**Model:** {model}
**Tokens:** {tokens}
**Duration:** {duration_ms}ms

---

{response}
"""
                if result.get("saved_to"):
                    result_text += f"\n\n---\n**Saved to:** `{result.get('saved_to')}`"

                if result.get("diagnostics"):
                    import json
                    diag_text = json.dumps(result["diagnostics"], indent=2)
                    result_text += f"\n\n## Diagnostics\n```json\n{diag_text}\n```"

                self._show_output("ask", result_text)

                # Record trace
                think.complete_trace(
                    operation="ask",
                    query=query,
                    summary=f"{mode}: {response[:50]}...",
                    tokens=int(tokens.split("+")[0]) + int(tokens.split("+")[1]) if "+" in tokens else 0,
                    sources=result.get("kb_sources", 0) + result.get("web_sources", 0),
                    duration_ms=duration_ms,
                )

                # Refresh file tree if saved
                if result.get("saved_to"):
                    file_tree = self.query_one("#file-tree", FileTree)
                    file_tree.refresh_tree()

            except Exception as e:
                think.clear_active()
                content.show_file("error.txt", f"Ask failed: {e}\n\nCheck that inference services are running.")

        asyncio.create_task(run_ask())

    def _run_watch(self, args: str) -> None:
        """OTel telemetry observability."""
        import asyncio
        import os

        content = self.query_one("#info-panel", InfoPanel)

        parts = args.split(maxsplit=1) if args else ["status"]
        subcmd = parts[0].lower()
        filter_arg = parts[1] if len(parts) > 1 else ""

        async def run_watch():
            try:
                from .cli import GaiusCLI

                cli = GaiusCLI()
                cli.state = self.state

                # Check OTel availability
                otel_available = False
                try:
                    from opentelemetry import trace
                    otel_available = True
                except ImportError:
                    pass

                if subcmd == "status":
                    result = await cli._watch_status(otel_available)
                elif subcmd == "traces":
                    result = await cli._watch_traces(filter_arg, otel_available)
                elif subcmd == "spans":
                    result = await cli._watch_spans(filter_arg, otel_available)
                elif subcmd == "metrics":
                    result = await cli._watch_metrics(filter_arg, otel_available)
                elif subcmd == "logs":
                    result = await cli._watch_logs(filter_arg, otel_available)
                elif subcmd == "clear":
                    result = cli._watch_clear()
                else:
                    result = await cli._watch_traces(args, otel_available)

                # Format result for display
                import json
                result_text = f"""# /watch {subcmd}

```json
{json.dumps(result, indent=2, default=str)}
```
"""
                content.show_file("watch.md", result_text)

            except Exception as e:
                content.show_file("error.txt", f"Watch failed: {e}")

        asyncio.create_task(run_watch())

    def _run_engine_command(self, args: str) -> None:
        """Engine connectivity commands."""
        import asyncio
        import os

        content = self.query_one("#info-panel", InfoPanel)

        parts = args.split(maxsplit=1) if args else ["status"]
        subcmd = parts[0].lower()

        async def run_engine():
            try:
                from .cli import GaiusCLI

                cli = GaiusCLI()
                result = await cli._cmd_engine(args if args else "status")

                # Format result for display
                import json
                result_text = f"""# /engine {subcmd}

```json
{json.dumps(result, indent=2, default=str)}
```
"""
                content.show_file("engine.md", result_text)

            except Exception as e:
                content.show_file("error.txt", f"Engine command failed: {e}")

        asyncio.create_task(run_engine())

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        yield Header()

        # Status bar
        yield Static(self._status_text(), id="status-bar")

        # Main container with panels
        with Container(id="main-container"):
            with Horizontal(id="main-horizontal"):
                # Left panel (files/agents)
                with Vertical(id="left-panel"):
                    yield Static("Navigator", id="left-panel-header")
                    yield FileTree(
                        self.state,
                        agents=AGENT_DATA,
                        kb_root=self.config.kb.root,
                        id="file-tree",
                    )

                # Center area (main grid + mini-grids in CAD layout)
                with Vertical(id="center-area"):
                    # Grid row: 19x19 main grid + right column of mini-grids
                    with Horizontal(id="grid-row"):
                        # Main 19x19 grid with location indicator below
                        with Vertical(id="main-grid-wrapper"):
                            yield MainGrid(self.state, id="main-grid")
                            yield LocationIndicator(
                                self.state.cursor_x,
                                self.state.cursor_y,
                                id="location-indicator"
                            )

                        # Right column: two stacked 9x9 mini-grids
                        with Vertical(id="right-minigrids"):
                            yield MiniGrid("Embed", id="minigrid-top", classes="right")
                            yield MiniGrid("Iso", id="minigrid-bottom", classes="bottom-right")

                        # Graph view wrapper (mirrors main-grid-wrapper) - hidden by default, 'g' cycles modes
                        with Vertical(id="graph-wrapper", classes="hidden"):
                            yield GraphView(kb_root=self.config.kb.root, id="graph-view")
                            yield LinkPreview(id="link-preview")

                        # Think panel (reasoning traces) - hidden by default, 'g' cycles modes
                        yield ThinkPanel(self.state, id="think-panel", classes="hidden")

                        # Evolution panel (daemon monitoring) - hidden by default, 'g' cycles modes
                        yield EvolutionPanel(self.state, id="evolution-panel", classes="hidden")

                        # Init panel (engine initialization progress) - shown during startup, 'g' cycles modes
                        yield InitPanel(self.state, id="init-panel", classes="hidden")

                        # Observe panel (operational metrics) - hidden by default, 'g' cycles modes
                        yield ObservePanel(self.state, id="observe-panel", classes="hidden")

                    # Note editor below the grids (hidden by default, Ctrl-N to show)
                    yield NoteEditor(id="note-editor", classes="hidden")

                # Right panel (content)
                with Vertical(id="right-panel"):
                    yield InfoPanel(self.state, id="info-panel")

        # Command input
        yield CommandInput(self.state, id="command-input")

        yield Footer()

        # Splash screen (overlay layer, dismisses when ready)
        yield SplashScreen(id="splash")

    def _status_text(self) -> str:
        """Generate status bar text."""
        mode = self.state.view_mode.value.upper()
        overlay = self.state.overlay_mode.value
        coord = self.state.cursor_coord
        domain = self.state.domain or "open"
        domain = domain[:20] + "..." if len(domain) > 23 else domain

        # Center panel mode indicator
        center_mode = self.state.center_panel_mode.value.upper()
        center_style = {
            "INIT": "yellow",
            "GRAPH": "blue",
            "THINK": "cyan",
            "EVOLUTION": "magenta",
            "NONE": "dim",
        }.get(center_mode, "white")

        # Connection status indicator (thin client architecture)
        conn_icons = {
            ConnectionStatus.PENDING: ("○", "dim"),
            ConnectionStatus.CONNECTING: ("◐", "yellow"),
            ConnectionStatus.CONNECTED: ("●", "green"),
            ConnectionStatus.OFFLINE: ("◯", "dim white"),
            ConnectionStatus.ERROR: ("✗", "red"),
        }
        conn_icon, conn_color = conn_icons.get(self._connection_status, ("?", "red"))

        # Generation indicator (shows data freshness)
        gen_str = f"g{self._state_generation}" if self._state_generation > 0 else ""

        return (
            f"[{conn_color}]{conn_icon}[/] "
            f"[bold green]{mode}[/] │ "
            f"[yellow]{overlay}[/] │ "
            f"[{center_style}]{center_mode}[/] │ "
            f"[bold cyan]{coord}[/] │ "
            f"{domain} "
            f"[dim]{gen_str}[/] │ "
            f"[dim]hjkl:move o:overlay v:view g:panel /:cmd[/]"
        )

    def _update_status(self) -> None:
        """Update the status bar."""
        status = self.query_one("#status-bar", Static)
        status.update(self._status_text())

    def _refresh_grid(self) -> None:
        """Refresh the main grid."""
        grid = self.query_one("#main-grid", MainGrid)
        grid.update_state(self.state)

    def _update_minigrids(self) -> None:
        """Update mini-grids based on cursor position with real TDA/UMAP data.

        IMPORTANT: Only uses cached data - does NOT trigger slow projection.
        This ensures instant startup. Mini-grids stay empty until background
        sync populates the cache.

        Thin Client: TDA features come from Postgres cache (self.state), not
        from TDAManager. The Engine computes TDA, TUI just displays it.
        """
        from .core.minigrids import get_real_minigrid_data
        from .core.projection import get_grid_manager

        # Get grid data from manager cache (don't trigger projection)
        grid_data = None
        try:
            grid_manager = get_grid_manager()

            # Only use cached data - don't call get_grid_data() which triggers projection
            if grid_manager._cache_valid and grid_manager._cached_data is not None:
                grid_data = grid_manager._cached_data
            # else: mini-grids stay empty until background sync

            # Debug logging
            if grid_data:
                self.log.debug(
                    f"Mini-grid data: n_docs={grid_data.n_documents}, "
                    f"embeddings={'yes' if grid_data.raw_embeddings is not None else 'no'}, "
                    f"grid_to_emb={len(grid_data.grid_to_embedding)} mappings"
                )

            # Check if we have data
            if grid_data and grid_data.n_documents == 0:
                # No documents loaded yet
                grid_data = None

        except Exception as e:
            # If grid data not available, mini-grids will be empty
            import traceback
            self.log.error(f"Failed to get grid data: {e}")
            self.log.error(traceback.format_exc())

        # Get curvatures for Iso view (legacy fallback)
        curvatures = self.state.curvatures_raw if self.state.curvatures_raw else None

        # Use real data from grid projection and geometry
        data = get_real_minigrid_data(
            grid_data=grid_data,
            curvatures=curvatures,
            cursor_x=self.state.cursor_x,
            cursor_y=self.state.cursor_y,
            iso_mode=self.state.iso_mode,
            iso_features=self.state.iso_features,
        )

        # Update each mini-grid (right column: top and bottom)
        # data values are MiniGridData objects with .grid and .title
        try:
            if "right" in data and data["right"]:
                mg_data = data["right"]
                self.query_one("#minigrid-top", MiniGrid).update_data(mg_data.grid, mg_data.title)
            if "top" in data and data["top"]:
                mg_data = data["top"]
                self.query_one("#minigrid-bottom", MiniGrid).update_data(mg_data.grid, mg_data.title)
        except Exception as e:
            self.log.error(f"Failed to update mini-grids: {e}")

    def _update_location(self) -> None:
        """Update the location indicator with current cursor position."""
        indicator = self.query_one("#location-indicator", LocationIndicator)
        indicator.update_position(self.state.cursor_x, self.state.cursor_y)

    def _update_explanation(self) -> None:
        """Update the content panel with contextual explanation."""
        explanation = generate_explanation(
            self.state.view_mode,
            self.state.overlay_mode,
            self.state.cursor_x,
            self.state.cursor_y,
        )
        content = self.query_one("#info-panel", InfoPanel)
        content.show_file("context.md", explanation)

    def _show_output(self, title: str, content: str, extension: str = ".md") -> str:
        """Show command output in center panel via NoteEditor.

        Creates scratch file and opens in editor. Refreshes file tree.

        Args:
            title: Base name for scratch file (will be sanitized)
            content: Text content to display
            extension: File extension (default .md)

        Returns:
            Path to created scratch file
        """
        editor = self.query_one("#note-editor", NoteEditor)
        filepath = editor.show_content(title, content, extension)

        file_tree = self.query_one("#file-tree", FileTree)
        file_tree.refresh_tree()

        return filepath

    # ─────────────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────────────

    def action_move(self, dx: int, dy: int) -> None:
        """Move cursor by delta."""
        if self.state.move_cursor(dx, dy):
            self._refresh_grid()
            self._update_status()
            self._update_minigrids()
            self._update_location()
            self._update_explanation()

    def action_cycle_view(self) -> None:
        """Cycle through view modes."""
        self.state.cycle_view_mode()
        self._refresh_grid()
        self._update_status()
        self._update_explanation()

    def action_cycle_overlay(self) -> None:
        """Cycle through overlay modes."""
        self.state.cycle_overlay_mode()
        self._refresh_grid()
        self._update_status()
        self._update_explanation()

    def action_cycle_iso(self) -> None:
        """Cycle through Iso view modes: κ → π → σ → β → κ."""
        from .core.iso_features import ISO_MODE_SYMBOLS
        new_mode = self.state.cycle_iso_mode()
        symbol = ISO_MODE_SYMBOLS.get(new_mode, "?")
        self._update_minigrids()
        self.notify(f"Iso: {new_mode.value} ({symbol})")

    def action_toggle_candidates(self) -> None:
        """Toggle candidate markers."""
        self.state.toggle_candidates()
        self._refresh_grid()

    def action_toggle_left(self) -> None:
        """Toggle left panel visibility."""
        panel = self.query_one("#left-panel")
        panel.toggle_class("hidden")

    def action_toggle_right(self) -> None:
        """Toggle right panel visibility."""
        panel = self.query_one("#right-panel")
        panel.toggle_class("hidden")

    def action_toggle_both(self) -> None:
        """Toggle both panels."""
        self.action_toggle_left()
        self.action_toggle_right()

    def action_command_mode(self) -> None:
        """Enter command mode."""
        cmd_input = self.query_one("#command-input", CommandInput)
        cmd_input.enter_command_mode("/")

    def action_show_help(self) -> None:
        """Show help in content panel."""
        content = self.query_one("#info-panel", InfoPanel)
        help_text = """# Gaius Help

## Navigation
- **hjkl**: Move cursor (vim-style)
- **t**: Tenuki (jump to strategic point)

## Views
- **v**: Cycle view modes (Go/Theta/Swarm)
- **o**: Cycle overlays (none/risk/h1/h2/agents/temporal)
- **c**: Toggle candidate markers

## Panels
- **[**: Toggle left panel (files/agents)
- **]**: Toggle right panel (content)
- **\\\\**: Toggle both panels

## Center Panel
- **g**: Cycle center modes (Graph → Think → Evolution → None)
- **e**: Jump directly to Evolution panel

## Notes (Zettelkasten)
- **Ctrl-N**: Create new scratch note
- Vim-style editing (i/I/A/o/O to insert, ESC for normal)
- **:q** or **:wq**: Close editor
- **:mv path/to/file.md**: Move file to new location
- **:rename [name]**: Move to scratch/<today>/<name or timestamp>.md
- Auto-saves on every edit
- Notes: build/dev/scratch/{date}/{timestamp}.md
- Wiki-links: [[path/to/note]]

## Graph View (center panel)
- **Arrow keys**: Navigate between nodes (when graph focused)
- **Enter**: Open selected node's file
- Shows backlinks (what links here)
- Shows forward links (what this links to)
- Syncs with FileTree cursor

## Commands
- **/**: Enter command mode
- **?**: Show this help

## Common Commands
- `/init`: Initialize platform (index KB + project + TDA + cache)
- `/reindex`: Refresh grid from current KB embeddings
- `/domain <name>`: Set analysis domain
- `/search <query>`: Search KB files and content
- `/research <topic>`: Web search + LLM synthesis to KB
- `/swarm [domain]`: Run multi-agent analysis
- `/summary`: Generate daily summary
- `/activity`: View activity log
- `/tda`: Show topological features
- `/info`: Show cursor position info
- `/explain [position] [--no-save]`: Explain grid position with LLM
- `/inference [status|start|stop|restart]`: Manage inference stack
- `/evolve [start|stop|status|trigger|budget]`: Evolution daemon
- `/ambient [cycle|status]`: Ambient computing cycles
- `/q` or `/exit`: Quit Gaius

## Explain Command
- `/explain`: Explain current cursor position
- `/explain K10`: Explain specific Go position
- `/explain --no-save`: Don't save to KB
- Opens generated note in editor for review/editing

## Evolution (press `e` for panel)
- `/evolve start [endpoint]`: Clean start GPU + daemon (default: fast)
- `/evolve stop`: Stop evolution daemon
- `/evolve status`: Show daemon status
- `/evolve trigger [agent]`: Force evolution cycle
- `/evolve budget`: Show XAI evaluation budget
"""
        content.show_file("help.md", help_text)

    def _find_tenuki_target(self) -> tuple[int, int] | None:
        """Find high-curvature region for strategic exploration (tenuki).

        Uses differential geometry to identify semantic boundaries where
        meaning changes rapidly - the "turbulent" regions in the manifold.

        Scoring: |curvature| × distance_factor × novelty_factor

        Returns:
            (x, y) position or None if no curvature data
        """
        if not self.state.curvature_map:
            # Fallback: cycle through agent positions
            if self.state.agent_positions:
                current = (self.state.cursor_x, self.state.cursor_y)
                best_dist = 0
                best_pos = None

                for name, x, y, color in self.state.agent_positions:
                    dist = abs(x - current[0]) + abs(y - current[1])
                    if dist > best_dist:
                        best_dist = dist
                        best_pos = (x, y)

                return best_pos
            return None

        current = (self.state.cursor_x, self.state.cursor_y)
        best_score = 0.0
        best_pos = None
        exploration_radius = 3

        # Scan all grid positions for high-curvature regions
        for y in range(19):
            for x in range(19):
                # Skip if no curvature data at this position
                if y >= len(self.state.curvature_map) or x >= len(self.state.curvature_map[y]):
                    continue
                if self.state.curvature_map[y][x] == 0:  # No data
                    continue

                # Curvature magnitude (higher = more interesting)
                curvature = abs(self.state.curvature_map[y][x])

                # Distance from cursor (Manhattan distance)
                dist = abs(x - current[0]) + abs(y - current[1])

                # Distance factor: prefer moderate distances
                if dist < 3:
                    dist_factor = 0.1  # Too close, not much strategic value
                elif dist < 7:
                    dist_factor = 1.0  # Ideal distance
                elif dist < 12:
                    dist_factor = 0.7  # Moderate distance
                else:
                    dist_factor = 0.4  # Far away

                # Novelty factor: avoid recently visited regions
                min_visited_dist = 999
                for vx, vy in self.state.tenuki_visited:
                    visited_dist = abs(x - vx) + abs(y - vy)
                    min_visited_dist = min(min_visited_dist, visited_dist)

                if min_visited_dist < 3:
                    novelty_factor = 0.3  # Recently explored
                elif min_visited_dist < 6:
                    novelty_factor = 0.7  # Moderately explored
                else:
                    novelty_factor = 1.0  # Novel region

                # Combined score
                score = curvature * dist_factor * novelty_factor

                if score > best_score:
                    best_score = score
                    best_pos = (x, y)

        # Mark visited region (with radius) if we found a target
        if best_pos:
            for dx in range(-exploration_radius, exploration_radius + 1):
                for dy in range(-exploration_radius, exploration_radius + 1):
                    vx, vy = best_pos[0] + dx, best_pos[1] + dy
                    if 0 <= vx < 19 and 0 <= vy < 19:
                        self.state.tenuki_visited.add((vx, vy))

        return best_pos

    def action_tenuki(self) -> None:
        """Jump to point of highest strategic interest (tenuki).

        In Go, tenuki means 'playing elsewhere' - ignoring the local
        situation for a bigger play. Here we jump to high-curvature regions:
        semantic boundaries where understanding changes rapidly.

        Uses Ricci curvature to find 'turbulent' areas (complex boundaries)
        while avoiding recently visited regions.
        """
        target = self._find_tenuki_target()

        if target and target != (self.state.cursor_x, self.state.cursor_y):
            self.state.cursor_x, self.state.cursor_y = target
            self._refresh_grid()
            self._update_status()
            self._update_minigrids()
            self._update_location()

            # Show notification
            κ = 0.0
            if (self.state.curvature_map and
                target[1] < len(self.state.curvature_map) and
                target[0] < len(self.state.curvature_map[target[1]])):
                κ = self.state.curvature_map[target[1]][target[0]]

            self.notify(
                f"Tenuki → ({target[0]}, {target[1]}) | κ={κ:.3f}",
                severity="information",
                timeout=3
            )

    def action_new_note(self) -> None:
        """Create a new Zettelkasten note and focus the editor."""
        editor = self.query_one("#note-editor", NoteEditor)

        # Show the editor if hidden
        editor.remove_class("hidden")

        # Create new note with timestamp filename
        filepath = editor.new_note()

        # Refresh the file tree to show new note
        file_tree = self.query_one("#file-tree", FileTree)
        file_tree.refresh_tree()

        # Update graph if visible
        graph_wrapper = self.query_one("#graph-wrapper", Vertical)
        if not graph_wrapper.has_class("hidden"):
            graph = self.query_one("#graph-view", GraphView)
            graph.update_for_file(filepath)

        # Update status to show we're editing
        self._update_status()

        # Show confirmation in content panel
        content = self.query_one("#info-panel", InfoPanel)
        content.show_file("note.txt", f"New note: {filepath}\n\nVim keys: i=insert, ESC=normal, :q=close")

    def action_zoom_editor(self) -> None:
        """Toggle editor zoom (tmux-style Ctrl+z).

        When zoomed, the NoteEditor fills the center column (hiding the 19x19 grid
        and minigrids). Side panels remain visible and independent.
        Press Ctrl+z again to restore normal layout.
        """
        editor = self.query_one("#note-editor", NoteEditor)
        grid_row = self.query_one("#grid-row")

        # Toggle zoom state
        self.state.editor_zoomed = not self.state.editor_zoomed

        if self.state.editor_zoomed:
            # Show and zoom the editor
            editor.remove_class("hidden")
            editor.add_class("zoomed")

            # Hide the grid row (main grid, minigrids, center panels)
            grid_row.add_class("hidden")

            # Focus the editor
            editor.focus()
        else:
            # Restore normal layout
            editor.remove_class("zoomed")

            # Show the grid row
            grid_row.remove_class("hidden")

            # Restore center panel visibility
            self._apply_center_panel_mode()

        self._update_status()

    def action_toggle_graph(self) -> None:
        """Cycle center panel mode.

        During init: INIT → GRAPH → THINK → EVOLUTION → OBSERVE → NONE → INIT
        After ready: GRAPH → THINK → EVOLUTION → OBSERVE → NONE → GRAPH (skips INIT)
        """
        graph_wrapper = self.query_one("#graph-wrapper", Vertical)
        graph = self.query_one("#graph-view", GraphView)
        think = self.query_one("#think-panel", ThinkPanel)
        evolution = self.query_one("#evolution-panel", EvolutionPanel)
        init_panel = self.query_one("#init-panel", InitPanel)
        observe_panel = self.query_one("#observe-panel", ObservePanel)

        # Cycle to next mode (state.py handles init-aware cycling)
        new_mode = self.state.cycle_center_panel_mode()

        # Hide all first
        graph_wrapper.add_class("hidden")
        think.add_class("hidden")
        evolution.add_class("hidden")
        init_panel.add_class("hidden")
        observe_panel.add_class("hidden")

        # Update visibility based on mode
        if new_mode == CenterPanelMode.INIT:
            init_panel.remove_class("hidden")
            init_panel.refresh()
        elif new_mode == CenterPanelMode.GRAPH:
            graph_wrapper.remove_class("hidden")
            # Refresh graph content
            graph.scan_kb()
            editor = self.query_one("#note-editor", NoteEditor)
            link_preview = self.query_one("#link-preview", LinkPreview)
            if editor.current_file:
                graph.update_for_file(editor.current_file)
                # Initialize LinkPreview with current file
                link_preview.update_from_node("current", filepath=editor.current_file)
            elif graph.current_file:
                # Use graph's current file if editor has none
                link_preview.update_from_node("current", filepath=graph.current_file)
            else:
                # Clear LinkPreview if no file is open
                link_preview.clear()
        elif new_mode == CenterPanelMode.THINK:
            think.remove_class("hidden")
            think.refresh()
        elif new_mode == CenterPanelMode.EVOLUTION:
            evolution.remove_class("hidden")
            # Trigger data refresh
            import asyncio
            asyncio.create_task(evolution.refresh_data())
        elif new_mode == CenterPanelMode.OBSERVE:
            observe_panel.remove_class("hidden")
            observe_panel.refresh()
        else:  # NONE
            # Force layout refresh when hiding all panels
            self.query_one("#grid-row").refresh(layout=True)

        # Update status to show current mode
        self._update_status()

    def action_show_evolution(self) -> None:
        """Show evolution panel directly."""
        graph_wrapper = self.query_one("#graph-wrapper", Vertical)
        think = self.query_one("#think-panel", ThinkPanel)
        evolution = self.query_one("#evolution-panel", EvolutionPanel)
        init_panel = self.query_one("#init-panel", InitPanel)
        observe_panel = self.query_one("#observe-panel", ObservePanel)

        # Set mode directly to EVOLUTION
        self.state.center_panel_mode = CenterPanelMode.EVOLUTION

        # Hide others, show evolution
        graph_wrapper.add_class("hidden")
        think.add_class("hidden")
        init_panel.add_class("hidden")
        observe_panel.add_class("hidden")
        evolution.remove_class("hidden")

        # Trigger data refresh
        import asyncio
        asyncio.create_task(evolution.refresh_data())

        self._update_status()

    def action_quit_hint(self) -> None:
        """Show quit hint instead of immediately quitting."""
        content = self.query_one("#info-panel", InfoPanel)
        content.show_file("quit.txt", "Use /q or /exit to quit Gaius.")

    # ─────────────────────────────────────────────────────────────────────
    # Event Handlers
    # ─────────────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        """Initialize on mount - runs enterApp startup procedure."""
        self._refresh_grid()
        self._update_minigrids()
        self._update_explanation()

        # Apply panel visibility from config
        if not self.state.left_panel_visible:
            self.query_one("#left-panel").add_class("hidden")
        if not self.state.right_panel_visible:
            self.query_one("#right-panel").add_class("hidden")

        # Apply center panel mode from config
        self._apply_center_panel_mode()

        # Start state client for thin client architecture (instant startup)
        self._start_state_client()

        # Load minigrid embedding data from Postgres (background)
        self._load_minigrid_data()

        # Start inference stack (orchestrator + nvidia/Orchestrator-8B)
        self._start_inference_stack()

        # Start scheduler service (background)
        self._start_scheduler()

        # Run enterApp startup procedure
        self._run_startup_commands()

        # Dismiss splash screen now that init is done
        try:
            splash = self.query_one("#splash", SplashScreen)
            splash.set_status("Ready!")
            self.set_timer(0.3, splash.dismiss)
        except Exception:
            pass  # Splash may not exist in tests

    def _start_state_client(self) -> None:
        """Start state client for thin client architecture.

        Attempts to:
        1. Load cached state from Postgres (instant)
        2. Connect to Engine in background
        3. Sync state updates via subscription

        This enables <100ms TUI startup while Engine connects in background.
        """
        import asyncio

        async def connect_and_sync():
            """Background task to connect and sync state."""
            from .client.state_client import get_state_client

            try:
                # Update status to connecting
                self._connection_status = ConnectionStatus.CONNECTING
                self._update_status()

                client = await get_state_client()
                kb_root = self.config.kb.root

                # Try to load cached state first
                state = await client.get_current_state(kb_root)
                if state:
                    self._state_generation = state.generation
                    # Update connection status based on source
                    if state.from_cache:
                        self._connection_status = ConnectionStatus.OFFLINE
                    else:
                        self._connection_status = ConnectionStatus.CONNECTED
                else:
                    # No cached state - check connection status
                    if client.is_connected:
                        self._connection_status = ConnectionStatus.CONNECTED
                    else:
                        self._connection_status = ConnectionStatus.OFFLINE

                # Register status change callback
                def on_status_change(status: ConnectionStatus):
                    self._connection_status = status
                    self.call_from_thread(self._update_status)

                client.on_status_change(on_status_change)

            except Exception as e:
                self.log.debug(f"State client connect failed: {e}")
                self._connection_status = ConnectionStatus.OFFLINE

            finally:
                self._update_status()

        asyncio.create_task(connect_and_sync())

    def _load_minigrid_data(self) -> None:
        """Load embedding data from Postgres for minigrid rendering.

        Called asynchronously after TUI mount. Loads raw embeddings and
        grid mappings, then populates GridManager cache.

        This enables minigrid views (Embed/Iso) to show real data instead
        of empty grids after instant startup.

        Also loads curvatures_raw for Iso view mode cycling.
        """
        import asyncio

        async def load_and_populate():
            """Background task to load embeddings and update minigrids."""
            try:
                from .storage.grid_state import load_full_grid_data_for_minigrids, load_current_state_fast
                from .core.projection import get_grid_manager

                kb_root = self.config.kb.root

                # Load curvatures_raw from cached state for Iso view
                cached = await load_current_state_fast(kb_root)
                if cached and cached.curvatures_raw:
                    self.state.curvatures_raw = cached.curvatures_raw
                    self.log.info(f"Loaded {len(cached.curvatures_raw)} curvatures for Iso view")

                grid_data = await load_full_grid_data_for_minigrids(kb_root)

                if grid_data is not None and grid_data.raw_embeddings is not None:
                    # Populate GridManager cache
                    grid_manager = get_grid_manager()
                    grid_manager.set_cached_data(grid_data)

                    # Update minigrids - we're in Textual's event loop so call directly
                    self._update_minigrids()
                    # Force refresh to ensure visual update
                    self.refresh()

                    self.log.info(
                        f"Minigrid data loaded: {len(grid_data.grid_to_embedding)} mappings"
                    )
                else:
                    self.log.debug("No embedding data available for minigrids")

            except Exception as e:
                self.log.debug(f"Minigrid data load failed: {e}")

        asyncio.create_task(load_and_populate())

    def _start_inference_stack(self) -> None:
        """Start inference orchestrator and default model (nvidia/Orchestrator-8B).

        Creates background task with progress tracking.
        IMPORTANT: Defers heavy imports to async context for instant startup.
        """
        import asyncio
        from datetime import datetime
        from .core.state import BackgroundTask

        # Create background task
        task = BackgroundTask(
            id="inference_startup",
            name="Starting nvidia/Orchestrator-8B",
            status="running",
            started_at=datetime.now(),
        )
        self.state.background_tasks.append(task)

        async def start_with_progress():
            """Start inference stack with progress updates."""
            # Defer heavy import to async context (get_inference_manager() takes ~500ms)
            from .inference.manager import get_inference_manager
            manager = get_inference_manager()

            def update_progress(task_name: str, progress: float, message: str):
                """Update background task progress."""
                task.progress = progress
                task.message = message
                # Force refresh of think panel if visible
                try:
                    think = self.query_one("#think-panel", ThinkPanel)
                    think.refresh()
                except Exception:
                    pass

            try:
                success = await manager.ensure_orchestrator_running(update_progress)

                if success:
                    task.status = "completed"
                    task.progress = 1.0
                    task.message = "nvidia/Orchestrator-8B ready"
                    task.completed_at = datetime.now()
                else:
                    task.status = "failed"
                    task.error = "Failed to start fast endpoint"
                    task.completed_at = datetime.now()

            except Exception as e:
                import logging
                task.status = "failed"
                task.error = str(e)
                task.completed_at = datetime.now()
                logging.getLogger(__name__).exception("Inference stack startup failed")

        asyncio.create_task(start_with_progress())

    def _start_scheduler(self) -> None:
        """Start the scheduler service for background inference.

        IMPORTANT: Defers heavy imports to async context for instant startup.
        """
        import asyncio

        async def start_scheduler():
            try:
                # Defer heavy import to async context (get_scheduler_service() takes ~500ms)
                from .inference.scheduler import get_scheduler_service
                service = get_scheduler_service()
                await service.start()
            except ImportError:
                pass  # Scheduler not available

        asyncio.create_task(start_scheduler())

    def _apply_center_panel_mode(self) -> None:
        """Apply center panel mode visibility from state.

        During engine initialization, automatically shows InitPanel.
        After initialization completes, respects the configured mode.
        """
        graph_wrapper = self.query_one("#graph-wrapper", Vertical)
        think = self.query_one("#think-panel", ThinkPanel)
        evolution = self.query_one("#evolution-panel", EvolutionPanel)
        init_panel = self.query_one("#init-panel", InitPanel)
        observe_panel = self.query_one("#observe-panel", ObservePanel)

        # During initialization, override to show InitPanel
        if not self.state.initialization_state.is_ready:
            self.state.center_panel_mode = CenterPanelMode.INIT

        mode = self.state.center_panel_mode

        # Hide all first
        graph_wrapper.add_class("hidden")
        think.add_class("hidden")
        evolution.add_class("hidden")
        init_panel.add_class("hidden")
        observe_panel.add_class("hidden")

        # Show the active one
        if mode == CenterPanelMode.INIT:
            init_panel.remove_class("hidden")
        elif mode == CenterPanelMode.GRAPH:
            graph_wrapper.remove_class("hidden")
        elif mode == CenterPanelMode.THINK:
            think.remove_class("hidden")
        elif mode == CenterPanelMode.EVOLUTION:
            evolution.remove_class("hidden")
        elif mode == CenterPanelMode.OBSERVE:
            observe_panel.remove_class("hidden")
        # else: NONE - all stay hidden

    def _run_startup_commands(self) -> None:
        """Execute startup commands from HOCON config.

        Like devenv's enterShell, this runs a sequence of commands
        when the app starts. Profile-specific commands allow for
        different startup behaviors per environment.
        """
        startup = self.config.startup
        content = self.query_one("#info-panel", InfoPanel)

        # Run each startup command
        commands_run = []
        for cmd in startup.commands:
            # Execute command (silently)
            self._execute_command(cmd)
            commands_run.append(cmd)

        # Show situational awareness summary if enabled
        if startup.show_situational:
            self._show_situational_summary(commands_run)

    def _show_situational_summary(self, commands_run: list[str]) -> None:
        """Display situational awareness summary on startup.

        Loads and displays the most recent thought document from scratch/
        instead of generating new thoughts (the engine generates thoughts
        via scheduled cognition cycles).

        Falls back to a simple welcome message if no thought notes exist.
        """
        import asyncio

        content = self.query_one("#info-panel", InfoPanel)
        editor = self.query_one("#note-editor", NoteEditor)

        # Log startup event
        asyncio.create_task(
            log_activity(
                ActivityType.STARTUP,
                profile_name=self.config.profile,
                domain=self.state.domain,
                details={"commands": commands_run},
            )
        )

        # Load and display the most recent thought note
        async def load_recent_thought():
            from datetime import datetime

            # Start session (for handoff tracking)
            session_manager = get_session_manager(self.config.profile)
            await session_manager.start_session(domain=self.state.domain)

            # Find the most recent thought note in scratch/
            scratch_path = Path(self.config.kb.scratch)
            recent_thought = self._find_most_recent_thought(scratch_path)

            if recent_thought:
                try:
                    # Open in editor (center panel)
                    editor.remove_class("hidden")
                    editor.open_note(str(recent_thought))

                    # Refresh file tree
                    file_tree = self.query_one("#file-tree", FileTree)
                    file_tree.refresh_tree()

                    # Show brief info in content panel
                    rel_path = recent_thought.relative_to(scratch_path)
                    content.show_file(
                        "startup.md",
                        f"# Session Started\n\n"
                        f"**Recent thought:** `{rel_path}`\n\n"
                        f"*Thoughts are generated by the engine. Use `/thoughts` to trigger manually.*"
                    )
                except Exception:
                    # Fallback: show in content panel
                    note_content = recent_thought.read_text()
                    content.show_file(recent_thought.name, note_content)
            else:
                # No thought notes exist yet - show welcome
                now = datetime.now()
                content.show_file(
                    "startup.md",
                    f"# Welcome to Gaius\n\n"
                    f"**Profile:** {self.config.profile}\n"
                    f"**Domain:** {self.state.domain or 'open'}\n"
                    f"**Time:** {now.strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"*No thought notes found. The engine will generate thoughts periodically.*\n"
                    f"*Use `/thoughts` to trigger cognition manually.*"
                )

        asyncio.create_task(load_recent_thought())

    def _find_most_recent_thought(self, scratch_path: Path) -> Path | None:
        """Find the most recent thought note in scratch/.

        Searches for files matching *_thought_*.md or *_thoughts.md patterns,
        sorted by modification time (most recent first).

        Args:
            scratch_path: Path to scratch/ directory

        Returns:
            Path to most recent thought note, or None if none found
        """
        if not scratch_path.exists():
            return None

        # Find all thought notes
        thought_files = []

        # Pattern 1: *_thought_*.md (new style with type suffix)
        thought_files.extend(scratch_path.rglob("*_thought_*.md"))

        # Pattern 2: *_thoughts.md (legacy style)
        thought_files.extend(scratch_path.rglob("*_thoughts.md"))

        if not thought_files:
            return None

        # Sort by modification time (newest first)
        thought_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        return thought_files[0]

    def on_command_submitted(self, event: CommandSubmitted) -> None:
        """Handle command submission."""
        cmd = event.command.strip()
        self._execute_command(cmd)

    def on_file_tree_selection(self, event: FileTreeSelection) -> None:
        """Handle file/agent selection from the tree."""
        data = event.data
        content = self.query_one("#info-panel", InfoPanel)
        editor = self.query_one("#note-editor", NoteEditor)
        graph_wrapper = self.query_one("#graph-wrapper", Vertical)
        graph = self.query_one("#graph-view", GraphView)

        if data["type"] == "file":
            filepath = data["path"]
            # Update graph view if visible
            if not graph_wrapper.has_class("hidden"):
                graph.update_for_file(filepath)

            # Check if it's an editable KB file (supported extension under archive/, current/, or scratch/)
            file_path = Path(filepath)
            path_parts = file_path.parts
            kb_dirs = ("archive", "current", "scratch")
            is_editable = any(d in path_parts for d in kb_dirs) and file_path.suffix.lower() in EDITABLE_EXTENSIONS
            if is_editable:
                # Open in editor
                editor.remove_class("hidden")
                editor.open_note(filepath)
            else:
                # Show in content panel (read-only)
                try:
                    text = Path(filepath).read_text()
                    content.show_file(Path(filepath).name, text)
                except Exception as e:
                    content.show_file("error.txt", f"Cannot read file: {e}")

        elif data["type"] == "agent":
            # Show agent status in content panel
            agent_info = f"""# Agent: {data['name']}

**Role:** {data.get('role', 'Unknown')}
**Status:** Active

## Last Output
{data.get('last', 'No recent output.')}

---
*Select agent file to interact*
"""
            content.show_file(f"{data['name'].lower()}.md", agent_info)

    def on_file_tree_highlight(self, event: FileTreeHighlight) -> None:
        """Handle cursor movement in FileTree - debounced graph update."""
        data = event.data

        # Only update for files
        if data.get("type") != "file":
            return

        filepath = data.get("path")
        if not filepath:
            return

        # Cancel any pending timer
        if self._graph_update_timer:
            self._graph_update_timer.stop()

        # Set new debounced timer (150ms)
        def update_graph() -> None:
            graph_wrapper = self.query_one("#graph-wrapper", Vertical)
            if not graph_wrapper.has_class("hidden"):
                # Try to select this node in the graph if it exists
                graph = self.query_one("#graph-view", GraphView)
                graph.select_node_by_path(filepath)

        self._graph_update_timer = self.set_timer(0.15, update_graph)

    def on_note_editor_file_renamed(self, event: NoteEditor.FileRenamed) -> None:
        """Handle file rename/move from editor."""
        # Refresh file tree to show new location
        file_tree = self.query_one("#file-tree", FileTree)
        file_tree.refresh_tree()

        # Update graph if visible
        graph_wrapper = self.query_one("#graph-wrapper", Vertical)
        if not graph_wrapper.has_class("hidden"):
            graph = self.query_one("#graph-view", GraphView)
            graph.scan_kb()  # Rescan for updated paths
            graph.update_for_file(event.new_path)

    def on_graph_view_node_highlighted(self, event: GraphView.NodeHighlighted) -> None:
        """Sync FileTree cursor, LinkPreview, and content when graph cursor moves."""
        # Update the LinkPreview widget
        link_preview = self.query_one("#link-preview", LinkPreview)
        self.log.info(f"NodeHighlighted: type={event.node_type}, path={event.filepath}, cmd={event.command}")
        link_preview.update_from_node(
            node_type=event.node_type,
            filepath=event.filepath,
            command=event.command,
        )
        self.log.info(f"LinkPreview updated: render={link_preview.render()}")

        # For document nodes, sync FileTree and show preview
        if event.filepath:
            file_tree = self.query_one("#file-tree", FileTree)
            file_tree.highlight_path(event.filepath)

            # Preview file content in InfoPanel
            content_panel = self.query_one("#info-panel", InfoPanel)
            filepath = event.filepath

            # Ensure .md extension
            if not filepath.endswith(".md"):
                filepath = f"{filepath}.md"

            path = Path(filepath)
            # Normalize relative paths to KB root
            if not path.is_absolute():
                kb_root = Path("build/dev")
                allowed_dirs = ("archive", "current", "scratch")
                parts = path.parts
                kb_parts = kb_root.parts

                if parts[:len(kb_parts)] != kb_parts:
                    if parts and parts[0] in allowed_dirs:
                        path = kb_root / path
                    else:
                        path = kb_root / path

            # Show preview if file exists
            if path.exists() and path.is_file():
                try:
                    text = path.read_text()
                    # Truncate for preview (first 500 chars or 20 lines)
                    lines = text.split("\n")[:20]
                    preview = "\n".join(lines)
                    if len(text) > len(preview):
                        preview += "\n\n... (truncated)"
                    content_panel.show_file(path.name, preview)
                except Exception:
                    pass  # Silently ignore read errors during preview
        elif event.command:
            # For action nodes, show command preview
            content_panel = self.query_one("#info-panel", InfoPanel)
            content_panel.show_file(
                "action.txt",
                f"Action Link\n\nCommand: {event.command}\n\nPress Enter to execute."
            )

    def on_graph_view_node_selected(self, event: GraphView.NodeSelected) -> None:
        """Open file when Enter pressed on graph node."""
        filepath = event.filepath
        editor = self.query_one("#note-editor", NoteEditor)
        content = self.query_one("#info-panel", InfoPanel)
        file_tree = self.query_one("#file-tree", FileTree)
        # KB root and allowed directories for file creation
        kb_root = Path("build/dev")
        allowed_dirs = ("archive", "current", "scratch")

        path = Path(filepath)

        # Ensure .md extension (wiki-links don't include extension)
        if not filepath.endswith(".md"):
            path = Path(f"{filepath}.md")

        # Normalize path: if relative, check if it's relative to KB root
        if not path.is_absolute():
            parts = path.parts
            kb_parts = kb_root.parts  # ('build', 'dev')

            # Check if path already starts with kb_root (e.g., "build/dev/current/...")
            if parts[:len(kb_parts)] == kb_parts:
                # Already has kb_root prefix, use as-is
                pass
            elif parts and parts[0] in allowed_dirs:
                # Path like "current/topics/kudu.md" - prepend kb_root
                path = kb_root / path
            else:
                # Try prepending kb_root for other relative paths
                path = kb_root / path

        # Resolve broken link via search if file doesn't exist
        if not path.exists():
            # Get the source file (the file containing the wiki link)
            graph_view = self.query_one("#graph-view", GraphView)
            source_file = graph_view.current_file

            # Derive link_text relative to kb_root (strip kb_root prefix if present)
            # e.g., path="build/dev/current/topics/kudu.md" -> link_text="current/topics/kudu"
            try:
                relative_path = path.relative_to(kb_root)
                link_text = str(relative_path).removesuffix(".md")
            except ValueError:
                # Path not under kb_root, use filename stem as fallback
                link_text = path.stem

            # Show status and trigger async resolution
            content.show_file(
                "resolving.txt",
                f"Resolving [[{link_text}]]...\n\nSearching KB and web for relevant content."
            )
            self.run_worker(
                self._resolve_broken_link(link_text, source_file, kb_root),
                name="resolve_link",
                exclusive=True,
            )
            return

        # Open in editor if it's an editable KB file (supported extension under archive/, current/, or scratch/)
        path_parts = path.parts
        kb_dirs = ("archive", "current", "scratch")
        is_editable = any(d in path_parts for d in kb_dirs) and path.suffix.lower() in EDITABLE_EXTENSIONS
        if is_editable:
            editor.remove_class("hidden")
            editor.open_note(str(path))
        else:
            # Show in content panel (read-only, e.g. archive/)
            try:
                text = path.read_text()
                content.show_file(path.name, text)
            except Exception as e:
                content.show_file("error.txt", f"Cannot read file: {e}")

    def on_graph_view_action_selected(self, event: GraphView.ActionSelected) -> None:
        """Execute slash command when Enter pressed on action link node.

        Action links like [action:/datasets info foo/bar] are parsed from
        documents and displayed in the link graph. When selected, the command
        is executed as if the user typed it in the command input.
        """
        command = event.command
        # The command already includes the leading slash
        self._execute_command(command)

    def on_init_panel_xb_auth_completed(
        self, event: InitPanel.XBAuthCompleted
    ) -> None:
        """Dismiss QR modal when XB OAuth completes.

        When the user completes OAuth via QR code on their device, the engine
        broadcasts XB_AUTH_COMPLETED. The InitPanel receives this event and
        posts an XBAuthCompleted message which bubbles up here to dismiss
        the QR modal automatically.
        """
        import logging
        logger = logging.getLogger(__name__)

        # Check if the current screen is a QRCodeModal
        if isinstance(self.screen, QRCodeModal):
            logger.info(
                f"XB auth completed for @{event.username}, dismissing QR modal"
            )
            self.screen.dismiss()

    def _execute_command(self, cmd: str) -> None:
        """Execute a slash command."""
        content = self.query_one("#info-panel", InfoPanel)

        if cmd.startswith("/"):
            cmd = cmd[1:]

        parts = cmd.split(maxsplit=1)
        command = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""

        if command == "help":
            self.action_show_help()
        elif command == "info":
            hint = get_position_hint(self.state.cursor_x, self.state.cursor_y)
            content.show_position_info(self.state.cursor_x, self.state.cursor_y, hint)
        elif command == "domain":
            if args:
                import asyncio

                old_domain = self.state.domain
                self.state.domain = args
                self._update_status()
                content.show_file("domain.txt", f"Domain set to: {args}")

                # Log domain change
                asyncio.create_task(
                    log_activity(
                        ActivityType.DOMAIN_CHANGE,
                        profile_name=self.config.profile,
                        domain=args,
                        details={"previous_domain": old_domain},
                    )
                )

                # Auto-trigger swarm if enabled
                if (
                    self.config.swarm.auto_trigger_on_domain
                    and self.config.swarm.enabled
                    and args != old_domain
                ):
                    content.show_file(
                        "domain.txt",
                        f"Domain set to: {args}\n\nAuto-triggering swarm analysis...",
                    )
                    self._run_swarm_analysis()
        elif command == "overlay":
            if args:
                try:
                    self.state.overlay_mode = OverlayMode(args.lower())
                    self._refresh_grid()
                    self._update_status()
                except ValueError:
                    content.show_file("error.txt", f"Unknown overlay: {args}")
            else:
                self.action_cycle_overlay()
        elif command == "iso":
            self._handle_iso_command(args, content)
        elif command == "view":
            if args:
                try:
                    self.state.view_mode = ViewMode(args.lower())
                    self._refresh_grid()
                    self._update_status()
                except ValueError:
                    content.show_file("error.txt", f"Unknown view: {args}")
            else:
                self.action_cycle_view()
        elif command == "init":
            # Initialize platform: full pipeline + cache (async with progress)
            content.show_file(
                "init.txt",
                "Starting full initialization...\n\n"
                "Running in background (2-5 minutes):\n"
                "1. Index KB documents\n"
                "2. Project to 19x19 grid (UMAP)\n"
                "3. Compute TDA features\n"
                "4. Cache for fast startup\n\n"
                "Press 'g' to toggle ThinkPanel for progress.\n"
                "The UI remains responsive during processing."
            )
            # Run async
            import asyncio
            asyncio.create_task(self._async_full_init())
        elif command == "reindex":
            # Reindex KB embeddings and refresh grid (async with progress)
            content.show_file(
                "reindex.txt",
                "Starting reindex...\n\n"
                "Running in background (2-5 minutes).\n"
                "Press 'g' to toggle ThinkPanel for progress.\n\n"
                "The UI remains responsive during processing."
            )
            # Run async
            import asyncio
            asyncio.create_task(self._async_refresh_from_embeddings())
        elif command == "tda":
            # Show TDA metrics
            try:
                from .core.tda import get_tda_manager
                tda_manager = get_tda_manager()
                metrics = tda_manager.get_metrics()
                tda_text = f"""# TDA Metrics

**H0 (Components):** {metrics.get('h0_count', 0)}
**H1 (Loops):** {metrics.get('h1_count', 0)}
**H2 (Voids):** {metrics.get('h2_count', 0)}
**Entropy:** {metrics.get('entropy', 0):.3f}
**Persistence Range:** {metrics.get('persistence_range', (0, 1))}

## H1 Cycles (Loops)
{len(metrics.get('h1_cycles', []))} 1-cycles detected

Use `/reindex` to refresh TDA from current KB.
"""
                content.show_file("tda.md", tda_text)
            except Exception as e:
                content.show_file("error.txt", f"TDA error: {e}")
        elif command == "swarm":
            # Run swarm analysis
            self._run_swarm_analysis(args if args else None)
        elif command == "agents":
            # Show agent status
            self._show_agent_status()
        elif command == "summary":
            # Generate daily summary
            self._show_daily_summary()
        elif command == "activity":
            # Show activity log
            self._show_activity()
        elif command == "search":
            # Search KB
            self._run_search(args)
        elif command == "research":
            # Research topic (web search + LLM synthesis)
            self._run_research(args)
        elif command == "ask":
            # General-purpose agentic query - /ask away!
            self._run_ask(args)
        elif command == "watch":
            # OTel telemetry observability
            self._run_watch(args)
        elif command == "engine":
            # Engine connectivity
            self._run_engine_command(args)
        elif command == "explain":
            # Explain grid view using local LLM
            self._explain_grid_view(args)
        elif command == "inference":
            # Manage inference stack (orchestrator, endpoints, models)
            self._handle_inference_command(args)
        elif command in ("evolve", "evo"):
            # Manage evolution daemon
            self._handle_evolve_command(args)
        elif command == "thoughts":
            # Trigger cognition or show recent thoughts
            self._handle_thoughts_command(args)
        elif command == "health":
            # Run comprehensive health check
            self._handle_health_command(args)
        elif command == "ambient":
            # Ambient computing cycles
            self._handle_ambient_command(args)
        elif command in ("x-bookmarks", "xb"):
            # X Bookmarks sync and management
            self._handle_x_bookmarks_command(args)
        elif command in ("datasets", "ds"):
            # HuggingFace dataset discovery
            self._handle_datasets_command(args)
        elif command in ("models", "m"):
            # HuggingFace model discovery
            self._handle_models_command(args)
        elif command in ("quit", "q", "exit"):
            self.exit()
        else:
            content.show_file("error.txt", f"Unknown command: {command}\n\nType /help for available commands.")


def main():
    """Entry point for the Gaius TUI."""
    import argparse
    import logging
    import os
    import sys

    # Suppress noisy startup logs for TUI (they corrupt the display)
    # Only show ERROR level by default, use GAIUS_LOG_LEVEL to override
    log_level = os.getenv("GAIUS_LOG_LEVEL", "ERROR")
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.ERROR),
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    # Suppress specific noisy loggers
    logging.getLogger("asyncpg").setLevel(logging.ERROR)
    logging.getLogger("grpc").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.ERROR)

    parser = argparse.ArgumentParser(description="Gaius - Spatial Intelligence Interface")
    parser.add_argument(
        "--profile", "-p",
        help="Configuration profile to load (default, cloudera, weathership)",
        default=None,
    )
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    app = GaiusApp(profile=args.profile)
    app.run()


if __name__ == "__main__":
    main()
