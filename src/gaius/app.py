"""Gaius TUI Application.

A CLI-first terminal interface for navigating complex, graph-oriented data domains.
Renders high-dimensional embeddings and topological structures onto a constrained grid.

Usage:
    uv run gaius                    # Pure UI mode
    uv run gaius-cli --cmd "/state" # CLI mode
"""

# Suppress huggingface tokenizers parallelism warnings BEFORE any imports
# These warnings occur when tokenizers are used after process forking
import os
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import Static, Header, Footer

from .core.state import AppState, ViewMode, OverlayMode, CenterPanelMode
from .core.config import get_config, GaiusConfig
from .core.telemetry import init_from_config as init_telemetry
from .core.projection import get_grid_manager, GridData
from .core.tda import get_tda_manager
from .core.activity import get_activity_tracker, log_activity, ActivityType
from .core.session import get_session_manager, SessionHandoff
from .agents import get_swarm_manager
from .agents.cognition import get_cognition_agent
from .awareness import generate_startup_report
from .widgets.grid import MainGrid
from .widgets.minigrid import MiniGrid
from .widgets.filetree import FileTree, FileTreeSelection, FileTreeHighlight
from .widgets.content import ContentPanel
from .widgets.command import CommandInput, CommandSubmitted
from .widgets.location import LocationIndicator
from .widgets.note_editor import NoteEditor
from .widgets.graph_view import GraphView
from .widgets.think_panel import ThinkPanel
from .widgets.evolution_panel import EvolutionPanel
from .static import (
    GRID_DATA,
    AGENT_DATA,
    DEATH_LOOPS,
    TDA_METRICS,
    get_minigrid_data,
    get_position_hint,
    generate_explanation,
)


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
        overflow: hidden;
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

    /* Graph view (wiki-link visualization) - 19x19 borderless grid */
    #graph-view {
        width: 40;
        height: 21;
        margin-left: 1;
        overflow: hidden;
    }

    #graph-view.hidden {
        display: none;
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
        background: $primary-darken-3;
        color: $text;
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

    ContentPanel {
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
    ContentPanel:focus {
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
        init_telemetry(self.config)  # Initialize OpenTelemetry
        self.state = AppState()
        self._graph_update_timer: Timer | None = None
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
        1. Load from cache (instant)
        2. If KB has content but no cache, schedule auto-init
        3. Fall back to static test data (fresh install)
        """
        # Try to load from cache first (fast)
        if self._try_load_cached_state():
            return

        # Check if KB has real content - if so, schedule auto-init
        if self._kb_has_content():
            self._schedule_auto_init()
            # Use minimal placeholder until init completes
            self.state.black_stones = []
            self.state.white_stones = []
            self.state.allocations = {}
            self.state.h1_cycles = []
            self.state.tda_entropy = 0.0
            return

        # Fall back to static test data (fresh install with empty KB)
        self.state.black_stones = GRID_DATA["black"]
        self.state.white_stones = GRID_DATA["white"]
        self.state.allocations = GRID_DATA["alloc"]
        self.state.h1_cycles = DEATH_LOOPS
        self.state.tda_entropy = TDA_METRICS["entropy"]

        # Load agent positions
        for agent in AGENT_DATA:
            self.state.agent_positions.append((
                agent["name"],
                agent["pos"][0],
                agent["pos"][1],
                agent["color"],
            ))

        # Set some candidates
        self.state.candidates = [(3, 3), (15, 15), (10, 10), (5, 14), (14, 5)]

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
            content = self.query_one("#content-panel", ContentPanel)
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

    def _try_load_cached_state(self) -> bool:
        """Try to load cached grid/TDA state.

        Returns:
            True if cache was loaded successfully
        """
        try:
            from .core.cache import load_cached_state, check_cache_validity

            # Check if cache is valid for current config
            if not check_cache_validity(
                self.config.kb.root,
                self.config.vector_store.embedding_model,
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

            # Apply cached TDA features
            self.state.h1_cycles = [dl.to_tuple() for dl in tda_features.h1_cycles]
            self.state.h2_voids = [v.to_tuple() for v in tda_features.h2_voids]
            self.state.tda_entropy = tda_features.entropy

            # Compute risk map from cached TDA
            if grid_data.embedding_to_grid and tda_features.risk_scores:
                self._compute_risk_map(tda_features, grid_data.embedding_to_grid)

            # Compute geometry from cached embeddings (for Iso view)
            if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) >= 15:
                try:
                    import asyncio
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
                except Exception as e:
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

        except Exception:
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

            # Try to compute TDA on 768-dim embeddings (not 2D projections)
            try:
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
                self.config.vector_store.embedding_model,
                self.config.tda.projection_method,
            )

            # Step 5: Apply to UI state
            self.state.black_stones = grid_data.document_positions
            self.state.white_stones = grid_data.cluster_centers
            self.state.allocations = grid_data.allocations

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

            try:
                from .inference.search import get_vector_search
                from .core.cache import save_cached_state
                import numpy as np

                task.message = "Step 1/5: Indexing KB documents..."
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
                    self.config.vector_store.embedding_model,
                    self.config.tda.projection_method,
                )

                # Apply to state
                self.state.black_stones = grid_data.document_positions
                self.state.white_stones = grid_data.cluster_centers
                self.state.allocations = grid_data.allocations
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
                # Restore stderr
                sys.stderr = old_stderr

        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, run_init)

        # Show result
        content = self.query_one("#content-panel", ContentPanel)
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

                # Refresh TDA on 768-dim embeddings (not 2D projections)
                tda_features = None
                try:
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
                            self.config.vector_store.embedding_model,
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

                # Refresh TDA
                task.message = "Step 3/4: Computing TDA features (H0/H1/H2)..."
                task.progress = 0.6

                tda_features = None
                try:
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
                            self.config.vector_store.embedding_model,
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
        content = self.query_one("#content-panel", ContentPanel)
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

        content = self.query_one("#content-panel", ContentPanel)
        domain = domain_override or self.state.domain

        # Update domain if override provided
        if domain_override:
            self.state.domain = domain_override
            self._update_status()

        # Show starting message
        content.show_file("swarm.txt", f"Running swarm analysis on: {domain}\n\nAgents: Leader, Risk, Optimizer, Planner, Critic, Executor, Adversary\n\nPlease wait...")

        # Run swarm asynchronously
        async def run_swarm():
            from .agents import run_swarm_round
            return await run_swarm_round(domain)

        try:
            # Run in event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule as task
                asyncio.create_task(self._complete_swarm_analysis(domain))
            else:
                result = loop.run_until_complete(run_swarm())
                self._apply_swarm_results(result)
        except Exception as e:
            content.show_file("error.txt", f"Swarm error: {e}")

    async def _complete_swarm_analysis(self, domain: str) -> None:
        """Complete swarm analysis asynchronously."""
        from .agents import run_swarm_round

        try:
            result = await run_swarm_round(domain)
            self._apply_swarm_results(result)
        except Exception as e:
            content = self.query_one("#content-panel", ContentPanel)
            content.show_file("error.txt", f"Swarm error: {e}")

    def _apply_swarm_results(self, result) -> None:
        """Apply swarm results to state and UI."""
        import asyncio

        content = self.query_one("#content-panel", ContentPanel)
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
            "",
            "## Agent Responses",
            "",
        ]

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

        content.show_file("swarm-result.md", "\n".join(lines))
        self._refresh_grid()
        self._update_status()

    def _show_agent_status(self) -> None:
        """Show current agent positions and status."""
        content = self.query_one("#content-panel", ContentPanel)

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

        content = self.query_one("#content-panel", ContentPanel)
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

                content.show_file("summary.md", note.to_markdown())

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

        content = self.query_one("#content-panel", ContentPanel)

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
        """Explain current grid view using local LLM with differential geometry.

        Args:
            args: Optional arguments: [position] [--no-save]
                  position: Go notation like K10 (default: cursor position)
                  --no-save: Don't save explanation to KB (default: save)
        """
        import asyncio
        from datetime import datetime
        from pathlib import Path
        from .inference.llm import explain_position, ExplanationContext
        from .core.projection import get_grid_manager
        from .core.tda import get_tda_manager
        from .core.minigrids import get_embed_view, get_iso_view

        content = self.query_one("#content-panel", ContentPanel)
        think = self.query_one("#think-panel", ThinkPanel)
        editor = self.query_one("#note-editor", NoteEditor)
        file_tree = self.query_one("#file-tree", FileTree)

        # Parse args - save by default, --no-save to disable
        save_to_kb = "--no-save" not in args
        args = args.replace("--no-save", "").replace("--save", "").strip()

        async def generate():
            try:
                think.start_trace(
                    operation="explanation",
                    query="grid interpretation",
                    model="local LLM"
                )

                start_time = datetime.now()

                # Get grid data and TDA features from managers
                try:
                    grid_data = get_grid_manager().get_grid_data()
                    tda_manager = get_tda_manager()
                    tda_features = tda_manager._cached_features  # May be None
                except Exception as e:
                    content.show_file("error.txt", f"Failed to get grid data: {e}")
                    think.clear_active()
                    return

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

                # Get document at cursor (if any)
                document_title = None
                document_path = None
                point_idx = grid_data.grid_to_embedding.get((cx, cy))
                if point_idx is not None and point_idx < len(grid_data.points):
                    point = grid_data.points[point_idx]
                    document_title = point.title
                    document_path = point.path

                # Extract geometric features (differential geometry)
                curvature = None
                gradient_x = None
                gradient_y = None
                divergence = None

                if self.state.curvature_map and cy < len(self.state.curvature_map):
                    if cx < len(self.state.curvature_map[cy]):
                        curvature = self.state.curvature_map[cy][cx]

                # Find gradient at cursor position
                if self.state.gradient_field:
                    for entry in self.state.gradient_field:
                        if len(entry) == 4 and entry[0] == cx and entry[1] == cy:
                            gradient_x = entry[2]
                            gradient_y = entry[3]
                            break

                if self.state.divergence_map and cy < len(self.state.divergence_map):
                    if cx < len(self.state.divergence_map[cy]):
                        divergence = self.state.divergence_map[cy][cx]

                # Extract TDA features
                tda_entropy = tda_features.entropy if tda_features else None
                h0_count = tda_features.h0_count if tda_features else None
                h1_count = tda_features.h1_count if tda_features else None
                h2_count = tda_features.h2_count if tda_features else None

                # Risk score at cursor
                risk_score = None
                if tda_features and point_idx is not None:
                    if point_idx < len(tda_features.risk_scores):
                        risk_score = tda_features.risk_scores[point_idx]

                # Find nearby documents (3x3 neighborhood)
                nearby_documents = []
                for dy in [-1, 0, 1]:
                    for dx in [-1, 0, 1]:
                        if dx == 0 and dy == 0:
                            continue
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < 19 and 0 <= ny < 19:
                            neighbor_idx = grid_data.grid_to_embedding.get((nx, ny))
                            if neighbor_idx is not None and neighbor_idx < len(grid_data.points):
                                nearby_documents.append(grid_data.points[neighbor_idx].title)

                # Get mini-grid data for visual descriptions
                embed_grid = None
                iso_grid = None
                embed_data = get_embed_view(grid_data, cx, cy)
                embed_grid = embed_data.grid

                curvatures = getattr(self.state, 'curvatures_raw', None)
                iso_data = get_iso_view(grid_data, curvatures, cx, cy)
                iso_grid = iso_data.grid

                # Create explanation context
                ctx = ExplanationContext(
                    cursor_x=cx,
                    cursor_y=cy,
                    document_title=document_title,
                    document_path=document_path,
                    curvature=curvature,
                    gradient_x=gradient_x,
                    gradient_y=gradient_y,
                    divergence=divergence,
                    tda_entropy=tda_entropy,
                    h0_count=h0_count,
                    h1_count=h1_count,
                    h2_count=h2_count,
                    risk_score=risk_score,
                    view_mode=self.state.view_mode.value,
                    overlay_mode=self.state.overlay_mode.value,
                    grid_coverage=grid_data.coverage,
                    total_documents=grid_data.n_documents,
                    nearby_documents=nearby_documents if nearby_documents else None,
                    embed_grid=embed_grid,
                    iso_grid=iso_grid,
                )

                # Generate explanation using new LLM interface
                explanation = await explain_position(ctx)

                # Strip thinking tags if present
                if '<think>' in explanation and '</think>' in explanation:
                    explanation = explanation.split('</think>')[-1].strip()

                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                # Convert coordinates to Go notation
                col = chr(ord('A') + cx + (1 if cx >= 8 else 0))
                position_str = f"{col}{19 - cy}"

                # Build output with geometric context
                output = [
                    f"# Grid Explanation: {position_str}",
                    "",
                    f"**Position:** {position_str} ({cx}, {cy})",
                    f"**Document:** {document_title or 'Empty cell'}",
                    f"**View:** {self.state.view_mode.value}",
                    f"**Overlay:** {self.state.overlay_mode.value}",
                    "",
                ]

                # Add geometric features summary
                if curvature is not None:
                    output.append("## Differential Geometry")
                    output.append("")
                    output.append(f"- **Ricci curvature κ:** {curvature:.3f}")
                    if gradient_x is not None and gradient_y is not None:
                        import math
                        mag = math.sqrt(gradient_x**2 + gradient_y**2)
                        output.append(f"- **Gradient magnitude:** {mag:.3f}")
                    if divergence is not None:
                        output.append(f"- **Divergence:** {divergence:.3f}")
                    output.append("")

                output.extend([
                    "## LLM Interpretation",
                    "",
                    explanation,
                ])

                # Save to KB if requested
                kb_path = None
                if save_to_kb:
                    from .core.kb_capture import ExplainCapture

                    capture = ExplainCapture(
                        position=position_str,
                        x=cx,
                        y=cy,
                        document_title=document_title,
                        document_path=document_path,
                        nearby_documents=nearby_documents[:8],
                        curvature=curvature,
                        gradient=(gradient_x, gradient_y) if gradient_x is not None else None,
                        risk_score=risk_score,
                        h0_count=h0_count or 0,
                        h1_count=h1_count or 0,
                        h2_count=h2_count or 0,
                        tda_entropy=tda_entropy or 0.0,
                        embed_grid=embed_grid,
                        iso_grid=iso_grid,
                        grid_coverage=grid_data.coverage,
                        total_documents=grid_data.n_documents,
                        view_mode=self.state.view_mode.value,
                        overlay_mode=self.state.overlay_mode.value,
                        explanation=explanation,
                        model="local LLM",
                        elapsed_ms=duration_ms,
                    )

                    scratch_root = Path("build/dev/scratch")
                    kb_path = capture.save_to_kb(scratch_root)
                    output.extend([
                        "",
                        f"---",
                        f"*Saved to: {kb_path}*",
                    ])

                    # Open the saved note in the editor
                    editor.remove_class("hidden")
                    editor.open_note(str(kb_path))

                    # Refresh file tree to show the new note
                    file_tree.refresh_tree()

                content.show_file("explain.md", "\n".join(output))

                # Record trace
                summary = f"Generated explanation in {duration_ms}ms"
                if kb_path:
                    summary += f" (saved to {kb_path.name})"
                think.complete_trace(
                    operation="explanation",
                    query="grid interpretation",
                    summary=summary,
                    tokens=0,
                    sources=1,
                    duration_ms=duration_ms,
                )

            except Exception as e:
                import traceback
                think.clear_active()
                error_detail = traceback.format_exc()
                content.show_file(
                    "error.txt",
                    f"Explanation failed: {e}\n\n"
                    f"Make sure optillm/vLLM is running.\n\n"
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
        from .inference.orchestrator import ProcessStatus

        content = self.query_one("#content-panel", ContentPanel)

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

        content = self.query_one("#content-panel", ContentPanel)

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

                    # Use engine client (agent-first architecture)
                    if use_engine_proxy():
                        orch = await get_orchestrator_proxy()
                        result = await orch.clean_start(endpoints)
                    else:
                        import logging
                        logging.getLogger(__name__).warning("LEGACY_FALLBACK: /evolve start bypassing engine - tech debt")
                        from .inference.orchestrator import get_orchestrator
                        orchestrator = get_orchestrator()
                        result = await orchestrator.clean_start(endpoints)

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

                    agent_id = subargs if subargs else None
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

        content = self.query_one("#content-panel", ContentPanel)
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
            # Trigger self-observation
            content.show_file("thoughts.md", "# Self-Observation\n\n*Generating self-observation thoughts...*")

            async def run_self_observation():
                try:
                    cognition = get_cognition_agent(self.config.profile)
                    context = await cognition._gather_context()
                    context.active_thoughts = await cognition.get_active_thoughts(limit=20)

                    thoughts = await cognition._observe_own_thoughts(context)
                    for thought in thoughts:
                        await cognition._save_thought(thought)

                    if thoughts:
                        # Open the most recent thought note
                        scratch_path = Path(self.config.kb.scratch)
                        recent = self._find_most_recent_thought(scratch_path)
                        if recent:
                            editor.remove_class("hidden")
                            editor.open_note(str(recent))

                        content.show_file(
                            "thoughts.md",
                            f"# Self-Observation Complete\n\n"
                            f"**Generated:** {len(thoughts)} self-observation thoughts\n\n"
                            f"*Thoughts about own thought patterns have been recorded.*"
                        )
                    else:
                        content.show_file("thoughts.md", "# Self-Observation\n\n*No new self-observations generated.*")

                except Exception as e:
                    content.show_file("error.txt", f"Self-observation failed: {e}")

            asyncio.create_task(run_self_observation())

        elif subcmd == "audit":
            # Trigger engine audit
            content.show_file("thoughts.md", "# Engine Audit\n\n*Auditing engine health...*")

            async def run_audit():
                try:
                    cognition = get_cognition_agent(self.config.profile)
                    context = await cognition._gather_context()

                    thoughts = await cognition._audit_engine_health(context)
                    for thought in thoughts:
                        await cognition._save_thought(thought)

                    if thoughts:
                        # Open the most recent thought note
                        scratch_path = Path(self.config.kb.scratch)
                        recent = self._find_most_recent_thought(scratch_path)
                        if recent:
                            editor.remove_class("hidden")
                            editor.open_note(str(recent))

                        content.show_file(
                            "thoughts.md",
                            f"# Engine Audit Complete\n\n"
                            f"**Generated:** {len(thoughts)} audit observations\n\n"
                            f"*Engine health observations have been recorded.*"
                        )
                    else:
                        content.show_file("thoughts.md", "# Engine Audit\n\n*No audit observations generated.*")

                except Exception as e:
                    content.show_file("error.txt", f"Engine audit failed: {e}")

            asyncio.create_task(run_audit())

        else:
            content.show_file("error.txt", f"Unknown thoughts subcommand: {subcmd}\n\nUsage:\n  /thoughts          - Trigger cognition and show thoughts\n  /thoughts recent   - Show most recent thought\n  /thoughts self     - Trigger self-observation\n  /thoughts audit    - Trigger engine audit")

    def _trigger_cognition_and_show(self, content: "ContentPanel", editor: "NoteEditor") -> None:
        """Trigger a cognition cycle and show the resulting thought note."""
        import asyncio

        content.show_file("thoughts.md", "# Cognition\n\n*Generating thoughts...*")

        async def run_cognition():
            try:
                cognition = get_cognition_agent(self.config.profile)
                result = await cognition.think(
                    max_thoughts=self.config.cognition.greeting_thoughts,
                    trigger_reason="manual",
                )

                # Open the most recent thought note
                scratch_path = Path(self.config.kb.scratch)
                recent = self._find_most_recent_thought(scratch_path)

                if recent:
                    editor.remove_class("hidden")
                    editor.open_note(str(recent))

                    # Refresh file tree
                    file_tree = self.query_one("#file-tree", FileTree)
                    file_tree.refresh_tree()

                content.show_file(
                    "thoughts.md",
                    f"# Cognition Complete\n\n"
                    f"**Generated:** {len(result.thoughts)} thoughts\n"
                    f"- Patterns: {result.patterns_detected}\n"
                    f"- Connections: {result.connections_found}\n"
                    f"- Curiosities: {result.curiosities_generated}\n"
                    f"- Self-observations: {result.self_observations}\n\n"
                    f"*Duration: {result.duration_ms}ms*"
                )

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

    def _handle_iso_command(self, args: str, content: "ContentPanel") -> None:
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

    def _iso_mode_description(self, mode: "IsoMode") -> str:
        """Get human-readable description for an Iso mode."""
        from .core.state import IsoMode
        descriptions = {
            IsoMode.CURVATURE: "Semantic boundaries via Ricci curvature",
            IsoMode.PERSISTENCE: "Topological complexity from H0+H1+H2",
            IsoMode.COMPLEXITY: "Semantic diversity within documents",
            IsoMode.BOUNDARY: "Documents forming semantic loops",
        }
        return descriptions.get(mode, mode.value)

    def _show_iso_info(self, content: "ContentPanel") -> None:
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

        content = self.query_one("#content-panel", ContentPanel)
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
                    match_type = "📄" if r["match"] == "filename" else "📝"
                    lines.append(f"- {match_type} **{r['path']}**")
                    lines.append(f"  {r['preview'][:100]}")
                    lines.append("")
            else:
                lines.append("*No results in KB.*")
                lines.append("")
                lines.append("Try `/research <topic>` to search the web and save to KB.")

            content.show_file("search.md", "\n".join(lines))

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

        content = self.query_one("#content-panel", ContentPanel)
        think = self.query_one("#think-panel", ThinkPanel)

        if not topic:
            content.show_file("error.txt", "Usage: /research <topic>\n\nSearches web and synthesizes results to KB.")
            return

        domain = self.state.domain or "general"
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
                content.show_file("research.md", result_text)

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

        content = self.query_one("#content-panel", ContentPanel)
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

                content.show_file("ask.md", result_text)

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

        content = self.query_one("#content-panel", ContentPanel)

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

        content = self.query_one("#content-panel", ContentPanel)

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

                        # Graph view (wiki-links) - hidden by default, 'g' cycles modes
                        yield GraphView(kb_root=self.config.kb.root, id="graph-view", classes="hidden")

                        # Think panel (reasoning traces) - hidden by default, 'g' cycles modes
                        yield ThinkPanel(self.state, id="think-panel", classes="hidden")

                        # Evolution panel (daemon monitoring) - hidden by default, 'g' cycles modes
                        yield EvolutionPanel(self.state, id="evolution-panel", classes="hidden")

                    # Note editor below the grids (hidden by default, Ctrl-N to show)
                    yield NoteEditor(id="note-editor", classes="hidden")

                # Right panel (content)
                with Vertical(id="right-panel"):
                    yield ContentPanel(self.state, id="content-panel")

        # Command input
        yield CommandInput(self.state, id="command-input")

        yield Footer()

    def _status_text(self) -> str:
        """Generate status bar text."""
        mode = self.state.view_mode.value.upper()
        overlay = self.state.overlay_mode.value
        coord = self.state.cursor_coord
        domain = self.state.domain[:20] + "..." if len(self.state.domain) > 23 else self.state.domain

        # Center panel mode indicator
        center_mode = self.state.center_panel_mode.value.upper()
        center_style = {
            "GRAPH": "blue",
            "THINK": "cyan",
            "EVOLUTION": "magenta",
            "NONE": "dim",
        }.get(center_mode, "white")

        return (
            f"[bold green]{mode}[/] │ "
            f"[yellow]{overlay}[/] │ "
            f"[{center_style}]{center_mode}[/] │ "
            f"[bold cyan]{coord}[/] │ "
            f"{domain} │ "
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
        """Update mini-grids based on cursor position with real TDA/UMAP data."""
        from .core.minigrids import get_real_minigrid_data
        from .core.projection import get_grid_manager
        from .core.tda import get_tda_manager

        # Get grid data and TDA features from managers
        grid_data = None
        tda_features = None
        try:
            grid_manager = get_grid_manager()
            grid_data = grid_manager.get_grid_data()
            tda_manager = get_tda_manager()
            tda_features = tda_manager._cached_features  # May be None if not computed yet

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
        try:
            if "right" in data and data["right"]:
                self.query_one("#minigrid-top", MiniGrid).update_data(data["right"])
            if "top" in data and data["top"]:
                self.query_one("#minigrid-bottom", MiniGrid).update_data(data["top"])
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
        content = self.query_one("#content-panel", ContentPanel)
        content.show_file("context.md", explanation)

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
        content = self.query_one("#content-panel", ContentPanel)
        help_text = """# Gaius Help

## Navigation
- **hjkl**: Move cursor (vim-style)
- **t**: Tenuki (jump to strategic point)

## Views
- **v**: Cycle view modes (Go/Pension/Swarm)
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
        graph = self.query_one("#graph-view", GraphView)
        if not graph.has_class("hidden"):
            graph.update_for_file(filepath)

        # Update status to show we're editing
        self._update_status()

        # Show confirmation in content panel
        content = self.query_one("#content-panel", ContentPanel)
        content.show_file("note.txt", f"New note: {filepath}\n\nVim keys: i=insert, ESC=normal, :q=close")

    def action_toggle_graph(self) -> None:
        """Cycle center panel mode: GRAPH → THINK → EVOLUTION → NONE → GRAPH."""
        graph = self.query_one("#graph-view", GraphView)
        think = self.query_one("#think-panel", ThinkPanel)
        evolution = self.query_one("#evolution-panel", EvolutionPanel)

        # Cycle to next mode
        new_mode = self.state.cycle_center_panel_mode()

        # Hide all first
        graph.add_class("hidden")
        think.add_class("hidden")
        evolution.add_class("hidden")

        # Update visibility based on mode
        if new_mode == CenterPanelMode.GRAPH:
            graph.remove_class("hidden")
            # Refresh graph content
            graph.scan_kb()
            editor = self.query_one("#note-editor", NoteEditor)
            if editor.current_file:
                graph.update_for_file(editor.current_file)
        elif new_mode == CenterPanelMode.THINK:
            think.remove_class("hidden")
            think.refresh()
        elif new_mode == CenterPanelMode.EVOLUTION:
            evolution.remove_class("hidden")
            # Trigger data refresh
            import asyncio
            asyncio.create_task(evolution.refresh_data())
        else:  # NONE
            # Force layout refresh when hiding all panels
            self.query_one("#grid-row").refresh(layout=True)

        # Update status to show current mode
        self._update_status()

    def action_show_evolution(self) -> None:
        """Show evolution panel directly."""
        graph = self.query_one("#graph-view", GraphView)
        think = self.query_one("#think-panel", ThinkPanel)
        evolution = self.query_one("#evolution-panel", EvolutionPanel)

        # Set mode directly to EVOLUTION
        self.state.center_panel_mode = CenterPanelMode.EVOLUTION

        # Hide others, show evolution
        graph.add_class("hidden")
        think.add_class("hidden")
        evolution.remove_class("hidden")

        # Trigger data refresh
        import asyncio
        asyncio.create_task(evolution.refresh_data())

        self._update_status()

    def action_quit_hint(self) -> None:
        """Show quit hint instead of immediately quitting."""
        content = self.query_one("#content-panel", ContentPanel)
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

        # Start inference stack (orchestrator + nvidia/Orchestrator-8B)
        self._start_inference_stack()

        # Start scheduler service (background)
        self._start_scheduler()

        # Run enterApp startup procedure
        self._run_startup_commands()

    def _start_inference_stack(self) -> None:
        """Start inference orchestrator and default model (nvidia/Orchestrator-8B).

        Creates background task with progress tracking.
        """
        import asyncio
        from datetime import datetime
        from .core.state import BackgroundTask
        from .inference.manager import get_inference_manager

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
                task.status = "failed"
                task.error = str(e)
                task.completed_at = datetime.now()
                self.log.exception("Inference stack startup failed")

        asyncio.create_task(start_with_progress())

    def _start_scheduler(self) -> None:
        """Start the scheduler service for background inference."""
        try:
            from .inference.scheduler import get_scheduler_service
            import asyncio

            service = get_scheduler_service()
            asyncio.create_task(service.start())
        except ImportError:
            pass  # Scheduler not available

    def _apply_center_panel_mode(self) -> None:
        """Apply center panel mode visibility from state."""
        graph = self.query_one("#graph-view", GraphView)
        think = self.query_one("#think-panel", ThinkPanel)

        mode = self.state.center_panel_mode
        if mode == CenterPanelMode.GRAPH:
            graph.remove_class("hidden")
            think.add_class("hidden")
        elif mode == CenterPanelMode.THINK:
            graph.add_class("hidden")
            think.remove_class("hidden")
        else:  # NONE
            graph.add_class("hidden")
            think.add_class("hidden")

    def _run_startup_commands(self) -> None:
        """Execute startup commands from HOCON config.

        Like devenv's enterShell, this runs a sequence of commands
        when the app starts. Profile-specific commands allow for
        different startup behaviors per environment.
        """
        startup = self.config.startup
        content = self.query_one("#content-panel", ContentPanel)

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

        content = self.query_one("#content-panel", ContentPanel)
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
                    f"**Domain:** {self.state.domain}\n"
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
        content = self.query_one("#content-panel", ContentPanel)
        editor = self.query_one("#note-editor", NoteEditor)
        graph = self.query_one("#graph-view", GraphView)

        if data["type"] == "file":
            filepath = data["path"]
            # Update graph view if visible
            if not graph.has_class("hidden"):
                graph.update_for_file(filepath)

            # Check if it's an editable KB file (.md under archive/, current/, or scratch/)
            path_parts = Path(filepath).parts
            kb_dirs = ("archive", "current", "scratch")
            is_editable = any(d in path_parts for d in kb_dirs) and filepath.endswith(".md")
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
            graph = self.query_one("#graph-view", GraphView)
            if not graph.has_class("hidden"):
                # Try to select this node in the graph if it exists
                graph.select_node_by_path(filepath)

        self._graph_update_timer = self.set_timer(0.15, update_graph)

    def on_note_editor_file_renamed(self, event: NoteEditor.FileRenamed) -> None:
        """Handle file rename/move from editor."""
        # Refresh file tree to show new location
        file_tree = self.query_one("#file-tree", FileTree)
        file_tree.refresh_tree()

        # Update graph if visible
        graph = self.query_one("#graph-view", GraphView)
        if not graph.has_class("hidden"):
            graph.scan_kb()  # Rescan for updated paths
            graph.update_for_file(event.new_path)

    def on_graph_view_node_highlighted(self, event: GraphView.NodeHighlighted) -> None:
        """Sync FileTree cursor and preview content when graph cursor moves."""
        file_tree = self.query_one("#file-tree", FileTree)
        file_tree.highlight_path(event.filepath)

        # Preview file content in ContentPanel
        content_panel = self.query_one("#content-panel", ContentPanel)
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

    def on_graph_view_node_selected(self, event: GraphView.NodeSelected) -> None:
        """Open file when Enter pressed on graph node."""
        filepath = event.filepath
        editor = self.query_one("#note-editor", NoteEditor)
        content = self.query_one("#content-panel", ContentPanel)
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

        # Create file if it doesn't exist (wiki-link creates on navigate)
        if not path.exists():
            # Validate path is within allowed KB directories
            try:
                rel_path = path.resolve().relative_to(kb_root.resolve())
                top_dir = rel_path.parts[0] if rel_path.parts else ""
                if top_dir not in allowed_dirs:
                    content.show_file(
                        "error.txt",
                        f"Cannot create file outside KB directories.\n\n"
                        f"Path: {filepath}\n"
                        f"Allowed: {', '.join(allowed_dirs)}"
                    )
                    return
            except ValueError:
                # Path is outside kb_root entirely
                content.show_file(
                    "error.txt",
                    f"Cannot create file outside KB root.\n\nPath: {filepath}"
                )
                return

            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
            # Refresh file tree to show new file
            file_tree.refresh_tree()
            content.show_file("created.txt", f"Created: {filepath}")

        # Open in editor if it's an editable KB file (.md under archive/, current/, or scratch/)
        path_parts = path.parts
        kb_dirs = ("archive", "current", "scratch")
        is_editable = any(d in path_parts for d in kb_dirs) and str(path).endswith(".md")
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

    def _execute_command(self, cmd: str) -> None:
        """Execute a slash command."""
        content = self.query_one("#content-panel", ContentPanel)

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
        elif command in ("quit", "q", "exit"):
            self.exit()
        else:
            content.show_file("error.txt", f"Unknown command: {command}\n\nType /help for available commands.")


def main():
    """Entry point for the Gaius TUI."""
    import argparse

    parser = argparse.ArgumentParser(description="Gaius - Spatial Intelligence Interface")
    parser.add_argument(
        "--profile", "-p",
        help="Configuration profile to load (default, cloudera, weathership)",
        default=None,
    )
    args = parser.parse_args()

    app = GaiusApp(profile=args.profile)
    app.run()


if __name__ == "__main__":
    main()
