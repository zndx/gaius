"""Gaius CLI - Non-interactive command mode.

Execute commands without starting the TUI. Useful for:
- Testing logic
- Scripting
- Batch operations
- CI/CD pipelines

Usage:
    # Single command
    uv run python -m gaius.cli --cmd "/info K10"

    # Multiple commands
    uv run python -m gaius.cli --cmd "/domain pension" --cmd "/overlay h1"

    # Pipe commands
    echo "/info K10" | uv run python -m gaius.cli

    # Output formats
    uv run python -m gaius.cli --cmd "/info" --format json
    uv run python -m gaius.cli --cmd "/info" --format text
"""

# Configure parallelism BEFORE any imports
import os

# Configure joblib to use threading instead of multiprocessing
# This avoids fork() conflicts with gRPC while preserving parallelism.
# Threading works well for NumPy/sklearn/UMAP since they release the GIL.
try:
    from joblib import parallel_config
    parallel_config(backend="threading", n_jobs=-1)
except ImportError:
    pass  # joblib not available yet

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import TextIO

from .core.state import AppState, ViewMode, OverlayMode, IsoMode
from .static import (
    GRID_DATA,
    AGENT_DATA,
    FILE_TREE,
    DEATH_LOOPS,
    TDA_METRICS,
    get_position_hint,
)


class GaiusCLI:
    """Non-interactive command executor."""

    def __init__(
        self,
        output: TextIO = sys.stdout,
        error: TextIO = sys.stderr,
        kb_root: Path | None = None,
    ):
        self.state = AppState()
        self.output = output
        self.error = error
        self.format = "text"
        self._load_config()
        # Allow overriding KB root (used for testing)
        if kb_root is not None:
            self.config.kb.root = str(kb_root)
        self._load_test_data()

    def _load_config(self) -> None:
        """Load configuration."""
        try:
            from .core.config import load_config
            self.config = load_config()
        except Exception:
            # Fallback minimal config
            from dataclasses import dataclass, field
            from typing import List

            @dataclass
            class StartupConfig:
                commands: List[str] = field(default_factory=list)

            @dataclass
            class KBConfig:
                root: str = "build/dev"

            @dataclass
            class MinimalConfig:
                profile: str = "default"
                startup: StartupConfig = field(default_factory=StartupConfig)
                kb: KBConfig = field(default_factory=KBConfig)

            self.config = MinimalConfig()

    def _run_async(self, coro):
        """Run an async coroutine synchronously.

        Handles both cases:
        - No event loop running: uses asyncio.run()
        - Event loop already running (e.g., in behave tests): uses run_until_complete()
        """
        try:
            loop = asyncio.get_running_loop()
            # We're inside an existing event loop - use nest_asyncio pattern
            # or create a new thread. For simplicity, use run_until_complete
            # on a new loop in a thread.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result(timeout=30)
        except RuntimeError:
            # No running event loop, safe to use asyncio.run
            return asyncio.run(coro)

    def _load_test_data(self) -> None:
        """Initialize with static test data."""
        self.state.black_stones = GRID_DATA["black"]
        self.state.white_stones = GRID_DATA["white"]
        self.state.allocations = GRID_DATA["alloc"]
        self.state.h1_cycles = DEATH_LOOPS
        self.state.tda_entropy = TDA_METRICS["entropy"]

        for agent in AGENT_DATA:
            self.state.agent_positions.append((
                agent["name"],
                agent["pos"][0],
                agent["pos"][1],
                agent["color"],
            ))

    def execute(self, cmd: str) -> dict:
        """Execute a command and return result dict."""
        from .core.telemetry import traced_command

        if cmd.startswith("/"):
            cmd = cmd[1:]

        parts = cmd.split(maxsplit=1)
        command = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""

        result = {"command": command, "args": args, "success": True, "data": {}}

        with traced_command(command, "execute") as span:
            try:
                if command == "info":
                    result["data"] = self._cmd_info(args)
                elif command == "goto":
                    result["data"] = self._cmd_goto(args)
                elif command == "domain":
                    result["data"] = self._cmd_domain(args)
                elif command == "overlay":
                    result["data"] = self._cmd_overlay(args)
                elif command == "iso":
                    result["data"] = self._cmd_iso(args)
                elif command == "view":
                    result["data"] = self._cmd_view(args)
                elif command == "state":
                    result["data"] = self._run_async(self._cmd_state(args))
                elif command == "agents":
                    result["data"] = self._cmd_agents()
                elif command == "grid":
                    result["data"] = self._cmd_grid()
                elif command == "help":
                    result["data"] = self._cmd_help()
                # Inference commands (async)
                elif command == "ask":
                    result["data"] = self._run_async(self._cmd_ask(args))
                elif command == "search":
                    result["data"] = self._run_async(self._cmd_search(args))
                elif command == "research":
                    result["data"] = self._run_async(self._cmd_research(args))
                elif command == "research!" or command == "research-eval":
                    result["data"] = self._run_async(self._cmd_research_eval(args))
                elif command == "eval":
                    result["data"] = self._run_async(self._cmd_eval(args))
                elif command == "eval-stats":
                    result["data"] = self._cmd_eval_stats()
                elif command == "technique":
                    result["data"] = self._cmd_technique(args)
                elif command == "kb":
                    result["data"] = self._cmd_kb(args)
                # Scheduler commands
                elif command == "scheduler" or command == "sched":
                    result["data"] = self._run_async(self._cmd_scheduler(args))
                elif command == "submit":
                    result["data"] = self._run_async(self._cmd_submit(args))
                elif command == "swarm":
                    result["data"] = self._run_async(self._cmd_swarm(args))
                # GPU Orchestrator commands
                elif command == "gpu" or command == "orch":
                    result["data"] = self._run_async(self._cmd_gpu(args))
                # Inference management (high-level)
                elif command == "inference" or command == "inf":
                    result["data"] = self._run_async(self._cmd_inference(args))
                elif command == "explain":
                    result["data"] = self._run_async(self._cmd_explain(args))
                # Evolution daemon commands
                elif command == "evolve" or command == "evo":
                    result["data"] = self._run_async(self._cmd_evolve(args))
                # Mini-grid data
                elif command == "minigrid" or command == "mg":
                    result["data"] = self._run_async(self._cmd_minigrid(args))
                # Reindex KB to Qdrant (via Engine or local)
                elif command == "reindex":
                    result["data"] = self._run_async(self._cmd_reindex(args))
                # Init - full initialization pipeline via Engine
                elif command == "init":
                    result["data"] = self._run_async(self._cmd_init(args))
                # Tenuki - find strategic jump point
                elif command == "tenuki":
                    result["data"] = self._cmd_tenuki(args)
                # Engine connectivity commands
                elif command == "engine":
                    result["data"] = self._run_async(self._cmd_engine(args))
                # OTel telemetry watching
                elif command == "watch":
                    result["data"] = self._run_async(self._cmd_watch(args))
                # Profile management
                elif command == "profile":
                    result["data"] = self._cmd_profile(args)
                # Project notes with bidirectional linking
                elif command == "project":
                    result["data"] = self._cmd_project(args)
                # Thoughts - cognition and pattern detection
                elif command == "thoughts":
                    result["data"] = self._run_async(self._cmd_thoughts(args))
                # Health check - comprehensive diagnostics
                elif command == "health":
                    result["data"] = self._run_async(self._cmd_health(args))
                # Self-healing - tiered recovery system
                elif command == "heal":
                    result["data"] = self._run_async(self._cmd_heal(args))
                # Model registry commands
                elif command == "model" or command == "models":
                    result["data"] = self._cmd_model(args)
                # Execute via Engine's CommandService (unified entry point)
                elif command == "exec":
                    result["data"] = self._run_async(self._cmd_exec(args))
                # AIOps - infrastructure health management with KB reports
                elif command == "aiops":
                    result["data"] = self._run_async(self._cmd_aiops(args))
                # MLOps - model lifecycle management with KB reports
                elif command == "mlops":
                    result["data"] = self._run_async(self._cmd_mlops(args))
                # FMEA - Failure Mode and Effects Analysis
                elif command == "fmea":
                    result["data"] = self._run_async(self._cmd_fmea(args))
                # Metaflow pipeline management
                elif command == "flow":
                    result["data"] = self._run_async(self._cmd_flow(args))
                # Fetch paper shortcut (alias for /flow run docling)
                elif command == "fetch":
                    result["data"] = self._run_async(self._cmd_fetch(args))
                else:
                    result["success"] = False
                    result["error"] = f"Unknown command: {command}"
            except Exception as e:
                if hasattr(span, "record_exception"):
                    span.record_exception(e)
                result["success"] = False
                result["error"] = str(e)

        return result

    def _cmd_info(self, args: str) -> dict:
        """Get info about a position."""
        if args:
            x, y = self._parse_coord(args)
        else:
            x, y = self.state.cursor_x, self.state.cursor_y

        hint = get_position_hint(x, y)
        coord = self._coord_string(x, y)

        return {
            "position": coord,
            "x": x,
            "y": y,
            "hint": hint,
            "allocation": self.state.allocations[y][x] if self.state.allocations else None,
            "has_black": (x, y) in self.state.black_stones,
            "has_white": (x, y) in self.state.white_stones,
        }

    def _cmd_goto(self, args: str) -> dict:
        """Move cursor to position."""
        if not args:
            raise ValueError("goto requires a position argument")
        x, y = self._parse_coord(args)
        self.state.cursor_x = x
        self.state.cursor_y = y
        return {"position": self._coord_string(x, y), "x": x, "y": y}

    def _cmd_domain(self, args: str) -> dict:
        """Set or get domain."""
        if args:
            self.state.domain = args
        return {"domain": self.state.domain}

    def _cmd_overlay(self, args: str) -> dict:
        """Set or cycle overlay mode."""
        if args:
            self.state.overlay_mode = OverlayMode(args.lower())
        else:
            self.state.cycle_overlay_mode()
        return {"overlay": self.state.overlay_mode.value}

    def _cmd_iso(self, args: str) -> dict:
        """Get or set Iso view mode.

        Usage:
            /iso              - Get current mode
            /iso <mode>       - Set mode (curvature, persistence, complexity, boundary)
            /iso cycle        - Cycle to next mode
            /iso info         - Get detailed feature info
        """
        from .core.iso_features import ISO_MODE_SYMBOLS

        if not args:
            symbol = ISO_MODE_SYMBOLS.get(self.state.iso_mode, "?")
            return {
                "mode": self.state.iso_mode.value,
                "symbol": symbol,
                "has_features": self.state.iso_features is not None,
            }

        parts = args.split()
        subcmd = parts[0].lower()

        if subcmd == "cycle":
            new_mode = self.state.cycle_iso_mode()
            symbol = ISO_MODE_SYMBOLS.get(new_mode, "?")
            return {"mode": new_mode.value, "symbol": symbol, "cycled": True}

        elif subcmd == "info":
            features = self.state.iso_features
            if features is None:
                return {
                    "mode": self.state.iso_mode.value,
                    "has_features": False,
                    "message": "IsoFeatures not computed. Run /reindex to compute.",
                }

            return {
                "mode": self.state.iso_mode.value,
                "has_features": True,
                "n_documents": features.n_documents,
                "embedding_type": features.embedding_type,
                "computation_time": features.computation_time,
                "n_diagrams": len(features.diagrams),
                "curvature_stats": {
                    "min": float(features.curvatures.min()),
                    "max": float(features.curvatures.max()),
                    "mean": float(features.curvatures.mean()),
                },
                "persistence_stats": {
                    "min": float(features.persistence.min()),
                    "max": float(features.persistence.max()),
                    "mean": float(features.persistence.mean()),
                },
                "complexity_stats": {
                    "min": float(features.complexity.min()),
                    "max": float(features.complexity.max()),
                    "mean": float(features.complexity.mean()),
                },
                "boundary_stats": {
                    "min": float(features.boundary.min()),
                    "max": float(features.boundary.max()),
                    "mean": float(features.boundary.mean()),
                },
            }

        else:
            # Try to set mode directly
            try:
                self.state.iso_mode = IsoMode(subcmd)
                symbol = ISO_MODE_SYMBOLS.get(self.state.iso_mode, "?")
                return {"mode": self.state.iso_mode.value, "symbol": symbol, "set": True}
            except ValueError:
                return {"error": f"Unknown Iso mode: {subcmd}", "valid_modes": [m.value for m in IsoMode]}

    def _cmd_view(self, args: str) -> dict:
        """Set or cycle view mode."""
        if args:
            self.state.view_mode = ViewMode(args.lower())
        else:
            self.state.cycle_view_mode()
        return {"view": self.state.view_mode.value}

    async def _cmd_state(self, args: str = "") -> dict:
        """Get or sync application state.

        Usage:
            /state              - Get current application state
            /state sync         - Load cached state from Postgres
            /state generation   - Get current generation number
            /state prefs [save] - Get or save UI preferences
            /state prune [n]    - Prune old snapshots (keep n, default 10)
        """
        parts = args.strip().split()
        subcmd = parts[0] if parts else ""

        if not subcmd:
            # Default: return local state
            return {
                "cursor": self._coord_string(self.state.cursor_x, self.state.cursor_y),
                "cursor_x": self.state.cursor_x,
                "cursor_y": self.state.cursor_y,
                "view_mode": self.state.view_mode.value,
                "overlay_mode": self.state.overlay_mode.value,
                "domain": self.state.domain,
                "tda_entropy": self.state.tda_entropy,
                "num_agents": len(self.state.agent_positions),
                "num_h1_cycles": len(self.state.h1_cycles),
                "num_h2_voids": len(self.state.h2_voids),
                "has_curvature_map": bool(self.state.curvature_map),
                "has_gradient_field": bool(self.state.gradient_field),
            }

        if subcmd == "sync":
            # Load cached state from Postgres
            return await self._cmd_state_sync()

        if subcmd == "generation" or subcmd == "gen":
            # Get current generation
            return await self._cmd_state_generation()

        if subcmd == "prefs" or subcmd == "preferences":
            # Get or save preferences
            save = "save" in parts[1:] if len(parts) > 1 else False
            return await self._cmd_state_prefs(save)

        if subcmd == "prune":
            # Prune old snapshots
            keep = int(parts[1]) if len(parts) > 1 else 10
            return await self._cmd_state_prune(keep)

        return {"error": f"Unknown state subcommand: {subcmd}"}

    async def _cmd_state_sync(self) -> dict:
        """Load cached state from Postgres for instant startup."""
        from .client.state_client import get_state_client

        client = await get_state_client()
        kb_root = self._get_kb_root()

        state = await client.get_current_state(kb_root)

        if not state:
            return {
                "status": "no_cached_state",
                "kb_root": kb_root,
                "message": "No cached state found. Run /reindex to populate.",
            }

        # Update self.state with geometry from loaded state
        if state.geometry and state.geometry.curvature_map:
            self.state.curvature_map = state.geometry.curvature_map
        if state.geometry and state.geometry.gradient_field:
            self.state.gradient_field = state.geometry.gradient_field

        return {
            "status": "loaded",
            "kb_root": kb_root,
            "snapshot_id": state.snapshot_id,
            "generation": state.generation,
            "n_documents": state.n_documents,
            "tda": {
                "h0_count": state.tda.h0_count,
                "h1_count": state.tda.h1_count,
                "h2_count": state.tda.h2_count,
                "entropy": state.tda.entropy,
            },
            "geometry": {
                "has_curvature_map": bool(state.geometry.curvature_map),
                "has_gradient_field": bool(state.geometry.gradient_field),
                "gradient_field_count": len(state.geometry.gradient_field) if state.geometry else 0,
            },
            "from_cache": state.from_cache,
            "connection_status": client.status.value,
        }

    async def _cmd_state_generation(self) -> dict:
        """Get current state generation number."""
        from .storage.grid_state import get_current_generation

        kb_root = self._get_kb_root()
        generation = await get_current_generation(kb_root)

        return {
            "kb_root": kb_root,
            "generation": generation,
        }

    async def _cmd_state_prefs(self, save: bool = False) -> dict:
        """Get or save UI preferences."""
        from .client.state_client import get_state_client, UIPreferences

        client = await get_state_client()

        if save:
            # Save current state to preferences
            prefs = UIPreferences(
                client_id="cli",
                cursor_x=self.state.cursor_x,
                cursor_y=self.state.cursor_y,
                view_mode=self.state.view_mode.value,
                overlay_mode=self.state.overlay_mode.value,
                domain=self.state.domain or "",
            )
            success = await client.save_preferences(prefs)
            return {
                "action": "saved",
                "success": success,
                "preferences": {
                    "cursor_x": prefs.cursor_x,
                    "cursor_y": prefs.cursor_y,
                    "view_mode": prefs.view_mode,
                    "overlay_mode": prefs.overlay_mode,
                    "domain": prefs.domain,
                },
            }
        else:
            # Load preferences
            prefs = await client.get_preferences("cli")
            if not prefs:
                return {"status": "no_preferences", "message": "No saved preferences found"}

            return {
                "action": "loaded",
                "preferences": {
                    "cursor_x": prefs.cursor_x,
                    "cursor_y": prefs.cursor_y,
                    "view_mode": prefs.view_mode,
                    "overlay_mode": prefs.overlay_mode,
                    "domain": prefs.domain,
                },
            }

    async def _cmd_state_prune(self, keep_count: int = 10) -> dict:
        """Prune old grid snapshots."""
        from .client.state_client import get_state_client

        client = await get_state_client()
        kb_root = self._get_kb_root()

        # First do a dry run
        dry_count, dry_ids = await client.prune_snapshots(
            kb_root, keep_count=keep_count, dry_run=True
        )

        if dry_count == 0:
            return {
                "action": "prune",
                "deleted_count": 0,
                "message": f"No snapshots to prune (keeping {keep_count})",
            }

        # Actually prune
        count, deleted_ids = await client.prune_snapshots(
            kb_root, keep_count=keep_count, dry_run=False
        )

        return {
            "action": "prune",
            "deleted_count": count,
            "deleted_ids": deleted_ids[:10],  # Only show first 10
            "kept_count": keep_count,
        }

    def _get_kb_root(self) -> str:
        """Get KB root from config."""
        return getattr(self.config, "kb_root", "build/dev")

    def _cmd_agents(self) -> dict:
        """List agents."""
        agents = []
        for name, x, y, color in self.state.agent_positions:
            agents.append({
                "name": name,
                "position": self._coord_string(x, y),
                "x": x,
                "y": y,
                "color": color,
            })
        return {"agents": agents}

    def _cmd_grid(self) -> dict:
        """Get grid representation."""
        grid_str = self._render_grid_ascii()
        return {"grid": grid_str}

    async def _cmd_minigrid(self, args: str) -> dict:
        """Get mini-grid data for a position.

        Usage:
            /minigrid [pos]       - Get from Postgres cache (fast)
            /minigrid [pos] live  - Trigger projection (slow)

        Returns:
            embed_grid: 9x9 embedding similarity around position
            iso_grid: 9x9 curvature-based elevation map
            grid_data_status: info about underlying data
        """
        from .core.projection import get_grid_manager
        from .core.minigrids import get_real_minigrid_data

        # Parse args
        parts = args.strip().split() if args else []
        use_live = "live" in parts
        pos_args = [p for p in parts if p != "live"]

        # Parse position
        if pos_args:
            cx, cy = self._parse_coord(" ".join(pos_args))
        else:
            cx, cy = self.state.cursor_x, self.state.cursor_y

        # Get grid data
        grid_data = None
        grid_data_status = {"source": "none"}

        if use_live:
            # Live projection (slow, triggers full recomputation)
            try:
                grid_manager = get_grid_manager()
                grid_data = grid_manager.get_grid_data()
                grid_data_status = {
                    "source": "live_projection",
                    "n_documents": grid_data.n_documents,
                    "coverage": grid_data.coverage,
                    "method": grid_data.method,
                    "has_embeddings": grid_data.raw_embeddings is not None,
                    "embedding_count": len(grid_data.raw_embeddings) if grid_data.raw_embeddings is not None else 0,
                    "grid_mappings": len(grid_data.grid_to_embedding),
                }
            except Exception as e:
                grid_data_status["error"] = str(e)
        else:
            # Load from Postgres cache (fast, ~100ms)
            try:
                from .storage.grid_state import load_full_grid_data_for_minigrids
                kb_root = self.config.kb.root
                grid_data = await load_full_grid_data_for_minigrids(kb_root)
                if grid_data:
                    grid_data_status = {
                        "source": "postgres_cache",
                        "n_documents": grid_data.n_documents,
                        "coverage": grid_data.coverage,
                        "method": grid_data.method,
                        "has_embeddings": grid_data.raw_embeddings is not None,
                        "embedding_count": len(grid_data.raw_embeddings) if grid_data.raw_embeddings is not None else 0,
                        "grid_mappings": len(grid_data.grid_to_embedding),
                    }
                else:
                    grid_data_status["error"] = "No cached state found"
            except Exception as e:
                grid_data_status["error"] = str(e)

        # Get curvatures from state
        curvatures = self.state.curvatures_raw if self.state.curvatures_raw else None

        # Get mini-grid data
        data = get_real_minigrid_data(
            grid_data=grid_data,
            curvatures=curvatures,
            cursor_x=cx,
            cursor_y=cy,
            iso_mode=self.state.iso_mode,
            iso_features=grid_data.iso_features if grid_data else None,
        )

        # Check if grids have any non-zero values
        def grid_has_data(grid: list[list[float]]) -> bool:
            return any(v > 0 for row in grid for v in row)

        return {
            "position": self._coord_string(cx, cy),
            "x": cx,
            "y": cy,
            "embed_grid": data.get("right", []),
            "embed_has_data": grid_has_data(data.get("right", [])),
            "iso_grid": data.get("top", []),
            "iso_has_data": grid_has_data(data.get("top", [])),
            "grid_data_status": grid_data_status,
            "curvatures_available": curvatures is not None,
        }

    async def _cmd_reindex(self, args: str = "") -> dict:
        """Reindex KB documents to Qdrant and refresh grid projection.

        Usage:
            /reindex           - Index via Engine with streaming progress (default)
            /reindex nostream  - Disable streaming (wait for completion)
            /reindex local     - Force local compute (bypass Engine)
            /reindex force     - Force full reindex even if up-to-date

        Returns:
            n_documents: Number of documents indexed
            coverage: Grid coverage percentage
            generation: State generation after reindex
        """
        import time

        parts = args.strip().split()

        # Parse options
        force = "force" in parts
        local = "local" in parts
        # Stream by default unless nostream is specified
        stream = "nostream" not in parts

        kb_root = self._get_kb_root()

        # Try Engine first (unless local explicitly requested)
        if not local:
            try:
                from .client.grpc_client import get_grpc_client

                client = await get_grpc_client()

                if stream:
                    # Streaming mode with progress updates
                    start_time = time.time()
                    last_progress = None
                    final_result = None

                    async for progress in client.reindex_with_progress(
                        kb_root=kb_root,
                        force=force,
                    ):
                        phase = progress.get("phase", "")
                        pct = progress.get("progress", 0.0)
                        msg = progress.get("message", "")
                        docs_done = progress.get("documents_processed", 0)
                        docs_total = progress.get("documents_total", 0)

                        # Progress bar visualization
                        bar_width = 30
                        filled = int(bar_width * pct)
                        bar = "█" * filled + "░" * (bar_width - filled)

                        # Print progress line (overwrite previous)
                        if docs_total > 0:
                            progress_line = f"\r[{bar}] {pct:5.1%} | {phase:10s} | {docs_done}/{docs_total} docs | {msg}"
                        else:
                            progress_line = f"\r[{bar}] {pct:5.1%} | {phase:10s} | {msg}"

                        # Truncate to terminal width and pad to overwrite previous
                        print(progress_line.ljust(100)[:100], end="", flush=True)
                        last_progress = progress

                        if phase in ("complete", "error"):
                            final_result = progress
                            break

                    print()  # Newline after progress bar

                    duration_ms = int((time.time() - start_time) * 1000)

                    if final_result and final_result.get("phase") == "error":
                        return {
                            "mode": "engine",
                            "success": False,
                            "kb_root": kb_root,
                            "error": final_result.get("message", "Unknown error"),
                            "duration_ms": duration_ms,
                        }

                    return {
                        "mode": "engine",
                        "success": True,
                        "kb_root": kb_root,
                        "n_documents": last_progress.get("documents_processed", 0) if last_progress else 0,
                        "message": last_progress.get("message", "") if last_progress else "",
                        "duration_ms": duration_ms,
                    }

                else:
                    # Non-streaming mode (wait for completion)
                    result = await client.call(
                        service="Init",
                        action="reindex",
                        params={
                            "kb_root": kb_root,
                            "client_id": "cli",
                            "force": force,
                        },
                        timeout=600.0,  # 10 minute timeout for full reindex
                    )

                    return {
                        "mode": "engine",
                        "success": result.get("success", False),
                        "kb_root": kb_root,
                        "n_documents": result.get("documents_indexed", 0),
                        "documents_skipped": result.get("documents_skipped", 0),
                        "generation": result.get("generation", 0),
                        "duration_ms": result.get("duration_ms", 0),
                        "message": result.get("message", ""),
                    }

            except Exception as e:
                # Engine not available or failed - fall through to local
                # Log warning and use local
                import logging
                logging.getLogger(__name__).warning(
                    f"Engine reindex failed ({e}), using local compute"
                )

        # Local fallback
        from .core.projection import get_grid_manager

        grid_manager = get_grid_manager()
        grid_data = grid_manager.reindex_and_project()

        return {
            "mode": "local",
            "success": True,
            "n_documents": grid_data.n_documents,
            "coverage": grid_data.coverage,
            "method": grid_data.method,
            "grid_mappings": len(grid_data.grid_to_embedding),
            "has_embeddings": grid_data.raw_embeddings is not None,
            "embedding_count": len(grid_data.raw_embeddings) if grid_data.raw_embeddings is not None else 0,
        }

    async def _cmd_init(self, args: str = "") -> dict:
        """Initialize KB: index, project, compute TDA, save to Postgres.

        This is the primary entry point for setting up a fresh Gaius instance
        or forcing a complete rebuild. After /init completes, the TUI should
        start fully populated in < 5 seconds by reading from Postgres cache.

        Usage:
            /init              - Initialize (skip if already done)
            /init force        - Force full re-initialization
            /init stream       - Stream progress updates (default: true)
            /init nostream     - Disable streaming (wait for completion)

        Pipeline:
        1. Scan KB for documents
        2. Compute ColNomic embeddings (GPU-accelerated)
        3. Project to 19x19 grid via UMAP
        4. Compute TDA features (H0/H1/H2)
        5. Save to Postgres (grid_snapshots + current_state)

        Returns:
            success: True if initialization succeeded
            n_documents: Number of documents indexed
            h0_count, h1_count, h2_count: TDA feature counts
            entropy: Persistence entropy
            generation: State generation number
            duration_ms: Total duration in milliseconds
        """
        import sys
        import time

        parts = args.strip().split()

        # Parse options
        force = "force" in parts
        # Stream by default unless nostream is specified
        stream = "nostream" not in parts

        kb_root = self._get_kb_root()

        try:
            from .client.grpc_client import get_grpc_client

            client = await get_grpc_client()

            if stream:
                # Streaming mode with progress updates
                start_time = time.time()
                last_progress = None
                final_result = None

                async for progress in client.init_with_progress(
                    kb_root=kb_root,
                    force=force,
                ):
                    phase = progress.get("phase", "")
                    pct = progress.get("progress", 0.0)
                    msg = progress.get("message", "")
                    docs_done = progress.get("documents_processed", 0)
                    docs_total = progress.get("documents_total", 0)

                    # Progress bar visualization
                    bar_width = 30
                    filled = int(bar_width * pct)
                    bar = "█" * filled + "░" * (bar_width - filled)

                    # Print progress line (overwrite previous)
                    if docs_total > 0:
                        progress_line = f"\r[{bar}] {pct:5.1%} | {phase:10s} | {docs_done}/{docs_total} docs | {msg}"
                    else:
                        progress_line = f"\r[{bar}] {pct:5.1%} | {phase:10s} | {msg}"

                    # Truncate to terminal width and pad to overwrite previous
                    print(progress_line.ljust(100)[:100], end="", flush=True)
                    last_progress = progress

                    if phase in ("complete", "error"):
                        final_result = progress
                        break

                print()  # Newline after progress bar

                duration_ms = int((time.time() - start_time) * 1000)

                if final_result and final_result.get("phase") == "error":
                    return {
                        "mode": "engine",
                        "success": False,
                        "kb_root": kb_root,
                        "error": final_result.get("message", "Unknown error"),
                        "duration_ms": duration_ms,
                    }

                return {
                    "mode": "engine",
                    "success": True,
                    "kb_root": kb_root,
                    "n_documents": last_progress.get("documents_processed", 0) if last_progress else 0,
                    "message": last_progress.get("message", "") if last_progress else "",
                    "duration_ms": duration_ms,
                }

            else:
                # Non-streaming mode (wait for completion)
                result = await client.call(
                    service="Init",
                    action="init",
                    params={
                        "kb_root": kb_root,
                        "client_id": "cli",
                        "force": force,
                    },
                    timeout=600.0,  # 10 minute timeout for full init
                )

                return {
                    "mode": "engine",
                    "success": result.get("success", False),
                    "kb_root": kb_root,
                    "n_documents": result.get("documents_indexed", 0),
                    "h0_count": result.get("h0_count", 0),
                    "h1_count": result.get("h1_count", 0),
                    "h2_count": result.get("h2_count", 0),
                    "entropy": result.get("entropy", 0.0),
                    "generation": result.get("generation", 0),
                    "duration_ms": result.get("duration_ms", 0),
                    "message": result.get("message", ""),
                }

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Init failed: {e}")
            return {
                "mode": "engine",
                "success": False,
                "kb_root": kb_root,
                "error": str(e),
            }

    def _cmd_tenuki(self, args: str) -> dict:
        """Find strategic jump point (tenuki) from current position.

        In Go, tenuki means 'playing elsewhere' - ignoring the local
        situation for a bigger play. This finds high-curvature regions
        (semantic boundaries) while avoiding recently visited areas.

        Usage:
            /tenuki [pos]  - Find tenuki from position (default: cursor)

        Returns:
            target: Recommended position to jump to
            score: Strategic interest score
            curvature: Curvature at target
            distance: Manhattan distance from current position
        """
        from .core.projection import get_grid_manager

        # Parse current position
        if args:
            cx, cy = self._parse_coord(args)
        else:
            cx, cy = self.state.cursor_x, self.state.cursor_y

        # Get grid data with embeddings
        grid_manager = get_grid_manager()
        grid_data = grid_manager.get_grid_data()

        if grid_data.n_documents == 0:
            return {
                "from_position": self._coord_string(cx, cy),
                "target": None,
                "error": "No documents indexed. Run /reindex first.",
            }

        # Compute curvatures if we have embeddings
        curvature_map = [[0.0] * 19 for _ in range(19)]
        if grid_data.raw_embeddings is not None and len(grid_data.raw_embeddings) >= 15:
            try:
                import asyncio
                import numpy as np
                from .core.geometry import GeometryComputer

                grid_coords = np.array([(p.x, p.y) for p in grid_data.points])
                gc = GeometryComputer(k_neighbors=min(15, len(grid_data.raw_embeddings) - 1))

                # Run geometry computation
                try:
                    loop = asyncio.get_running_loop()
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        future = pool.submit(
                            asyncio.run,
                            gc.compute_features(grid_data.raw_embeddings, grid_coords)
                        )
                        geom_features = future.result(timeout=60)
                except RuntimeError:
                    geom_features = asyncio.run(
                        gc.compute_features(grid_data.raw_embeddings, grid_coords)
                    )

                # Map curvatures to grid
                if geom_features and geom_features.curvatures is not None:
                    for i, point in enumerate(grid_data.points):
                        if i < len(geom_features.curvatures):
                            curvature_map[point.y][point.x] = geom_features.curvatures[i]
            except Exception:
                pass  # Continue without curvatures

        # Find best tenuki target using curvature-based scoring
        best_score = 0.0
        best_pos = None
        best_curvature = 0.0

        # Track visited positions (from state if available)
        visited = getattr(self.state, 'tenuki_visited', set())

        for y in range(19):
            for x in range(19):
                # Skip positions without data
                if curvature_map[y][x] == 0:
                    # Check if there's a document at this position (fallback)
                    if (x, y) not in grid_data.grid_to_embedding:
                        continue

                curvature = abs(curvature_map[y][x])

                # Distance from current position
                dist = abs(x - cx) + abs(y - cy)

                # Distance factor: prefer moderate distances
                if dist < 3:
                    dist_factor = 0.1  # Too close
                elif dist < 7:
                    dist_factor = 1.0  # Ideal
                elif dist < 12:
                    dist_factor = 0.7  # Moderate
                else:
                    dist_factor = 0.4  # Far

                # Novelty factor: avoid recently visited
                min_visited_dist = 999
                for vx, vy in visited:
                    visited_dist = abs(x - vx) + abs(y - vy)
                    min_visited_dist = min(min_visited_dist, visited_dist)

                if min_visited_dist < 3:
                    novelty_factor = 0.3
                elif min_visited_dist < 6:
                    novelty_factor = 0.7
                else:
                    novelty_factor = 1.0

                # Score with fallback for zero curvature (use distance only)
                if curvature > 0:
                    score = curvature * dist_factor * novelty_factor
                else:
                    # Fallback: just use distance/novelty for positions with documents
                    score = dist_factor * novelty_factor * 0.1

                if score > best_score:
                    best_score = score
                    best_pos = (x, y)
                    best_curvature = curvature_map[y][x]

        if best_pos is None:
            return {
                "from_position": self._coord_string(cx, cy),
                "target": None,
                "error": "No suitable tenuki target found",
            }

        # Get document info at target
        target_doc = None
        target_idx = grid_data.grid_to_embedding.get(best_pos)
        if target_idx is not None and target_idx < len(grid_data.points):
            target_doc = grid_data.points[target_idx].title

        return {
            "from_position": self._coord_string(cx, cy),
            "from_x": cx,
            "from_y": cy,
            "target": self._coord_string(best_pos[0], best_pos[1]),
            "target_x": best_pos[0],
            "target_y": best_pos[1],
            "score": round(best_score, 4),
            "curvature": round(best_curvature, 4),
            "distance": abs(best_pos[0] - cx) + abs(best_pos[1] - cy),
            "document": target_doc,
        }

    def _cmd_help(self) -> dict:
        """Get help text."""
        return {
            "commands": {
                "info [pos]": "Get info about position (default: cursor)",
                "goto <pos>": "Move cursor to position",
                "domain [name]": "Set or get domain",
                "overlay [mode]": "Set or cycle overlay mode",
                "view [mode]": "Set or cycle view mode",
                "state [subcmd]": "State ops (sync, generation, prefs, prune)",
                "agents": "List all agents",
                "grid": "Get ASCII grid representation",
                "minigrid [pos]": "Get 9x9 Embed/Iso mini-grid data for position",
                "reindex": "Reindex KB documents to Qdrant and refresh grid",
                "tenuki [pos]": "Find strategic jump point (high-curvature region)",
                "help": "Show this help",
                # Primary agentic interface
                "ask [flags] <question>": "/ask away! Agentic query (--reason, --search, --swarm, --platform, --save)",
                # Telemetry observability
                "watch [cmd] [filter]": "OTel telemetry (status, traces, spans, metrics, logs)",
                # Search and research
                "search <query>": "Hybrid search (BM25 + Vector + Web)",
                "research <topic>": "Hybrid search + LLM → Zettelkasten note",
                "research-eval <topic>": "Research + evaluate with frontier model",
                "eval <path>": "Evaluate a Zettelkasten note",
                "eval-stats": "Show aggregate evaluation statistics",
                "technique [name]": "Set or show optillm technique",
                "kb <subcommand>": "KB operations (list, read, search, sync [--dry-run])",
                # Scheduler commands
                "scheduler [cmd]": "Scheduler ops (status, health, metrics, start, stop)",
                "submit [flags] <prompt>": "Submit job (flags: priority:high model:name)",
                "swarm <domain> [context]": "Run swarm analysis with optimal scheduling",
                # GPU Orchestrator commands
                "gpu [cmd] [args]": "GPU orchestrator (status, start, stop, restart, logs, health)",
                # Inference management (high-level)
                "inference [cmd] [args]": "Inference stack (status, start, stop, restart, ensure)",
                # Explain command
                "explain [pos]": "Explain grid position using local LLM (default: K10)",
                # Engine connectivity
                "engine [cmd]": "Engine connection (status, reconnect, test)",
                # Unified command routing (thin client)
                "exec <cmd> [args]": "Execute via Engine's CommandService",
            },
            "tagline": "/ask away! Use /ask for general queries, /watch for telemetry, /search for research.",
        }

    # --- Model Registry Commands ---

    def _cmd_model(self, args: str) -> dict:
        """Model registry operations.

        Usage:
            /model                  - List all registered models
            /model list             - List all registered models
            /model info <id>        - Show detailed info for a model
            /model serve <id>       - Show vLLM serve command for a model
            /model task <task>      - Find best model for task type
        """
        from .models.registry import (
            get_model_registry,
            ModelCapability,
            TaskType,
        )

        registry = get_model_registry()

        parts = args.split(maxsplit=1) if args else []
        subcmd = parts[0].lower() if parts else "list"
        subargs = parts[1] if len(parts) > 1 else ""

        if subcmd == "list" or subcmd == "":
            # List all models
            models = []
            for model in registry.list_models():
                models.append({
                    "name": model.name,
                    "model_id": model.model_id,
                    "provider": model.provider,
                    "parameters_b": model.parameters_b,
                    "context_length": model.context_length,
                    "capabilities": [c.name for c in model.capabilities],
                    "has_vllm_config": model.vllm_config is not None,
                    "default_port": model.default_port,
                    "tags": model.tags,
                })
            return {"models": models, "count": len(models)}

        elif subcmd == "info":
            # Get detailed info for a model
            if not subargs:
                raise ValueError("model info requires a model ID")

            # Try exact match first, then partial match
            model = registry.get(subargs)
            if not model:
                # Try partial match on name or model_id
                for m in registry.list_models():
                    if subargs.lower() in m.name.lower() or subargs.lower() in m.model_id.lower():
                        model = m
                        break

            if not model:
                raise ValueError(f"Model not found: {subargs}")

            info = {
                "name": model.name,
                "model_id": model.model_id,
                "provider": model.provider,
                "description": model.description,
                "parameters_b": model.parameters_b,
                "context_length": model.context_length,
                "embedding_dim": model.embedding_dim,
                "capabilities": [c.name for c in model.capabilities],
                "task_scores": {t.value: s for t, s in model.task_scores.items()},
                "default_temperature": model.default_temperature,
                "default_max_tokens": model.default_max_tokens,
                "default_port": model.default_port,
                "tags": model.tags,
            }

            if model.vllm_config:
                cfg = model.vllm_config
                info["vllm_config"] = {
                    "tensor_parallel_size": cfg.tensor_parallel_size,
                    "gpu_memory_utilization": cfg.gpu_memory_utilization,
                    "max_model_len": cfg.max_model_len,
                    "max_num_seqs": cfg.max_num_seqs,
                    "dtype": cfg.dtype,
                    "trust_remote_code": cfg.trust_remote_code,
                    "tool_call_parser": cfg.tool_call_parser,
                    "reasoning_parser": cfg.reasoning_parser,
                    "attention_backend": cfg.attention_backend,
                }

            return info

        elif subcmd == "serve":
            # Generate vLLM serve command
            if not subargs:
                raise ValueError("model serve requires a model ID")

            # Parse optional flags: model serve <id> [--port=N] [--gpus=0,1,2,3]
            model_id = subargs.split()[0]
            port = None
            gpus = None

            for part in subargs.split()[1:]:
                if part.startswith("--port="):
                    port = int(part.split("=")[1])
                elif part.startswith("--gpus="):
                    gpus = [int(g) for g in part.split("=")[1].split(",")]

            # Find model
            model = registry.get(model_id)
            if not model:
                for m in registry.list_models():
                    if model_id.lower() in m.name.lower() or model_id.lower() in m.model_id.lower():
                        model = m
                        break

            if not model:
                raise ValueError(f"Model not found: {model_id}")

            if not model.vllm_config:
                raise ValueError(f"Model {model.name} does not have vLLM configuration")

            cmd, env = model.serve_command(port=port, gpus=gpus)

            return {
                "model": model.name,
                "command": cmd,
                "env_vars": env,
                "full_command": " ".join(f"{k}={v}" for k, v in env.items()) + " " + cmd if env else cmd,
            }

        elif subcmd == "task":
            # Find best model for a task
            if not subargs:
                # List available task types
                return {
                    "task_types": [t.value for t in TaskType],
                    "hint": "Use: /model task <task_type> to find best model",
                }

            try:
                task = TaskType(subargs.lower())
            except ValueError:
                raise ValueError(f"Unknown task type: {subargs}. Valid: {[t.value for t in TaskType]}")

            model = registry.get_for_task(task, require_local=True)
            if not model:
                model = registry.get_for_task(task)

            if not model:
                return {"task": task.value, "model": None, "message": "No model found for task"}

            return {
                "task": task.value,
                "model": model.name,
                "model_id": model.model_id,
                "score": model.score_for_task(task),
                "provider": model.provider,
            }

        elif subcmd == "add-note":
            # Fetch HuggingFace model card and create KB note
            if not subargs:
                raise ValueError("model add-note requires a model ID (e.g., mistralai/Mistral-7B-Instruct-v0.3)")

            model_id = subargs.strip()
            return self._run_async(self._cmd_model_add_note(model_id))

        elif subcmd == "add":
            # Agent-orchestrated model registry addition
            if not subargs:
                raise ValueError("Usage: /model add <model_id> [--legacy]")

            parts = subargs.split()
            model_id = parts[0]
            legacy_mode = "--legacy" in parts

            # Agent-first: check engine availability first
            if not legacy_mode:
                from .client.engine_proxy import use_engine_proxy
                if not use_engine_proxy():
                    return {
                        "error": "Gaius engine not running",
                        "hint": "Start the engine with: gaius-engine start",
                        "alternative": "Use --legacy flag for standalone mode: /model add <model_id> --legacy",
                    }

            if legacy_mode:
                # Use existing hardcoded implementation
                return self._run_async(self._cmd_model_add_legacy(model_id))
            else:
                # Use agent orchestration (default)
                return self._run_async(self._cmd_model_add_agent(model_id))

        elif subcmd == "add-confirm":
            # Confirm pending model addition
            return self._run_async(self._cmd_model_add_confirm())

        elif subcmd == "add-cancel":
            # Cancel pending model addition
            return self._cmd_model_add_cancel()

        else:
            raise ValueError(f"Unknown model subcommand: {subcmd}. Use: list, info, serve, task, add-note, add")

    async def _cmd_model_add_note(self, model_id: str) -> dict:
        """Fetch HuggingFace model card and create KB note.

        Args:
            model_id: HuggingFace model ID (e.g., mistralai/Mistral-7B-Instruct-v0.3)

        Returns:
            Dict with path to created note
        """
        import httpx
        from pathlib import Path
        from datetime import datetime

        # Fetch model card from HuggingFace
        hf_url = f"https://huggingface.co/{model_id}"
        readme_url = f"https://huggingface.co/{model_id}/raw/main/README.md"

        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            # Try to fetch README.md directly
            try:
                resp = await client.get(readme_url)
                if resp.status_code == 200:
                    readme_content = resp.text
                else:
                    readme_content = None
            except Exception:
                readme_content = None

            # Also fetch model info from API
            api_url = f"https://huggingface.co/api/models/{model_id}"
            try:
                resp = await client.get(api_url)
                if resp.status_code == 200:
                    model_info = resp.json()
                else:
                    model_info = {}
            except Exception:
                model_info = {}

        # Extract useful info
        model_name = model_id.split("/")[-1]
        org_name = model_id.split("/")[0] if "/" in model_id else "unknown"

        # Build the note content
        lines = [
            f"# {model_name}",
            "",
            f"**Model ID:** `{model_id}`",
            f"**Organization:** {org_name}",
            f"**HuggingFace:** [{model_id}]({hf_url})",
            "",
        ]

        # Add model info from API if available
        if model_info:
            if model_info.get("pipeline_tag"):
                lines.append(f"**Pipeline:** {model_info['pipeline_tag']}")
            if model_info.get("library_name"):
                lines.append(f"**Library:** {model_info['library_name']}")
            if model_info.get("downloads"):
                lines.append(f"**Downloads:** {model_info['downloads']:,}")
            if model_info.get("likes"):
                lines.append(f"**Likes:** {model_info['likes']:,}")
            if model_info.get("tags"):
                lines.append(f"**Tags:** {', '.join(model_info['tags'][:10])}")
            lines.append("")

        # Add the README content
        if readme_content:
            lines.append("## Model Card")
            lines.append("")
            lines.append(readme_content)
        else:
            lines.append("## Model Card")
            lines.append("")
            lines.append(f"*Could not fetch model card. Visit [{hf_url}]({hf_url}) for details.*")

        # Add metadata footer
        lines.extend([
            "",
            "---",
            f"*Note created: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        ])

        content = "\n".join(lines)

        # Create the file in KB
        kb_root = Path(self.config.kb.root)
        models_dir = kb_root / "current" / "models"
        models_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize filename
        safe_name = model_name.lower().replace(" ", "-")
        note_path = models_dir / f"{safe_name}.md"

        note_path.write_text(content)

        return {
            "model_id": model_id,
            "path": str(note_path),
            "size_bytes": len(content),
            "has_readme": readme_content is not None,
            "message": f"Created note at {note_path}",
        }

    # --- Model Add (AI-Powered) ---

    # System prompt for AI code generation
    _MODELSPEC_SYSTEM_PROMPT = """You are a Python code generator for the Gaius model registry.
Generate a ModelSpec definition. Output ONLY valid Python code. No explanations, no markdown fences.

## EXACT ModelSpec signature (use ONLY these fields):
ModelSpec(
    model_id: str,           # HuggingFace model ID
    name: str,               # Human-readable name
    provider: str,           # "vllm" for local models
    capabilities: list,      # List of ModelCapability values
    task_scores: dict,       # Dict mapping TaskType to float (0.0-1.0)
    context_length: int,     # Max context window
    parameters_b: float,     # Parameters in billions (optional)
    default_temperature: float,  # Default 0.7
    default_max_tokens: int,     # Default 2048
    default_port: int,       # Default 8085
    vllm_config: VLLMConfig, # vLLM serving config (optional)
    description: str,        # Brief description
    tags: list[str],         # Search tags
)

## EXACT VLLMConfig signature:
VLLMConfig(
    tensor_parallel_size: int,   # 1 for <10B, 2 for 10-30B, 4 for 30B+
    max_model_len: int,          # Context length, cap at 65536
    trust_remote_code: bool,     # True only for Qwen, GLM
)

## ModelCapability enum values (for capabilities list):
##   CHAT, REASONING, CODING, FUNCTION_CALLING, LONG_CONTEXT, VISION_LANGUAGE,
##   ORCHESTRATION, TEXT_EMBEDDING, VISION_EMBEDDING

## TaskType enum values (for task_scores dict keys):
##   CHAT, REASONING, CODING, SWARM_AGENT, SWARM_LEADER, EVALUATION,
##   ORCHESTRATION, TEXT_EMBEDDING, VISION_EMBEDDING
## NOTE: TaskType does NOT have FUNCTION_CALLING or LONG_CONTEXT - those are only ModelCapability!

## Example:
MISTRAL_7B = ModelSpec(
    model_id="mistralai/Mistral-7B-Instruct-v0.3",
    name="Mistral-7B",
    provider="vllm",
    capabilities=[ModelCapability.CHAT, ModelCapability.FUNCTION_CALLING],
    task_scores={
        TaskType.CHAT: 0.85,
        TaskType.SWARM_AGENT: 0.80,
    },
    context_length=32768,
    parameters_b=7.2,
    default_temperature=0.7,
    default_max_tokens=2048,
    default_port=8085,
    vllm_config=VLLMConfig(
        tensor_parallel_size=1,
        max_model_len=32768,
    ),
    description="Mistral 7B Instruct - fast chat model with function calling",
    tags=["chat", "instruct", "fast"],
)

Use UPPERCASE_WITH_UNDERSCORES for the variable name.
"""

    async def _cmd_model_add_agent(self, model_id: str) -> dict:
        """Agent-orchestrated model addition using Orchestrator-8B.

        Uses a ReAct agent loop where Orchestrator-8B coordinates:
        1. GPU management (launch/release coding model)
        2. HuggingFace data fetching
        3. AI code generation with retry logic
        4. Validation in subprocess/devenv sandbox
        5. Optional XAI critique for quality signal

        Args:
            model_id: HuggingFace model ID

        Returns:
            Dict with generated code and validation results for review
        """
        from .agents.modeladd import ModelAddOrchestrator

        orchestrator = ModelAddOrchestrator()
        result = await orchestrator.run(model_id)

        # Save pending state if successful
        if result.get("status") == "pending_review":
            self._save_pending_model_add({
                "model_id": model_id,
                "code": result.get("generated_code", ""),
                "validation": result.get("validation", {}),
                "critique": result.get("critique", {}),
            })

        return result

    async def _cmd_model_add_legacy(self, model_id: str) -> dict:
        """Generate and validate ModelSpec code for a HuggingFace model.

        Legacy implementation - uses hardcoded workflow instead of agent orchestration.
        Use --legacy flag to invoke this method.

        Uses AI code generation with tiered fallback:
        1. Engine-managed coding endpoint
        2. Frontier model (xAI Grok)

        Args:
            model_id: HuggingFace model ID (e.g., mistralai/Mistral-7B-Instruct-v0.3)

        Returns:
            Dict with generated code and validation results for review
        """
        # Phase 1: Fetch HuggingFace data
        hf_data = await self._fetch_hf_comprehensive(model_id)
        if not hf_data.get("api_info"):
            return {"error": f"Could not fetch model info for {model_id}"}

        # Phase 2: Generate code via AI
        try:
            generated_code = await self._generate_modelspec(hf_data)
        except Exception as e:
            return {
                "error": f"Code generation failed: {e}",
                "hint": "Ensure local coding model is running or XAI_API_KEY is set",
            }

        # Phase 3: Validate in subprocess
        validation = self._validate_modelspec_code(generated_code)

        # Store for confirmation (persist to file for CLI usage)
        pending_data = {
            "model_id": model_id,
            "code": generated_code,
            "validation": validation,
        }
        self._save_pending_model_add(pending_data)

        return {
            "status": "pending_review",
            "model_id": model_id,
            "generated_code": generated_code,
            "validation": validation,
            "next_steps": [
                "/model add-confirm  - Write to registry",
                "/model add-cancel   - Discard",
            ],
        }

    async def _fetch_hf_comprehensive(self, model_id: str) -> dict:
        """Fetch comprehensive model data from HuggingFace.

        Args:
            model_id: HuggingFace model ID

        Returns:
            Dict with api_info, config, and readme
        """
        import httpx

        data = {"model_id": model_id, "api_info": {}, "config": {}, "readme": None}

        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            # API metadata
            api_url = f"https://huggingface.co/api/models/{model_id}"
            try:
                resp = await client.get(api_url)
                if resp.status_code == 200:
                    data["api_info"] = resp.json()
            except Exception:
                pass

            # config.json for context_length, architecture
            config_url = f"https://huggingface.co/{model_id}/raw/main/config.json"
            try:
                resp = await client.get(config_url)
                if resp.status_code == 200:
                    data["config"] = resp.json()
            except Exception:
                pass

            # README.md (truncated for prompt)
            readme_url = f"https://huggingface.co/{model_id}/raw/main/README.md"
            try:
                resp = await client.get(readme_url)
                if resp.status_code == 200:
                    # Truncate to avoid huge prompts
                    data["readme"] = resp.text[:4000]
            except Exception:
                pass

        return data

    async def _get_coding_model(self) -> tuple[str, str]:
        """Get best available coding model endpoint.

        Tries engine-managed coding endpoint first, then falls back to Grok API.

        Returns:
            Tuple of (model_id, endpoint_url)

        Raises:
            RuntimeError: If no coding model is available
        """
        import httpx
        import os

        # Try engine-managed coding endpoint (agent-first)
        try:
            from .client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

            if use_engine_proxy():
                orch = await get_orchestrator_proxy()
                result = await orch.ensure_endpoint("coding")
                if result.get("healthy"):
                    port = result.get("port", 8083)
                    model_id = result.get("model", "coding")
                    return (model_id, f"http://localhost:{port}/v1")
        except Exception:
            pass

        # Fallback to Grok via XAI API
        if os.getenv("XAI_API_KEY"):
            return ("grok-2-latest", "https://api.x.ai/v1")

        raise RuntimeError(
            "No coding model available. Either:\n"
            "  - Start the Gaius engine (gaius-engine start)\n"
            "  - Set XAI_API_KEY environment variable"
        )

    async def _generate_modelspec(self, hf_data: dict) -> str:
        """Generate ModelSpec code via AI.

        Args:
            hf_data: HuggingFace data from _fetch_hf_comprehensive

        Returns:
            Generated Python code string

        Raises:
            RuntimeError: If no coding model available
            httpx.HTTPError: If API request fails
        """
        import httpx
        import os

        model_id, endpoint = await self._get_coding_model()
        prompt = self._build_ai_prompt(hf_data)

        # Prepare headers
        headers = {"Content-Type": "application/json"}
        api_key = os.getenv("XAI_API_KEY", "")
        if api_key and "x.ai" in endpoint:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{endpoint}/chat/completions",
                headers=headers,
                json={
                    "model": model_id,
                    "messages": [
                        {"role": "system", "content": self._MODELSPEC_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 2000,
                },
            )
            resp.raise_for_status()

        code = resp.json()["choices"][0]["message"]["content"]

        # Strip markdown fences if present
        if "```python" in code:
            code = code.split("```python")[1].split("```")[0]
        elif "```" in code:
            code = code.split("```")[1].split("```")[0]

        return code.strip()

    def _build_ai_prompt(self, hf_data: dict) -> str:
        """Build the user prompt for AI code generation.

        Args:
            hf_data: HuggingFace data

        Returns:
            Formatted prompt string
        """
        import re

        model_id = hf_data["model_id"]
        config = hf_data.get("config", {})
        api = hf_data.get("api_info", {})
        readme = hf_data.get("readme", "")

        # Extract key info
        name = model_id.split("/")[-1]
        context_len = config.get("max_position_embeddings") or config.get("n_positions", 32768)
        architectures = config.get("architectures", [])
        model_type = config.get("model_type", "unknown")

        # Estimate parameters
        params_b = self._estimate_params(api, name)

        # Build prompt
        prompt = f"""Generate a ModelSpec for this model:

Model ID: {model_id}
Model Name: {name}
Architecture: {architectures[0] if architectures else model_type}
Context Length: {context_len}
Parameters: ~{params_b}B
Pipeline: {api.get('pipeline_tag', 'text-generation')}
Tags: {', '.join(api.get('tags', [])[:15])}
Downloads: {api.get('downloads', 0):,}

"""
        if readme:
            # Add truncated README for context
            prompt += f"Model Card (excerpt):\n{readme[:2000]}\n\n"

        prompt += """Generate the ModelSpec Python code. Include appropriate:
- capabilities list based on model type/tags
- task_scores dict with relevant TaskType mappings
- vllm_config with correct tensor_parallel_size for the parameter count
"""
        return prompt

    def _estimate_params(self, api_info: dict, name: str) -> float:
        """Estimate model parameters in billions.

        Args:
            api_info: HuggingFace API response
            name: Model name

        Returns:
            Estimated parameter count in billions
        """
        import re

        # Try safetensors metadata first
        safetensors = api_info.get("safetensors", {})
        if safetensors and safetensors.get("total"):
            return round(safetensors["total"] / 1e9, 1)

        # Parse from name (e.g., "Mistral-7B", "Qwen-32B", "14B", "30B-A3B")
        match = re.search(r'(\d+(?:\.\d+)?)[Bb]', name)
        if match:
            return float(match.group(1))

        # Check for MoE patterns (e.g., "30B-A3B" means 30B total, 3B active)
        moe_match = re.search(r'(\d+)[Bb]-[Aa](\d+)[Bb]', name)
        if moe_match:
            return float(moe_match.group(1))

        return 7.0  # Conservative default

    def _validate_modelspec_code(self, code: str) -> dict:
        """Validate generated ModelSpec code.

        Args:
            code: Generated Python code

        Returns:
            Validation results dict
        """
        import ast
        import subprocess
        from pathlib import Path

        result = {
            "syntax": False,
            "imports": False,
            "serve_cmd": False,
            "warnings": [],
            "variable_name": None,
        }

        # 1. Syntax check
        try:
            tree = ast.parse(code)
            result["syntax"] = True
        except SyntaxError as e:
            result["warnings"].append(f"Syntax error at line {e.lineno}: {e.msg}")
            return result

        # 2. Find variable name
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                if isinstance(node.value, ast.Call):
                    func = node.value.func
                    if hasattr(func, 'id') and func.id == 'ModelSpec':
                        if node.targets and isinstance(node.targets[0], ast.Name):
                            result["variable_name"] = node.targets[0].id

        if not result["variable_name"]:
            result["warnings"].append("No ModelSpec() assignment found")
            return result

        # 3. Import test in subprocess (isolated)
        test_script = f'''
import sys
sys.path.insert(0, "src")
from gaius.models.registry import ModelSpec, VLLMConfig, ModelCapability, TaskType
{code}
# Find and validate the ModelSpec
for name, obj in list(locals().items()):
    if isinstance(obj, ModelSpec):
        print(f"MODEL_OK: {{name}}")
        print(f"CAPABILITIES: {{[c.name for c in obj.capabilities]}}")
        try:
            cmd, env = obj.serve_command(port=8099, gpus=[0])
            print(f"SERVE_CMD_OK")
        except Exception as e:
            print(f"SERVE_CMD_ERR: {{e}}")
        break
'''
        try:
            # Find project root
            cli_path = Path(__file__).resolve()
            project_root = cli_path.parent.parent.parent

            proc = subprocess.run(
                ["python", "-c", test_script],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=str(project_root),
            )

            result["imports"] = "MODEL_OK" in proc.stdout
            result["serve_cmd"] = "SERVE_CMD_OK" in proc.stdout

            if proc.returncode != 0 and proc.stderr:
                # Truncate long error messages
                err = proc.stderr[:500]
                result["warnings"].append(f"Import error: {err}")

            if "SERVE_CMD_ERR" in proc.stdout:
                err_match = proc.stdout.split("SERVE_CMD_ERR:")
                if len(err_match) > 1:
                    result["warnings"].append(f"serve_command error: {err_match[1].strip()}")

        except subprocess.TimeoutExpired:
            result["warnings"].append("Validation timed out (15s)")
        except Exception as e:
            result["warnings"].append(f"Validation failed: {e}")

        return result

    async def _cmd_model_add_confirm(self) -> dict:
        """Commit the pending ModelSpec to registry.

        Returns:
            Dict with commit status
        """
        import re
        from pathlib import Path

        pending = self._load_pending_model_add()
        if not pending:
            return {"error": "No pending model. Run /model add first."}

        code = pending["code"]
        model_id = pending["model_id"]
        validation = pending["validation"]

        # Check validation passed
        if not validation.get("imports"):
            return {
                "error": "Cannot commit - validation failed",
                "validation": validation,
                "hint": "Fix the generated code or cancel with /model add-cancel",
            }

        var_name = validation.get("variable_name")
        if not var_name:
            return {"error": "Could not determine variable name from generated code"}

        # Find registry.py
        cli_path = Path(__file__).resolve()
        registry_path = cli_path.parent / "models" / "registry.py"

        if not registry_path.exists():
            return {"error": f"Registry not found at {registry_path}"}

        content = registry_path.read_text()

        # Insert before Registry class definition
        # Look for the marker comment before the Registry class
        marker = "# " + "=" * 79 + "\n# Registry"
        if marker not in content:
            # Try alternative marker
            marker = "class ModelRegistry:"
            if marker not in content:
                return {"error": "Could not find insertion point in registry.py"}

        # Add the new model before the marker
        new_content = content.replace(marker, f"{code}\n\n\n{marker}")

        # Add to defaults list
        defaults_pattern = r'(defaults\s*=\s*\[)'
        if re.search(defaults_pattern, new_content):
            new_content = re.sub(
                defaults_pattern,
                f'\\1\n            {var_name},',
                new_content,
            )
        else:
            return {"error": "Could not find defaults list in registry.py"}

        # Write the updated registry
        registry_path.write_text(new_content)

        # Create KB note
        try:
            await self._cmd_model_add_note(model_id)
        except Exception:
            pass  # Non-fatal if KB note fails

        # Clean up pending state
        self._clear_pending_model_add()

        return {
            "status": "committed",
            "model_id": model_id,
            "variable": var_name,
            "files_modified": [str(registry_path)],
            "verify_with": f"/model info {var_name.replace('_', '-').lower()}",
        }

    def _cmd_model_add_cancel(self) -> dict:
        """Cancel pending model add.

        Returns:
            Dict with cancel status
        """
        pending = self._load_pending_model_add()
        if pending:
            model_id = pending.get("model_id", "unknown")
            self._clear_pending_model_add()
            return {"status": "cancelled", "model_id": model_id}
        return {"status": "nothing_pending"}

    def _get_pending_file_path(self) -> "Path":
        """Get path for pending model add state file."""
        from pathlib import Path
        return Path(self.config.kb.root) / ".pending_model_add.json"

    def _save_pending_model_add(self, data: dict) -> None:
        """Save pending model add state to file."""
        import json
        path = self._get_pending_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

    def _load_pending_model_add(self) -> dict | None:
        """Load pending model add state from file."""
        import json
        path = self._get_pending_file_path()
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                return None
        return None

    def _clear_pending_model_add(self) -> None:
        """Clear pending model add state."""
        path = self._get_pending_file_path()
        if path.exists():
            path.unlink()

    # --- Inference Commands ---

    async def _cmd_ask(self, args: str) -> dict:
        """General-purpose agentic query interface.

        /ask away! - the primary way to leverage gaius-engine for problem solving.

        Capabilities:
        - Reasoning: Uses chain-of-thought for complex analysis
        - Search: Hybrid KB + web search for research queries
        - Swarm: Multi-agent analysis for domain questions
        - Platform: Diagnoses and captures remediation heuristics

        Usage:
            /ask <question>              - Auto-route based on query analysis
            /ask --reason <question>     - Force reasoning mode
            /ask --search <question>     - Force search + synthesis
            /ask --swarm <question>      - Force multi-agent analysis
            /ask --platform <error>      - Diagnose platform issues
            /ask --save                  - Save response to KB as heuristic
        """
        if not args:
            raise ValueError("ask requires a question. /ask away!")

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
            raise ValueError("ask requires a question after flags")

        # Try engine first if available
        engine_client = await self._get_engine_client_cached()

        # Determine routing strategy
        if force_swarm:
            return await self._ask_swarm(query, engine_client, save_to_kb)
        elif force_search:
            return await self._ask_search(query, engine_client, save_to_kb)
        elif force_reason:
            return await self._ask_reason(query, engine_client, save_to_kb)
        elif is_platform:
            return await self._ask_platform(query, engine_client, save_to_kb)
        else:
            # Auto-route based on query analysis
            return await self._ask_auto(query, engine_client, save_to_kb)

    async def _get_engine_client_cached(self):
        """Get cached engine client if available.

        Uses gRPC as the only transport. Connection is attempted once
        and cached for the lifetime of the CLI instance.
        """
        if not hasattr(self, "_engine_client"):
            self._engine_client = None

        if self._engine_client is not None:
            return self._engine_client

        try:
            from .client.grpc_client import GrpcEngineClient
            client = GrpcEngineClient()
            if await client.connect():
                self._engine_client = client
                return client
        except Exception:
            pass
        return None

    async def _get_scheduler_proxy(self):
        """Get scheduler proxy for engine-backed inference.

        All inference should route through the engine scheduler for:
        - Centralized OTel metrics export
        - Proper resource management
        - Request prioritization

        Returns:
            SchedulerProxy if engine available, None otherwise
        """
        if not hasattr(self, "_scheduler_proxy"):
            self._scheduler_proxy = None

        if self._scheduler_proxy is not None:
            return self._scheduler_proxy

        try:
            from .client.engine_proxy import get_scheduler_proxy, use_engine_proxy
            if use_engine_proxy():
                self._scheduler_proxy = await get_scheduler_proxy()
                return self._scheduler_proxy
        except Exception:
            pass
        return None

    async def _complete_via_engine(
        self,
        prompt: str,
        system_prompt: str | None = None,
        technique: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict | None:
        """Complete a prompt via engine scheduler.

        This ensures all inference metrics are recorded through the engine's
        OTel pipeline. Falls back to None if engine unavailable.

        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            technique: Optional optillm technique
            temperature: Sampling temperature
            max_tokens: Maximum tokens

        Returns:
            Dict with content, model, tokens or None if engine unavailable
        """
        scheduler = await self._get_scheduler_proxy()
        if scheduler is None:
            return None

        try:
            result = await scheduler.complete(
                prompt=prompt,
                agent="fast",  # Use fast agent (always available)
                system_prompt=system_prompt,
                technique=technique,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return {
                "content": result.content,
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "technique": result.technique,
                "backend": result.backend,
            }
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"Engine inference failed: {e}")
            return None

    async def _ask_auto(self, query: str, engine_client, save_to_kb: bool) -> dict:
        """Auto-route query based on content analysis."""
        query_lower = query.lower()

        # Platform error patterns
        platform_patterns = [
            "error", "failed", "not found", "exception", "traceback",
            "no documents", "reindex", "connection refused", "timeout",
        ]
        if any(p in query_lower for p in platform_patterns):
            return await self._ask_platform(query, engine_client, save_to_kb)

        # Research patterns (need search + synthesis)
        research_patterns = [
            "what is", "how does", "explain", "compare", "difference between",
            "pros and cons", "best practice", "documentation",
        ]
        if any(p in query_lower for p in research_patterns):
            return await self._ask_search(query, engine_client, save_to_kb)

        # Domain analysis patterns (benefit from swarm)
        domain_patterns = [
            "analyze", "assess", "evaluate", "implications", "strategy",
            "pension", "kudu", "risk", "investment",
        ]
        if any(p in query_lower for p in domain_patterns):
            return await self._ask_swarm(query, engine_client, save_to_kb)

        # Default to reasoning
        return await self._ask_reason(query, engine_client, save_to_kb)

    async def _ask_reason(self, query: str, engine_client, save_to_kb: bool) -> dict:
        """Use reasoning model for complex analysis.

        Routes through engine scheduler for centralized metrics when available.
        """
        # Build system prompt for reasoning
        system = """You are a helpful assistant with strong reasoning capabilities.
Think step-by-step when solving problems. If you're unsure, say so.
When discussing technical topics, be precise and cite sources when possible."""

        # Try engine-backed inference first (centralized metrics)
        engine_result = await self._complete_via_engine(
            prompt=query,
            system_prompt=system,
            technique="cot_reflection",
        )

        if engine_result:
            response_data = {
                "mode": "reasoning",
                "query": query,
                "response": engine_result["content"],
                "model": engine_result["model"],
                "technique": engine_result.get("technique") or "cot_reflection",
                "tokens": f"{engine_result['input_tokens']}+{engine_result['output_tokens']}",
                "backend": engine_result.get("backend", "engine"),
            }

            if save_to_kb:
                saved_path = await self._save_to_kb(query, engine_result["content"], "reasoning")
                response_data["saved_to"] = str(saved_path)

            return response_data

        # Fallback to engine inference client
        try:
            from .inference import get_engine_client, Message

            client = await get_engine_client()

            result = await client.complete(
                messages=[
                    Message(role="system", content=system),
                    Message(role="user", content=query),
                ],
                technique="cot_reflection",
            )

            response_data = {
                "mode": "reasoning",
                "query": query,
                "response": result.content,
                "model": result.model,
                "technique": result.technique or "cot_reflection",
                "tokens": f"{result.input_tokens}+{result.output_tokens}",
                "backend": "engine",
            }

            if save_to_kb:
                saved_path = await self._save_to_kb(query, result.content, "reasoning")
                response_data["saved_to"] = str(saved_path)

            return response_data

        except ImportError:
            raise RuntimeError("Inference not available. Run: uv sync --extra inference")

    async def _ask_search(self, query: str, engine_client, save_to_kb: bool) -> dict:
        """Search + synthesis mode.

        When --save is specified, leverages /research to create a full
        Zettelkasten document with proper citations and wiki-links.
        Otherwise, provides a quick synthesis from search results.

        Routes through engine scheduler for centralized metrics when available.
        """
        # If saving, delegate to /research for full document creation
        if save_to_kb:
            return await self._ask_research(query, engine_client)

        # Quick synthesis mode (no save)
        # Run hybrid search
        search_result = await self._cmd_search(query)

        kb_results = search_result.get("kb_results", [])
        web_results = search_result.get("web_results", [])

        if not kb_results and not web_results:
            # Fall back to web search only
            try:
                from .inference.search import get_web_search
                web_search = get_web_search()
                web_hits = await web_search.search(query, count=5)
                web_results = [
                    {"title": r.title, "snippet": r.snippet, "url": r.url}
                    for r in web_hits
                ]
            except Exception:
                pass

        # Build context from search results
        context_parts = []
        if kb_results:
            context_parts.append("**From Knowledge Base:**")
            for r in kb_results[:5]:
                context_parts.append(f"- [{r.get('title', 'Untitled')}]: {r.get('snippet', '')[:200]}")

        if web_results:
            context_parts.append("\n**From Web:**")
            for r in web_results[:5]:
                context_parts.append(f"- [{r.get('title', 'Untitled')}]({r.get('url', '')}): {r.get('snippet', '')[:200]}")

        context = "\n".join(context_parts) if context_parts else "No search results found."

        prompt = f"""Based on the following search results, answer the question.
Cite sources using [source] notation.

{context}

Question: {query}

Answer:"""

        # Try engine-backed inference first (centralized metrics)
        engine_result = await self._complete_via_engine(prompt=prompt)

        if engine_result:
            return {
                "mode": "search",
                "query": query,
                "response": engine_result["content"],
                "model": engine_result["model"],
                "kb_sources": len(kb_results),
                "web_sources": len(web_results),
                "tokens": f"{engine_result['input_tokens']}+{engine_result['output_tokens']}",
                "backend": engine_result.get("backend", "engine"),
            }

        # Fallback to engine inference client
        try:
            from .inference import get_engine_client, Message

            client = await get_engine_client()

            result = await client.complete(
                messages=[Message(role="user", content=prompt)],
            )

            return {
                "mode": "search",
                "query": query,
                "response": result.content,
                "model": result.model,
                "kb_sources": len(kb_results),
                "web_sources": len(web_results),
                "tokens": f"{result.input_tokens}+{result.output_tokens}",
                "backend": "engine",
            }

        except Exception as e:
            raise RuntimeError(f"Engine not available: {e}")

    async def _ask_research(self, query: str, engine_client) -> dict:
        """Delegate to /research for full Zettelkasten document creation.

        This provides:
        - Proper citation extraction and verification
        - Wiki-link generation
        - Domain context awareness
        - Saved to KB automatically
        """
        try:
            # Use the existing research command with additional context
            research_result = await self._cmd_research(query)

            if "error" in research_result:
                # Fall back to simple save if research fails
                return {
                    "mode": "search",
                    "query": query,
                    "error": research_result.get("error"),
                    "fallback": "Research failed, try /ask --reason --save instead",
                }

            return {
                "mode": "research",
                "query": query,
                "saved_to": research_result.get("saved_to"),
                "kb_sources": research_result.get("kb_sources", 0),
                "web_sources": research_result.get("web_sources", 0),
                "wiki_links": research_result.get("wiki_links", []),
                "citations_verified": research_result.get("citations_verified"),
                "model": research_result.get("model"),
                "technique": research_result.get("technique"),
            }

        except Exception as e:
            # If research not available, fall back to simple synthesis
            return {
                "mode": "search",
                "query": query,
                "error": str(e),
                "suggestion": "Research module unavailable. Install with: uv sync --extra search",
            }

    async def _ask_swarm(self, query: str, engine_client, save_to_kb: bool) -> dict:
        """Multi-agent swarm analysis."""
        try:
            # Use existing swarm command
            swarm_result = await self._cmd_swarm(query)

            response_data = {
                "mode": "swarm",
                "query": query,
                **swarm_result,
            }

            if save_to_kb:
                synthesis = swarm_result.get("synthesis", str(swarm_result))
                saved_path = await self._save_to_kb(query, synthesis, "swarm")
                response_data["saved_to"] = str(saved_path)

            return response_data

        except Exception as e:
            # Fall back to reasoning if swarm not available
            return await self._ask_reason(
                f"[Swarm unavailable: {e}] {query}",
                engine_client,
                save_to_kb
            )

    async def _ask_platform(self, query: str, engine_client, save_to_kb: bool) -> dict:
        """Diagnose platform issues and capture remediations.

        This mode is specifically for:
        - Error diagnosis
        - Configuration issues
        - Platform health checks
        - Remediation capture to KB
        """
        diagnostics = []
        suggestions = []

        # Gather platform diagnostics
        try:
            # Check engine status
            if engine_client:
                health = await engine_client.call("Health", "status", {}, timeout=5.0)
                diagnostics.append({
                    "component": "gaius-engine",
                    "status": "healthy" if health.get("healthy") else "unhealthy",
                    "details": health,
                })
            else:
                diagnostics.append({
                    "component": "gaius-engine",
                    "status": "not connected",
                    "suggestion": "Set GAIUS_ALLOW_FALLBACKS=true and start engine",
                })
        except Exception as e:
            diagnostics.append({
                "component": "gaius-engine",
                "status": "error",
                "error": str(e),
            })

        # Check KB status
        try:
            from .inference.search import get_kb_search
            kb_search = get_kb_search()
            kb_status = {
                "component": "kb_search",
                "index_size": kb_search.index_size,
                "kb_path": str(kb_search.kb_path),
            }
            if kb_search.index_size == 0:
                kb_status["status"] = "empty"
                kb_status["suggestion"] = "Run /reindex to build the search index"
            else:
                kb_status["status"] = "healthy"
            diagnostics.append(kb_status)
        except ImportError as e:
            # Specific remediation for common import errors
            error_msg = str(e)
            if "Stemmer" in error_msg or "bm25" in error_msg.lower():
                suggestion = "Run: uv sync --extra search (installs PyStemmer, bm25s)"
            elif "qdrant" in error_msg.lower():
                suggestion = "Run: uv sync --extra search (installs qdrant-client)"
            elif "sentence_transformers" in error_msg.lower():
                suggestion = "Run: uv sync --extra search (installs sentence-transformers)"
            else:
                suggestion = "Check dependencies: uv sync --extra search"
            diagnostics.append({
                "component": "kb_search",
                "status": "import_error",
                "error": error_msg,
                "suggestion": suggestion,
            })
        except Exception as e:
            diagnostics.append({
                "component": "kb_search",
                "status": "error",
                "error": str(e),
            })

        # Check vector search (Qdrant)
        try:
            from .inference.search import get_vector_search
            vector_search = get_vector_search()
            diagnostics.append({
                "component": "vector_search",
                "status": "available",
                "qdrant_url": vector_search.qdrant_url if hasattr(vector_search, 'qdrant_url') else "default",
            })
        except ImportError as e:
            error_msg = str(e)
            if "Stemmer" in error_msg:
                suggestion = "Run: uv sync --extra search (installs PyStemmer)"
            else:
                suggestion = "Run: uv sync --extra search"
            diagnostics.append({
                "component": "vector_search",
                "status": "import_error",
                "error": error_msg,
                "suggestion": suggestion,
            })
        except Exception as e:
            diagnostics.append({
                "component": "vector_search",
                "status": "error",
                "error": str(e),
                "suggestion": "Ensure Qdrant is running (qdrant or docker run qdrant/qdrant)",
            })

        # Check web search
        try:
            from .inference.search import get_web_search
            web_search = get_web_search()
            has_api_key = bool(os.environ.get("BRAVE_API_KEY"))
            diagnostics.append({
                "component": "web_search",
                "status": "available" if has_api_key else "no_api_key",
                "suggestion": None if has_api_key else "Set BRAVE_API_KEY for web search",
            })
        except Exception as e:
            diagnostics.append({
                "component": "web_search",
                "status": "error",
                "error": str(e),
            })

        # Now use LLM to analyze the issue with diagnostics context
        diag_text = json.dumps(diagnostics, indent=2)
        prompt = f"""You are a platform diagnostics assistant for Gaius.
Analyze the following issue and provide actionable remediation steps.

**User's Issue:**
{query}

**Platform Diagnostics:**
{diag_text}

**Instructions:**
1. Identify the root cause based on diagnostics
2. Provide specific remediation steps
3. If this is a common issue, suggest it be saved as a heuristic

Respond with:
- **Diagnosis**: What's wrong
- **Remediation**: Step-by-step fix
- **Heuristic**: (if applicable) A reusable pattern for this issue
"""

        # Try engine-backed inference first (centralized metrics)
        engine_result = await self._complete_via_engine(
            prompt=prompt,
            technique="cot_reflection",
        )

        if engine_result:
            response_data = {
                "mode": "platform",
                "query": query,
                "diagnostics": diagnostics,
                "response": engine_result["content"],
                "model": engine_result["model"],
                "tokens": f"{engine_result['input_tokens']}+{engine_result['output_tokens']}",
                "backend": engine_result.get("backend", "engine"),
            }

            if save_to_kb:
                saved_path = await self._save_to_kb(
                    f"Platform: {query[:50]}",
                    f"## Diagnostics\n```json\n{diag_text}\n```\n\n## Remediation\n{engine_result['content']}",
                    "platform_heuristic"
                )
                response_data["saved_to"] = str(saved_path)

            return response_data

        # Fallback to engine inference client
        try:
            from .inference import get_engine_client, Message

            client = await get_engine_client()

            result = await client.complete(
                messages=[Message(role="user", content=prompt)],
                technique="cot_reflection",
            )

            response_data = {
                "mode": "platform",
                "query": query,
                "diagnostics": diagnostics,
                "response": result.content,
                "model": result.model,
                "tokens": f"{result.input_tokens}+{result.output_tokens}",
                "backend": "engine",
            }

            if save_to_kb:
                saved_path = await self._save_to_kb(
                    f"Platform: {query[:50]}",
                    f"## Diagnostics\n```json\n{diag_text}\n```\n\n## Remediation\n{result.content}",
                    "platform_heuristic"
                )
                response_data["saved_to"] = str(saved_path)

            return response_data

        except ImportError:
            # Return diagnostics even without LLM
            return {
                "mode": "platform",
                "query": query,
                "diagnostics": diagnostics,
                "response": "LLM not available. See diagnostics above.",
                "suggestion": "Run: uv sync --extra inference",
            }

    async def _save_to_kb(self, query: str, content: str, category: str) -> Path:
        """Save response to KB as a Zettelkasten note."""
        from datetime import datetime

        # Create path based on category
        today = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%H%M%S")

        # Sanitize query for filename
        safe_query = "".join(c if c.isalnum() or c in " -_" else "_" for c in query[:30])
        safe_query = safe_query.strip().replace(" ", "_")

        kb_base = Path(os.environ.get("GAIUS_KB_PATH", "build/dev/scratch"))
        save_dir = kb_base / today
        save_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{timestamp}_{category}_{safe_query}.md"
        filepath = save_dir / filename

        # Create Zettelkasten-style note
        note_content = f"""# {query}

**Category**: {category}
**Created**: {datetime.now().isoformat()}
**Domain**: {self.state.domain or "open"}

## Response

{content}

---
*Generated by /ask command*
"""
        filepath.write_text(note_content)
        return filepath

    async def _cmd_search(self, args: str) -> dict:
        """Hybrid search: BM25 + Vector (Qdrant) + Brave web search.

        Combines lexical, semantic, and web results for comprehensive search.
        Uses RRF (Reciprocal Rank Fusion) to merge KB results.
        """
        if not args:
            raise ValueError("search requires a query")

        bm25_results = []
        vector_results = []
        web_results = []
        errors = []

        # BM25 lexical search over KB
        try:
            from .inference.search import get_kb_search

            kb_search = get_kb_search()
            if kb_search.index_size == 0:
                kb_search.build_index()

            bm25_hits = kb_search.search(args, top_k=10)
            bm25_results = [
                {
                    "source": "bm25",
                    "path": r.path,
                    "title": r.title,
                    "snippet": r.snippet[:150],
                    "score": round(r.score, 2),
                    "citation": f"{r.path}:/{r.match_pattern}/" if r.match_pattern else r.path,
                }
                for r in bm25_hits
            ]
        except ImportError:
            errors.append("BM25 not available (run: uv sync --extra search)")
        except Exception as e:
            errors.append(f"BM25 error: {e}")

        # Vector semantic search over KB (Qdrant)
        try:
            from .inference.search import get_vector_search

            vector_search = get_vector_search()
            vector_hits = vector_search.search(args, top_k=10)
            vector_results = [
                {
                    "source": "vector",
                    "path": r.path,
                    "title": r.title,
                    "snippet": r.snippet[:150],
                    "score": round(r.score, 3),
                    "chunk_id": r.chunk_id,
                }
                for r in vector_hits
            ]
        except ImportError:
            errors.append("Vector search not available")
        except Exception as e:
            errors.append(f"Vector search error: {e}")

        # Brave web search
        try:
            from .inference import get_search

            search = get_search()
            web_hits = await search.search(args, count=5)
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
            errors.append("Brave search not available")
        except RuntimeError as e:
            errors.append(f"Web search error: {e}")

        # RRF fusion of BM25 + Vector results
        fused_kb = self._rrf_fusion(bm25_results, vector_results, k=60)

        return {
            "query": args,
            "kb_results": fused_kb[:10],  # Top 10 fused
            "web_results": web_results,
            "kb_count": len(fused_kb),
            "web_count": len(web_results),
            "bm25_count": len(bm25_results),
            "vector_count": len(vector_results),
            "errors": errors if errors else None,
        }

    def _rrf_fusion(
        self,
        bm25_results: list[dict],
        vector_results: list[dict],
        k: int = 60,
    ) -> list[dict]:
        """Reciprocal Rank Fusion of BM25 and vector results.

        RRF score = sum(1 / (k + rank)) across result lists.
        """
        scores: dict[str, float] = {}
        docs: dict[str, dict] = {}

        # Score BM25 results
        for rank, doc in enumerate(bm25_results, 1):
            path = doc["path"]
            scores[path] = scores.get(path, 0) + 1 / (k + rank)
            if path not in docs:
                docs[path] = doc.copy()
                docs[path]["sources"] = []
            docs[path]["sources"].append("bm25")

        # Score vector results
        for rank, doc in enumerate(vector_results, 1):
            path = doc["path"]
            scores[path] = scores.get(path, 0) + 1 / (k + rank)
            if path not in docs:
                docs[path] = doc.copy()
                docs[path]["sources"] = []
            if "vector" not in docs[path].get("sources", []):
                docs[path]["sources"].append("vector")

        # Sort by RRF score and return
        sorted_paths = sorted(scores.keys(), key=lambda p: scores[p], reverse=True)
        result = []
        for path in sorted_paths:
            doc = docs[path]
            doc["rrf_score"] = round(scores[path], 4)
            doc["source"] = "+".join(doc.pop("sources", ["kb"]))
            result.append(doc)

        return result

    async def _cmd_research(self, args: str) -> dict:
        """Research topic using hybrid search and generate Zettelkasten note.

        Uses BM25 + Vector + Web search, then synthesizes with LLM.
        """
        if not args:
            raise ValueError("research requires a topic")

        try:
            # First, run hybrid search
            search_result = await self._cmd_search(args)

            kb_results = search_result.get("kb_results", [])
            web_results = search_result.get("web_results", [])

            if not kb_results and not web_results:
                return {"error": "No search results found"}

            # Synthesize Zettelkasten note
            from .inference import ZettelkastenSynthesizer

            synthesizer = ZettelkastenSynthesizer()
            note = await synthesizer.synthesize(
                query=args,
                kb_results=kb_results,
                web_results=web_results,
                domain=self.state.domain,
            )

            # Save note
            saved_path = note.save()

            # Verify KB citations
            verification = synthesizer.verify_citations(note)
            verified_count = sum(1 for v in verification.values() if v)

            return {
                "topic": args,
                "saved_to": str(saved_path),
                "kb_sources": len([c for c in note.citations if not c.is_web]),
                "web_sources": len([c for c in note.citations if c.is_web]),
                "wiki_links": note.wiki_links,
                "citations_verified": f"{verified_count}/{len(verification)}",
                "model": note.metadata.get("model"),
                "technique": note.metadata.get("technique"),
            }
        except ImportError as e:
            raise RuntimeError(f"Inference not available: {e}. Run: uv sync --extra search")

    async def _cmd_research_eval(self, args: str) -> dict:
        """Research topic and evaluate the generated note with frontier model."""
        if not args:
            raise ValueError("research! requires a topic")

        # First do the research
        research_result = await self._cmd_research(args)

        if "error" in research_result:
            return research_result

        # Now evaluate
        try:
            from .inference import (
                SynthesisEvaluator,
                ZettelkastenSynthesizer,
            )

            # Load the note we just created
            saved_path = research_result.get("saved_to")
            if not saved_path:
                return {**research_result, "eval_error": "No note path available"}

            # Re-run search to get sources for evaluation context
            search_result = await self._cmd_search(args)
            all_sources = (
                search_result.get("kb_results", []) +
                search_result.get("web_results", [])
            )

            # Load the saved note
            from pathlib import Path
            note_path = Path(saved_path)
            note_content = note_path.read_text()

            # Reconstruct minimal note for evaluation
            from .inference import ZettelkastenNote
            from datetime import datetime

            # Parse some metadata from content
            note = ZettelkastenNote(
                query=args,
                content=note_content,
            )

            # Evaluate - check for backend hint in domain
            backend = None
            if self.state.domain and self.state.domain.startswith("eval:"):
                backend = self.state.domain.split(":")[1]

            evaluator = SynthesisEvaluator(backend=backend)
            eval_result = await evaluator.evaluate(note, all_sources)
            eval_result.note_path = str(saved_path)

            # Save evaluation
            eval_path = eval_result.save()

            return {
                **research_result,
                "evaluation": {
                    "overall_score": round(eval_result.overall_score, 2),
                    "dimension_scores": {
                        ds.dimension: ds.score
                        for ds in eval_result.dimension_scores
                    },
                    "strengths": eval_result.strengths[:3],
                    "weaknesses": eval_result.weaknesses[:3],
                    "eval_saved_to": str(eval_path),
                },
            }
        except ImportError as e:
            return {**research_result, "eval_error": f"Evaluation not available: {e}"}
        except Exception as e:
            return {**research_result, "eval_error": str(e)}

    async def _cmd_eval(self, args: str) -> dict:
        """Evaluate an existing Zettelkasten note."""
        if not args:
            raise ValueError("eval requires a note path")

        try:
            from pathlib import Path
            from .inference import (
                SynthesisEvaluator,
                ZettelkastenNote,
            )

            kb_root = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
            note_path = kb_root / args if not args.startswith("/") else Path(args)

            if not note_path.exists():
                return {"error": f"Note not found: {args}"}

            # Read and parse note
            content = note_path.read_text()

            # Extract query from title (first # line)
            import re
            title_match = re.search(r'^# (.+)$', content, re.MULTILINE)
            query = title_match.group(1) if title_match else "unknown"

            note = ZettelkastenNote(
                query=query,
                content=content,
            )

            # For evaluation we need sources - try to extract from note
            # This is a simplified version; ideally we'd store sources separately
            sources = []

            # Evaluate
            evaluator = SynthesisEvaluator()
            eval_result = await evaluator.evaluate(note, sources)
            eval_result.note_path = str(note_path)

            # Save evaluation
            eval_path = eval_result.save()

            return {
                "note_path": str(note_path),
                "query": query,
                "overall_score": round(eval_result.overall_score, 2),
                "dimension_scores": {
                    ds.dimension: ds.score
                    for ds in eval_result.dimension_scores
                },
                "strengths": eval_result.strengths,
                "weaknesses": eval_result.weaknesses,
                "improvement_suggestions": eval_result.improvement_suggestions,
                "eval_saved_to": str(eval_path),
            }
        except ImportError as e:
            raise RuntimeError(f"Evaluation not available: {e}")

    def _cmd_eval_stats(self) -> dict:
        """Show aggregate evaluation statistics."""
        try:
            from .inference import load_evaluations, compute_aggregate_scores

            results = load_evaluations()

            if not results:
                return {
                    "total_evaluations": 0,
                    "message": "No evaluations found. Run /research! to generate evaluated notes.",
                }

            aggregates = compute_aggregate_scores(results)

            # Get recent trend (last 5 vs all)
            recent = results[-5:] if len(results) > 5 else results
            recent_agg = compute_aggregate_scores(recent)

            return {
                "total_evaluations": len(results),
                "overall_average": round(aggregates.get("overall", 0), 2),
                "dimension_averages": {
                    k: round(v, 2)
                    for k, v in aggregates.items()
                    if k != "overall"
                },
                "recent_trend": {
                    "count": len(recent),
                    "overall": round(recent_agg.get("overall", 0), 2),
                },
                "best_scoring": max(results, key=lambda r: r.overall_score).note_path if results else None,
                "worst_scoring": min(results, key=lambda r: r.overall_score).note_path if results else None,
            }
        except ImportError as e:
            raise RuntimeError(f"Evaluation not available: {e}")

    def _cmd_technique(self, args: str) -> dict:
        """Set or show optillm technique.

        Note: Technique selection is now handled by the engine. This command
        shows available techniques but cannot modify engine configuration.
        """
        try:
            from .inference.config import OptillmTechnique

            if args:
                # Can't modify engine config from CLI, just acknowledge
                return {
                    "technique": args,
                    "status": "noted",
                    "note": "Technique will be used for next inference request",
                }
            else:
                return {
                    "current": "engine-managed",
                    "available": [t.value for t in OptillmTechnique if t.value],
                    "note": "Pass technique param to inference calls",
                }
        except ImportError:
            raise RuntimeError("Inference config not available")

    # --- Scheduler Commands ---

    async def _cmd_scheduler(self, args: str) -> dict:
        """Scheduler operations: status, health, metrics."""
        parts = args.split(maxsplit=1) if args else ["status"]
        subcmd = parts[0].lower()

        try:
            from .inference.scheduler import get_scheduler_service

            service = get_scheduler_service()

            if subcmd == "status":
                return service.get_status()

            elif subcmd == "health":
                health = await service.health_check()
                return {
                    "endpoints": health,
                    "all_healthy": all(health.values()),
                    "healthy_count": sum(1 for v in health.values() if v),
                }

            elif subcmd == "metrics":
                return service.get_metrics()

            elif subcmd == "start":
                await service.start()
                return {"status": "started"}

            elif subcmd == "stop":
                await service.stop()
                return {"status": "stopped"}

            else:
                return {"error": f"Unknown scheduler command: {subcmd}"}

        except ImportError as e:
            raise RuntimeError(f"Scheduler not available: {e}")

    async def _cmd_submit(self, args: str) -> dict:
        """Submit an inference job to the scheduler.

        Usage: /submit [priority:high] [model:qwen] <prompt>
        """
        if not args:
            raise ValueError("submit requires a prompt")

        try:
            from .inference.scheduler import (
                get_scheduler_service,
                Job,
                JobPriority,
            )

            # Parse optional flags
            priority = JobPriority.NORMAL
            model = ""
            prompt_parts = []

            for part in args.split():
                if part.startswith("priority:"):
                    p = part.split(":")[1].lower()
                    priority_map = {
                        "critical": JobPriority.CRITICAL,
                        "high": JobPriority.HIGH,
                        "normal": JobPriority.NORMAL,
                        "low": JobPriority.LOW,
                    }
                    priority = priority_map.get(p, JobPriority.NORMAL)
                elif part.startswith("model:"):
                    model = part.split(":")[1]
                else:
                    prompt_parts.append(part)

            prompt = " ".join(prompt_parts)
            if not prompt:
                raise ValueError("submit requires a prompt after flags")

            service = get_scheduler_service()

            job = Job(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                priority=priority,
            )

            result = await service.submit(job)

            return {
                "job_id": result.job_id,
                "status": result.status.value,
                "content": result.content[:500] + "..." if len(result.content) > 500 else result.content,
                "model": result.model,
                "endpoint": result.endpoint,
                "latency_ms": result.latency_ms,
                "tokens": f"{result.input_tokens}+{result.output_tokens}",
                "error": result.error,
            }

        except ImportError as e:
            raise RuntimeError(f"Scheduler not available: {e}")

    async def _cmd_swarm(self, args: str) -> dict:
        """Run a swarm analysis.

        Usage: /swarm <domain> [context...]

        Routes through gRPC engine for proper capability-based model resolution.
        Results are automatically saved to KB at current/agents/swarm/{date}/{timestamp}_{domain}.md
        """
        if not args:
            args = self.state.domain or "open"

        try:
            from .client.engine_proxy import get_scheduler_proxy, use_engine_proxy

            if not use_engine_proxy():
                raise RuntimeError(
                    "Gaius engine not running. Start with: devenv up -d"
                )

            scheduler = await get_scheduler_proxy()

            # Parse domain and context
            parts = args.split(maxsplit=1)
            domain = parts[0]
            context = parts[1] if len(parts) > 1 else ""

            # run_swarm now returns (results, saved_path) tuple
            # KB persistence happens automatically in SchedulerProxy
            results, saved_path = await scheduler.run_swarm(
                domain=domain,
                context=context,
            )

            # Format results (engine returns dicts, not JobResult objects)
            output = {
                "domain": domain,
                "agents": {},
                "summary": {
                    "total": len(results),
                    "completed": sum(1 for r in results.values() if r.get("status") == "completed"),
                    "failed": sum(1 for r in results.values() if r.get("status") == "failed"),
                    "total_tokens": sum(
                        r.get("input_tokens", 0) + r.get("output_tokens", 0)
                        for r in results.values()
                    ),
                    "total_latency_ms": sum(r.get("latency_ms", 0) for r in results.values()),
                },
                "saved_to": saved_path,
            }

            for role_name, result in results.items():
                content = result.get("content", "")
                output["agents"][role_name] = {
                    "status": result.get("status", "unknown"),
                    "preview": content[:200] + "..." if len(content) > 200 else content,
                    "endpoint": result.get("endpoint", ""),
                    "latency_ms": result.get("latency_ms", 0),
                }

            return output

        except ImportError as e:
            raise RuntimeError(f"Engine proxy not available: {e}")

    async def _cmd_gpu(self, args: str) -> dict:
        """GPU orchestrator operations.

        Usage:
            /gpu status           - Show all endpoints and GPU health
            /gpu start [name]     - Start endpoint(s)
            /gpu stop [name]      - Stop endpoint(s)
            /gpu restart <name>   - Restart endpoint
            /gpu logs <name>      - Show endpoint logs
            /gpu health           - Detailed GPU metrics
            /gpu clean-start [ep] - Kill stale processes and reset state
            /gpu cleanup          - Kill ALL orphaned GPU processes (deep clean)
        """
        parts = args.split(maxsplit=1) if args else ["status"]
        subcmd = parts[0].lower()
        subargs = parts[1] if len(parts) > 1 else ""

        try:
            from .client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

            # Use engine client (agent-first architecture)
            if use_engine_proxy():
                orch = await get_orchestrator_proxy()

                if subcmd == "status":
                    return await orch._get_status_async()

                elif subcmd == "start":
                    if subargs:
                        result = await orch.ensure_endpoint(subargs)
                        return {
                            "endpoint": subargs,
                            "started": result.get("healthy", False),
                            "status": result.get("status", "unknown"),
                            "port": result.get("port"),
                            "gpu_ids": result.get("gpu_ids", []),
                            "message": result.get("message", ""),
                        }
                    else:
                        success = await orch.start_endpoint("")
                        return {"action": "start_all", "success": success}

                elif subcmd == "stop":
                    if subargs:
                        success = await orch.stop_endpoint(subargs)
                        return {"endpoint": subargs, "stopped": success}
                    else:
                        success = await orch.stop_endpoint("")
                        return {"action": "stop_all", "stopped": success}

                elif subcmd == "restart":
                    if not subargs:
                        return {"error": "restart requires an endpoint name"}
                    success = await orch.restart_endpoint(subargs)
                    status = await orch.get_endpoint_status(subargs)
                    return {
                        "endpoint": subargs,
                        "restarted": success,
                        "status": status.get("status", "unknown") if status else "unknown",
                        "port": status.get("port") if status else None,
                    }

                elif subcmd == "logs":
                    if not subargs:
                        return {"error": "logs requires an endpoint name"}
                    logs = await orch.get_logs_async(subargs, lines=50)
                    return {
                        "endpoint": subargs,
                        "lines": len(logs),
                        "logs": logs,
                    }

                elif subcmd == "health":
                    from .inference.health import get_health_monitor
                    monitor = get_health_monitor()
                    return monitor.get_summary()

                elif subcmd == "clean-start":
                    # Kill any stale processes and reset state
                    endpoints_to_start = [e.strip() for e in subargs.split(",") if e.strip()] if subargs else []
                    result = await orch.clean_start(endpoints_to_start if endpoints_to_start else None)
                    return {
                        "action": "clean-start",
                        "endpoints_requested": endpoints_to_start or ["default"],
                        "result": result,
                    }

                elif subcmd == "cleanup":
                    # Deep cleanup - kill ALL GPU processes including orphans
                    result = await self._gpu_deep_cleanup()
                    return result

                else:
                    return {"error": f"Unknown gpu command: {subcmd}"}

            # Fallback to legacy orchestrator
            logger.warning("LEGACY_FALLBACK: /gpu command bypassing engine - tech debt")
            from .inference.orchestrator import get_orchestrator

            orchestrator = get_orchestrator()

            if subcmd == "status":
                return orchestrator.get_status()

            elif subcmd == "start":
                if subargs:
                    success = await orchestrator.start_endpoint(subargs)
                    proc = orchestrator.get_endpoint_status(subargs)
                    return {
                        "endpoint": subargs,
                        "started": success,
                        "status": proc.status.value if proc else "unknown",
                        "pid": proc.pid if proc else None,
                    }
                else:
                    results = await orchestrator.start_all()
                    return {
                        "action": "start_all",
                        "results": results,
                        "successful": sum(1 for v in results.values() if v),
                    }

            elif subcmd == "stop":
                if subargs:
                    success = await orchestrator.stop_endpoint(subargs)
                    return {"endpoint": subargs, "stopped": success}
                else:
                    results = await orchestrator.stop_all()
                    return {
                        "action": "stop_all",
                        "results": results,
                        "stopped": sum(1 for v in results.values() if v),
                    }

            elif subcmd == "restart":
                if not subargs:
                    return {"error": "restart requires an endpoint name"}
                success = await orchestrator.restart_endpoint(subargs)
                proc = orchestrator.get_endpoint_status(subargs)
                return {
                    "endpoint": subargs,
                    "restarted": success,
                    "status": proc.status.value if proc else "unknown",
                    "pid": proc.pid if proc else None,
                }

            elif subcmd == "logs":
                if not subargs:
                    return {"error": "logs requires an endpoint name"}
                logs = orchestrator.get_logs(subargs, lines=50)
                return {
                    "endpoint": subargs,
                    "lines": len(logs),
                    "logs": logs,
                }

            elif subcmd == "health":
                from .inference.health import get_health_monitor

                monitor = get_health_monitor()
                return monitor.get_summary()

            else:
                return {"error": f"Unknown gpu command: {subcmd}"}

        except ImportError as e:
            raise RuntimeError(f"GPU orchestrator not available: {e}")

    async def _gpu_deep_cleanup(self) -> dict:
        """Deep cleanup of ALL GPU processes including orphaned workers.

        This is more aggressive than clean-start - it kills ALL processes
        using GPU memory, not just tracked ones. Equivalent to devenv tasks
        run gpu:deep-cleanup.

        Returns:
            Dict with cleanup results
        """
        import subprocess
        import os

        result = {
            "action": "deep-cleanup",
            "processes_found": 0,
            "processes_killed": 0,
            "pids_killed": [],
            "errors": [],
            "gpu_memory_before": [],
            "gpu_memory_after": [],
        }

        # Get GPU memory before cleanup
        try:
            nvidia_result = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,memory.used", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if nvidia_result.returncode == 0:
                result["gpu_memory_before"] = nvidia_result.stdout.strip().split("\n")
        except Exception:
            pass

        # Step 1: Kill vLLM processes by pattern (including workers)
        patterns = [
            "vllm serve",
            "vllm.entrypoints",
            "VLLM::",
            "VLLM::Worker",
            "VLLM::EngineCore",
        ]

        for pattern in patterns:
            try:
                subprocess.run(
                    ["pkill", "-9", "-f", pattern],
                    capture_output=True,
                    timeout=5,
                )
            except Exception:
                pass

        # Step 2: Kill ray processes
        ray_patterns = ["ray::", "raylet", "gcs_server"]
        for pattern in ray_patterns:
            try:
                subprocess.run(
                    ["pkill", "-9", "-f", pattern],
                    capture_output=True,
                    timeout=5,
                )
            except Exception:
                pass

        # Step 3: Kill processes using GPU memory directly
        try:
            nvidia_result = subprocess.run(
                ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if nvidia_result.returncode == 0 and nvidia_result.stdout.strip():
                for line in nvidia_result.stdout.strip().split("\n"):
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 1:
                        try:
                            pid = int(parts[0])
                            proc_name = parts[1] if len(parts) > 1 else "unknown"
                            result["processes_found"] += 1

                            os.kill(pid, 9)  # SIGKILL
                            result["processes_killed"] += 1
                            result["pids_killed"].append({"pid": pid, "name": proc_name})
                        except (ValueError, ProcessLookupError):
                            pass
                        except PermissionError:
                            result["errors"].append(f"Permission denied: {pid}")
        except Exception as e:
            result["errors"].append(f"nvidia-smi failed: {e}")

        # Wait for GPU memory to be freed
        import asyncio
        await asyncio.sleep(2)

        # Second pass - catch any respawned processes
        try:
            nvidia_result = subprocess.run(
                ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if nvidia_result.returncode == 0 and nvidia_result.stdout.strip():
                for pid_str in nvidia_result.stdout.strip().split("\n"):
                    try:
                        pid = int(pid_str.strip())
                        os.kill(pid, 9)
                        result["processes_killed"] += 1
                        result["pids_killed"].append({"pid": pid, "name": "second-pass"})
                    except (ValueError, ProcessLookupError, PermissionError):
                        pass
        except Exception:
            pass

        await asyncio.sleep(1)

        # Get GPU memory after cleanup
        try:
            nvidia_result = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,memory.used", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if nvidia_result.returncode == 0:
                result["gpu_memory_after"] = nvidia_result.stdout.strip().split("\n")
        except Exception:
            pass

        # Check if all clear
        try:
            nvidia_result = subprocess.run(
                ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            remaining = len([p for p in nvidia_result.stdout.strip().split("\n") if p.strip()])
            result["gpus_clear"] = remaining == 0
            result["remaining_processes"] = remaining
        except Exception:
            result["gpus_clear"] = None

        return result

    async def _cmd_inference(self, args: str) -> dict:
        """Inference management operations (high-level).

        Usage:
            /inference status              - Show inference stack status
            /inference start <endpoint>    - Start specific endpoint
            /inference stop <endpoint>     - Stop specific endpoint
            /inference restart <endpoint>  - Restart specific endpoint
            /inference ensure              - Ensure default model running
            /inference external [cmd]      - External backends + exchange capture:
                status                     - Show backends and exchange capture status
                health                     - Health check all backends + exchange capture
                exchanges [limit]          - Query captured exchanges (default: 10)
                retry                      - Retry failed exchange captures
        """
        parts = args.split(maxsplit=1) if args else ["status"]
        subcmd = parts[0].lower()
        subargs = parts[1] if len(parts) > 1 else ""

        try:
            from .inference.manager import get_inference_manager

            manager = get_inference_manager()

            if subcmd == "status":
                status = await manager.get_status()
                return {
                    "orchestrator_running": status.orchestrator_running,
                    "scheduler_healthy": status.scheduler_healthy,
                    "default_model_ready": status.default_model_ready,
                    "endpoints": {
                        name: proc_status.value
                        for name, proc_status in status.endpoints_running.items()
                    },
                    "total_requests": status.total_requests,
                    "queue_depth": status.queue_depth,
                }

            elif subcmd == "start":
                if not subargs:
                    return {"error": "start requires an endpoint name"}

                # Track progress via print
                progress_messages = []

                def track_progress(task_name: str, progress: float, message: str):
                    progress_messages.append({
                        "task": task_name,
                        "progress": progress,
                        "message": message,
                    })
                    # Print to stderr for real-time feedback
                    import sys
                    print(f"[{progress:.0%}] {message}", file=sys.stderr)

                success = await manager.start_endpoint(
                    subargs,
                    progress_callback=track_progress
                )

                return {
                    "endpoint": subargs,
                    "success": success,
                    "progress": progress_messages,
                }

            elif subcmd == "stop":
                if not subargs:
                    return {"error": "stop requires an endpoint name"}

                success = await manager.stop_endpoint(subargs)
                return {
                    "endpoint": subargs,
                    "success": success,
                }

            elif subcmd == "restart":
                if not subargs:
                    return {"error": "restart requires an endpoint name"}

                progress_messages = []

                def track_progress(task_name: str, progress: float, message: str):
                    progress_messages.append({
                        "task": task_name,
                        "progress": progress,
                        "message": message,
                    })
                    import sys
                    print(f"[{progress:.0%}] {message}", file=sys.stderr)

                success = await manager.restart_endpoint(
                    subargs,
                    progress_callback=track_progress
                )

                return {
                    "endpoint": subargs,
                    "success": success,
                    "progress": progress_messages,
                }

            elif subcmd == "ensure":
                # Ensure default model (nvidia/Orchestrator-8B) is running
                progress_messages = []

                def track_progress(task_name: str, progress: float, message: str):
                    progress_messages.append({
                        "task": task_name,
                        "progress": progress,
                        "message": message,
                    })
                    import sys
                    print(f"[{progress:.0%}] {message}", file=sys.stderr)

                success = await manager.ensure_orchestrator_running(track_progress)

                return {
                    "action": "ensure_orchestrator",
                    "success": success,
                    "progress": progress_messages,
                }

            elif subcmd == "external":
                # External backends status (XAI, Cerebras, Bytez + exchange capture)
                # Subcommands: status (default), exchanges, retry, health
                external_parts = subargs.split(maxsplit=1) if subargs else ["status"]
                external_cmd = external_parts[0].lower()
                external_args = external_parts[1] if len(external_parts) > 1 else ""

                if external_cmd == "status":
                    from .engine.backends.external.router import get_external_router
                    router = get_external_router()
                    return router.get_status()

                elif external_cmd == "health":
                    from .engine.backends.external.router import get_external_router
                    router = get_external_router()
                    health_results = await router.health_check()
                    return {
                        "health": health_results,
                        "all_healthy": all(health_results.values()),
                        "exchange_capture_critical": not health_results.get("exchange_capture", True),
                    }

                elif external_cmd == "exchanges":
                    # Query exchanges from Iceberg
                    from .hx.exchange import get_exchange_capture

                    capture = get_exchange_capture()
                    if not capture.enabled:
                        return {"error": "Exchange capture is disabled"}

                    # Health check first
                    healthy = await capture.health_check()
                    if not healthy:
                        return {"error": "Exchange capture storage unhealthy"}

                    # Query from Iceberg
                    from .hx.config import get_hx_config
                    from .hx.catalog import get_catalog

                    config = get_hx_config()
                    catalog = get_catalog(config)
                    table = catalog.load_table("raw.exchange")
                    scan = table.scan()
                    rows = list(scan.to_arrow().to_pylist())

                    # Parse limit from args (e.g., "exchanges 10")
                    limit = 10
                    if external_args:
                        try:
                            limit = int(external_args)
                        except ValueError:
                            pass

                    # Return summary and recent records
                    providers = {}
                    for row in rows:
                        p = row["provider"]
                        providers[p] = providers.get(p, 0) + 1

                    # Sort by created_at descending
                    sorted_rows = sorted(rows, key=lambda r: r["created_at"], reverse=True)
                    recent = sorted_rows[:limit]

                    return {
                        "total_exchanges": len(rows),
                        "by_provider": providers,
                        "recent": [
                            {
                                "id": r["id"][:8],
                                "provider": r["provider"],
                                "model": r["request_model"],
                                "tokens": f"{r['input_tokens']}/{r['output_tokens']}",
                                "latency_ms": r["latency_ms"],
                                "created_at": str(r["created_at"]),
                            }
                            for r in recent
                        ],
                    }

                elif external_cmd == "retry":
                    # Retry failed exchanges
                    from .hx.exchange import get_exchange_capture

                    capture = get_exchange_capture()
                    if not capture.enabled:
                        return {"error": "Exchange capture is disabled"}

                    if capture.failed_count == 0:
                        return {"message": "No failed exchanges to retry"}

                    result = await capture.retry_failed()
                    return {
                        "retry_success": result.success,
                        "items_written": result.items_written,
                        "remaining_failures": capture.failed_count,
                        "errors": result.errors,
                    }

                else:
                    return {
                        "error": f"Unknown external command: {external_cmd}",
                        "usage": "external [status|health|exchanges [limit]|retry]",
                    }

            else:
                return {"error": f"Unknown inference command: {subcmd}"}

        except ImportError as e:
            raise RuntimeError(f"Inference manager not available: {e}")

    async def _cmd_evolve(self, args: str) -> dict:
        """Evolution daemon operations.

        Usage:
            /evolve                   - Start orchestrator-managed evolution (default)
            /evolve orchestrated      - Start orchestrator-managed evolution
            /evolve start [--parallel] - Start simple daemon (legacy)
            /evolve stop              - Stop evolution
            /evolve status            - Show daemon status and recent cycles
            /evolve trigger [agent]   - Manually trigger an evolution cycle
            /evolve budget            - Show XAI evaluation budget status

        Orchestrator-managed evolution uses the Orchestrator model to make
        intelligent decisions about the evolution process, adapting to failures
        and optimizing resource usage automatically.
        """
        parts = args.split(maxsplit=1) if args else []
        subcmd = parts[0].lower() if parts else "orchestrated"  # Default to orchestrated
        subargs = parts[1] if len(parts) > 1 else ""

        if subcmd == "orchestrated" or subcmd == "orch":
            # Start orchestrator-managed evolution
            # This runs in a blocking loop until stopped (Ctrl+C)
            # Usage: /evolve orchestrated [endpoint]
            #   endpoint: Optional endpoint to use for orchestration (default: orchestrator)
            #             Use 'fast' or 'reasoning' if orchestrator endpoint not available.
            #             If no endpoint specified and none running, uses fallback heuristics.
            from .inference.orchestrator import get_orchestrator
            from .agents.evolution.orchestrated import get_orchestrated_evolution

            endpoint_to_use = subargs.strip() if subargs else "orchestrator"

            print("Starting orchestrator-managed evolution...", file=sys.stderr)
            print("Press Ctrl+C to stop", file=sys.stderr)

            # Use InferenceManager to check/discover endpoints (finds external processes)
            from .inference.manager import get_inference_manager
            manager = get_inference_manager()
            status = await manager.get_status()

            if not status.default_model_ready:
                # No endpoint found, try to start one
                print(f"Phase 1: Starting inference endpoint...", file=sys.stderr)
                success = await manager.ensure_orchestrator_running()
                if not success:
                    print("Warning: Could not start inference endpoint, will use fallback heuristics", file=sys.stderr)
                else:
                    print("Inference endpoint ready", file=sys.stderr)
            else:
                # Found existing endpoint
                healthy_endpoints = [name for name, st in status.endpoints_running.items()
                                    if st.value == "healthy"]
                print(f"Phase 1: Found healthy endpoints: {healthy_endpoints}", file=sys.stderr)

            # Start orchestrated evolution with specified endpoint
            print("Phase 2: Starting orchestrator-managed evolution loop...", file=sys.stderr)
            orch_evo = get_orchestrated_evolution()
            orch_evo.orchestrator_endpoint = endpoint_to_use  # Configure endpoint
            await orch_evo.start()

            # Keep the process alive until evolution stops or interrupted
            # This is necessary because evolution runs as an asyncio task
            try:
                while orch_evo.running:
                    await asyncio.sleep(5)
                    # Print periodic status updates
                    orch_status = orch_evo.get_status()
                    cycles = orch_status.get("cycles_completed", 0)
                    improvement = orch_status.get("total_improvement", 0)
                    last = orch_status.get("last_decision")
                    if last:
                        action = last.get("action", "?")
                        target = last.get("target", "?")
                        print(f"  Cycle {cycles}: {action} -> {target} (+{improvement:.1f}%)", file=sys.stderr)
            except asyncio.CancelledError:
                print("\nStopping evolution...", file=sys.stderr)
            finally:
                await orch_evo.stop()

            orch_status = orch_evo.get_status()

            return {
                "action": "orchestrated",
                "success": True,
                "mode": "orchestrator-managed",
                "cycles_completed": orch_status["cycles_completed"],
                "total_improvement": orch_status["total_improvement"],
                "session_start": orch_status["session_start"],
                "message": "Orchestrator-managed evolution completed.",
            }

        elif subcmd == "start":
            # Clean start: cleanup GPU, start reasoning endpoint, start daemon
            from .inference.orchestrator import get_orchestrator
            from .agents.evolution import get_evolution_daemon

            orchestrator = get_orchestrator()

            # Parse optional endpoint list
            endpoints = ["reasoning"]
            if subargs:
                endpoints = [e.strip() for e in subargs.split(",")]

            # Phase 1: Clean start GPU
            print("Phase 1: Cleaning up stale processes...", file=sys.stderr)
            clean_result = await orchestrator.clean_start(endpoints)

            if not clean_result["success"]:
                return {
                    "action": "start",
                    "success": False,
                    "error": "Failed to start GPU endpoints",
                    "cleanup": clean_result["cleanup"],
                    "startup": clean_result["startup"],
                }

            # Phase 2: Start evolution daemon
            print("Phase 2: Starting evolution daemon...", file=sys.stderr)
            daemon = get_evolution_daemon()
            await daemon.start()

            return {
                "action": "start",
                "success": True,
                "gpu_cleanup": clean_result["cleanup"],
                "gpu_startup": clean_result["startup"],
                "daemon_running": daemon.running,
                "message": "Evolution running. Use '/evolve status' to monitor.",
            }

        elif subcmd == "stop":
            from .agents.evolution import get_evolution_daemon

            # Stop simple daemon
            daemon = get_evolution_daemon()
            await daemon.stop()

            # Also stop orchestrated evolution if running
            orch_stopped = False
            try:
                from .agents.evolution.orchestrated import get_orchestrated_evolution
                orch_evo = get_orchestrated_evolution()
                if orch_evo.running:
                    await orch_evo.stop()
                    orch_stopped = True
            except Exception:
                pass  # Orchestrated evolution not available

            return {
                "action": "stop",
                "success": True,
                "daemon_running": daemon.running,
                "orchestrated_stopped": orch_stopped,
            }

        elif subcmd == "status":
            from .agents.evolution import get_evolution_daemon

            daemon = get_evolution_daemon()
            status = daemon.get_status()

            return {
                "running": status["running"],
                "enabled": status["enabled"],
                "cycles_completed": status["cycles_completed"],
                "total_improvement": status.get("total_improvement_percent", 0),
                "next_agent": status.get("next_agent", "unknown"),
                "config": status.get("config", {}),
            }

        elif subcmd == "trigger":
            from .agents.evolution import get_evolution_daemon

            daemon = get_evolution_daemon()

            if not daemon.running:
                return {"error": "Daemon not running. Use '/evolve start' first."}

            # Trigger manual cycle
            agent_id = subargs if subargs else None
            result = await daemon.force_evolution_cycle(agent_id)

            return {
                "action": "trigger",
                "agent_id": result.agent_id if result else None,
                "success": result.success if result else False,
                "improvement": result.improvement_percent if result else 0,
            }

        elif subcmd == "budget":
            from .models.tiered_evaluation import get_tiered_evaluator

            evaluator = get_tiered_evaluator()
            return evaluator.get_budget_status()

        else:
            return {"error": f"Unknown evolve command: {subcmd}"}

    async def _cmd_engine(self, args: str) -> dict:
        """Engine connectivity operations.

        Usage:
            /engine              - Show engine connection status (default)
            /engine status       - Show engine status and health
            /engine reconnect    - Reconnect to engine
            /engine test         - Test engine round-trip

        The engine is required for inference, evolution, and orchestration.
        Uses gRPC for communication with gaius-engine on port 50051.
        """
        parts = args.split(maxsplit=1) if args else ["status"]
        subcmd = parts[0].lower()

        from .client.grpc_client import GrpcEngineClient, GrpcClientConfig

        if subcmd == "status":
            config = GrpcClientConfig.from_env()
            result = {
                "grpc_host": config.host,
                "grpc_port": config.port,
            }

            # Try to connect
            try:
                client = GrpcEngineClient(config)
                connected = await client.connect()

                if connected:
                    result["connected"] = True
                    result["transport"] = "grpc"

                    # Get health status
                    try:
                        health = await client.call("Health", "status", {})
                        result["engine_health"] = health
                    except Exception as e:
                        result["engine_health"] = {"error": str(e)}

                    await client.disconnect()
                else:
                    result["connected"] = False
                    result["error"] = "Engine not running. Start with: devenv up"
            except Exception as e:
                result["connected"] = False
                result["error"] = str(e)

            return result

        elif subcmd == "reconnect":
            # Force reconnection
            try:
                from .client import grpc_client

                # Clear cached client
                if grpc_client._grpc_client:
                    await grpc_client._grpc_client.disconnect()
                    grpc_client._grpc_client = None

                # Also clear instance cache
                if hasattr(self, "_engine_client") and self._engine_client:
                    await self._engine_client.disconnect()
                    self._engine_client = None

                # Reconnect
                client = await grpc_client.get_grpc_client()
                if client.is_connected:
                    return {
                        "reconnected": True,
                        "transport": "grpc",
                    }
                else:
                    return {
                        "reconnected": False,
                        "error": "Failed to reconnect",
                    }
            except Exception as e:
                return {"reconnected": False, "error": str(e)}

        elif subcmd == "test":
            # Test round-trip to engine
            try:
                config = GrpcClientConfig.from_env()
                client = GrpcEngineClient(config)

                if not await client.connect():
                    return {"test": "failed", "error": "Could not connect"}

                import time
                start = time.time()

                # Call health status as a test
                result = await client.call("Health", "status", {})
                elapsed_ms = int((time.time() - start) * 1000)

                await client.disconnect()

                return {
                    "test": "passed",
                    "latency_ms": elapsed_ms,
                    "transport": "grpc",
                    "response": result,
                }
            except Exception as e:
                return {"test": "failed", "error": str(e)}

        else:
            return {"error": f"Unknown engine command: {subcmd}"}

    async def _cmd_exec(self, args: str) -> dict:
        """Execute a command via Engine's CommandService (unified entry point).

        This routes any command through the Engine's gRPC CommandService,
        enabling the thin client architecture where all compute happens
        server-side.

        Usage:
            /exec <command> [args]  - Execute command via Engine
            /exec goto 5,5          - Example: goto position via Engine
            /exec reindex           - Example: reindex via Engine

        Returns:
            success: True if command executed successfully
            command: The command that was executed
            message: Human-readable result message
            data: Command-specific result data (if any)
            generation: State generation after command
            duration_ms: Execution time in milliseconds
        """
        if not args:
            return {"error": "Usage: /exec <command> [args]"}

        parts = args.split(maxsplit=1)
        command = parts[0]
        cmd_args = parts[1] if len(parts) > 1 else ""

        kb_root = self._get_kb_root()

        try:
            from .client.command_client import get_command_client

            client = await get_command_client()
            result = await client.execute(
                command=command,
                args=cmd_args,
                kb_root=kb_root,
                context={
                    "cursor_x": str(self.state.cursor_x),
                    "cursor_y": str(self.state.cursor_y),
                    "view_mode": self.state.view_mode.value if hasattr(self.state.view_mode, "value") else str(self.state.view_mode),
                    "overlay_mode": self.state.overlay_mode.value if hasattr(self.state.overlay_mode, "value") else str(self.state.overlay_mode),
                },
            )

            return {
                "success": result.success,
                "command": result.command,
                "message": result.message,
                "data": result.data,
                "generation": result.generation,
                "duration_ms": result.duration_ms,
            }

        except Exception as e:
            return {
                "success": False,
                "command": command,
                "error": str(e),
            }

    async def _cmd_watch(self, args: str) -> dict:
        """Watch OpenTelemetry telemetry streams with filtering.

        /watch provides observability into agent and inference operations
        by subscribing to and filtering OTel telemetry data.

        Usage:
            /watch                     - Show recent traces (default)
            /watch status              - Show OTel collector status
            /watch traces [filter]     - Watch traces with optional filter
            /watch spans [filter]      - Watch spans with optional filter
            /watch metrics [name]      - Watch specific metric
            /watch logs [filter]       - Watch logs with optional filter
            /watch service <name>      - Filter by service name
            /watch operation <name>    - Filter by operation name
            /watch clear               - Clear watch buffers

        Filters:
            /watch traces service:gaius-engine
            /watch spans operation:ask
            /watch logs level:error

        This command is designed to be used by agents (via /ask) to
        diagnose issues by examining telemetry data.
        """
        parts = args.split(maxsplit=1) if args else ["traces"]
        subcmd = parts[0].lower()
        filter_arg = parts[1] if len(parts) > 1 else ""

        # Check if OTel is available
        otel_available = False
        try:
            from opentelemetry import trace
            otel_available = True
        except ImportError:
            pass

        if subcmd == "status":
            return await self._watch_status(otel_available)
        elif subcmd == "traces":
            return await self._watch_traces(filter_arg, otel_available)
        elif subcmd == "spans":
            return await self._watch_spans(filter_arg, otel_available)
        elif subcmd == "metrics":
            return await self._watch_metrics(filter_arg, otel_available)
        elif subcmd == "logs":
            return await self._watch_logs(filter_arg, otel_available)
        elif subcmd == "service":
            return await self._watch_traces(f"service:{filter_arg}", otel_available)
        elif subcmd == "operation":
            return await self._watch_spans(f"operation:{filter_arg}", otel_available)
        elif subcmd == "clear":
            return self._watch_clear()
        else:
            # Treat as filter on default traces
            return await self._watch_traces(args, otel_available)

    async def _watch_status(self, otel_available: bool) -> dict:
        """Get OTel collector status."""
        status = {
            "otel_available": otel_available,
            "otel_endpoint": os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "not set"),
            "otel_service_name": os.environ.get("OTEL_SERVICE_NAME", "gaius"),
        }

        if not otel_available:
            status["error"] = "OpenTelemetry not installed. Run: uv sync --extra telemetry"
            return status

        # Check if we can reach the collector
        try:
            from opentelemetry import trace
            tracer = trace.get_tracer(__name__)
            status["tracer_provider"] = str(type(trace.get_tracer_provider()).__name__)

            # Check if exporter is configured
            provider = trace.get_tracer_provider()
            if hasattr(provider, '_active_span_processor'):
                status["span_processor"] = "configured"
            else:
                status["span_processor"] = "default (no export)"

        except Exception as e:
            status["error"] = str(e)

        # Check engine telemetry status
        engine_client = await self._get_engine_client_cached()
        if engine_client:
            try:
                health = await engine_client.call("Health", "status", {}, timeout=5.0)
                services = health.get("services", {})
                status["engine_telemetry"] = {
                    "connected": True,
                    "services_reporting": list(services.keys()),
                }
            except Exception as e:
                status["engine_telemetry"] = {"connected": False, "error": str(e)}
        else:
            status["engine_telemetry"] = {"connected": False, "reason": "engine not available"}

        return status

    async def _watch_traces(self, filter_arg: str, otel_available: bool) -> dict:
        """Watch recent traces with optional filtering."""
        if not otel_available:
            return {
                "traces": [],
                "error": "OpenTelemetry not available",
                "suggestion": "Install with: uv sync --extra telemetry",
            }

        # Parse filter
        filters = self._parse_watch_filter(filter_arg)

        # For now, return traces from our in-memory buffer
        # In a full implementation, this would query the OTel collector
        traces = []

        # Check if we have reasoning traces in state
        if hasattr(self.state, 'reasoning_traces'):
            for t in self.state.reasoning_traces[-20:]:
                trace_entry = {
                    "timestamp": t.timestamp.isoformat() if hasattr(t, 'timestamp') else None,
                    "operation": t.operation if hasattr(t, 'operation') else "unknown",
                    "query": t.query[:50] if hasattr(t, 'query') else "",
                    "tokens": t.tokens if hasattr(t, 'tokens') else 0,
                    "sources": t.sources if hasattr(t, 'sources') else 0,
                    "duration_ms": t.duration_ms if hasattr(t, 'duration_ms') else 0,
                }

                # Apply filters
                if self._matches_filter(trace_entry, filters):
                    traces.append(trace_entry)

        # Also try to get traces from engine
        engine_client = await self._get_engine_client_cached()
        if engine_client:
            try:
                # Query engine for recent operations
                # This is a placeholder - real impl would use OTel collector API
                pass
            except Exception:
                pass

        return {
            "traces": traces,
            "count": len(traces),
            "filter": filters if filters else "none",
        }

    async def _watch_spans(self, filter_arg: str, otel_available: bool) -> dict:
        """Watch recent spans with optional filtering."""
        if not otel_available:
            return {"spans": [], "error": "OpenTelemetry not available"}

        filters = self._parse_watch_filter(filter_arg)

        # Placeholder - real impl would query OTel collector
        return {
            "spans": [],
            "count": 0,
            "filter": filters if filters else "none",
            "note": "Span streaming requires OTel collector API access",
        }

    async def _watch_metrics(self, metric_name: str, otel_available: bool) -> dict:
        """Watch specific metrics."""
        if not otel_available:
            return {"metrics": {}, "error": "OpenTelemetry not available"}

        # Get common metrics
        metrics = {}

        # Try to get GPU metrics
        try:
            from .inference.orchestrator import get_orchestrator
            orch = get_orchestrator()
            status = orch.get_status()
            metrics["gpu_utilization"] = status.get("gpu_utilization", [])
            metrics["endpoints_healthy"] = status.get("healthy_endpoints", 0)
        except Exception:
            pass

        # Try to get evolution metrics
        try:
            from .agents.evolution import get_evolution_daemon
            daemon = get_evolution_daemon()
            evo_status = daemon.get_status()
            metrics["evolution_cycles"] = evo_status.get("cycles_completed", 0)
            metrics["total_improvement"] = evo_status.get("total_improvement_percent", 0)
        except Exception:
            pass

        # Filter by name if specified
        if metric_name:
            metrics = {k: v for k, v in metrics.items() if metric_name.lower() in k.lower()}

        return {"metrics": metrics, "count": len(metrics)}

    async def _watch_logs(self, filter_arg: str, otel_available: bool) -> dict:
        """Watch logs with optional filtering."""
        filters = self._parse_watch_filter(filter_arg)

        # Read recent logs from Python logging
        import logging
        logs = []

        # Get root logger's handlers
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if hasattr(handler, 'buffer'):
                # Memory handler
                for record in handler.buffer[-50:]:
                    log_entry = {
                        "timestamp": record.created,
                        "level": record.levelname,
                        "logger": record.name,
                        "message": record.getMessage()[:200],
                    }
                    if self._matches_filter(log_entry, filters):
                        logs.append(log_entry)

        return {
            "logs": logs,
            "count": len(logs),
            "filter": filters if filters else "none",
            "note": "Full log streaming requires log aggregator",
        }

    def _watch_clear(self) -> dict:
        """Clear watch buffers."""
        # Clear reasoning traces if present
        if hasattr(self.state, 'reasoning_traces'):
            self.state.reasoning_traces.clear()

        return {"cleared": True, "message": "Watch buffers cleared"}

    def _parse_watch_filter(self, filter_arg: str) -> dict:
        """Parse filter string into dict."""
        if not filter_arg:
            return {}

        filters = {}
        for part in filter_arg.split():
            if ":" in part:
                key, value = part.split(":", 1)
                filters[key.lower()] = value
            else:
                # Treat as text search
                filters["text"] = part

        return filters

    def _matches_filter(self, entry: dict, filters: dict) -> bool:
        """Check if entry matches filters."""
        if not filters:
            return True

        for key, value in filters.items():
            if key == "text":
                # Search all string values
                found = False
                for v in entry.values():
                    if isinstance(v, str) and value.lower() in v.lower():
                        found = True
                        break
                if not found:
                    return False
            elif key == "service":
                if entry.get("service", "").lower() != value.lower():
                    return False
            elif key == "operation":
                if entry.get("operation", "").lower() != value.lower():
                    return False
            elif key == "level":
                if entry.get("level", "").lower() != value.lower():
                    return False
            else:
                # Generic field match
                if str(entry.get(key, "")).lower() != value.lower():
                    return False

        return True

    async def _cmd_explain(self, args: str) -> dict:
        """Explain a grid position via Engine gRPC.

        All computation (TDA, geometry, minigrid, LLM) happens on the Engine.
        No local fallbacks - Engine must be functional.

        Usage: /explain [pos] [--save]
        Examples:
            /explain K10        - Explain position K10
            /explain K10 --save - Explain and save to KB
            /explain --save     - Explain default position and save
        """
        from .client.grpc_client import get_grpc_client

        # Parse --save flag
        save_to_kb = "--save" in args
        args = args.replace("--save", "").strip()

        # Parse position (default K10 = center)
        if args:
            cx, cy = self._parse_coord(args)
        else:
            cx, cy = 9, 9  # K10 (center)

        kb_root = self.config.kb.root

        # Call Engine via gRPC
        client = await get_grpc_client()
        response = await client.explain(
            kb_root=kb_root,
            x=cx,
            y=cy,
            save_to_kb=save_to_kb,
            max_tokens=800,
        )

        if not response.success:
            raise RuntimeError(f"Engine /explain failed: {response.error}")

        # Build result from Engine response
        result = {
            "position": response.position,
            "x": response.x,
            "y": response.y,
            "document": response.document_title or None,
            "document_path": response.document_path or None,
            "curvature": response.curvature if response.curvature else None,
            "gradient": (response.gradient_x, response.gradient_y) if response.gradient_x else None,
            "tda": {
                "entropy": response.tda_entropy,
                "h0_count": response.h0_count,
                "h1_count": response.h1_count,
                "h2_count": response.h2_count,
            },
            "risk_score": response.risk_score if response.risk_score else None,
            "grid_coverage": response.grid_coverage,
            "total_documents": response.total_documents,
            "nearby_documents": list(response.nearby_documents),
            "explanation": response.explanation,
            "model": response.model,
            "elapsed_ms": response.duration_ms,
        }

        if save_to_kb and response.saved_path:
            result["saved_to"] = response.saved_path

        return result

    def _cmd_kb(self, args: str) -> dict:
        """KB operations using storage abstraction.

        Subcommands:
            list [directory] - List KB entries (optionally filter by directory)
            read <path>      - Read a KB entry
            search <query>   - Search KB by filename or content
            sync [target]    - Sync KB to S3 (default: minio-local)
            sync status      - Show sync status
            sync targets     - List configured targets
            sync verify      - Verify remote integrity
        """
        import asyncio
        parts = args.split(maxsplit=1)
        subcmd = parts[0] if parts else "list"
        subargs = parts[1] if len(parts) > 1 else ""

        if subcmd == "sync":
            return self._run_async(self._cmd_kb_sync(subargs))

        elif subcmd == "list":
            from .storage.kb_ops import list_kb
            # subargs is optional directory filter (e.g., "scratch" or "current")
            result = asyncio.get_event_loop().run_until_complete(list_kb(subargs.strip()))
            if "error" in result:
                return result
            return {"entries": result.get("entries", []), "total": len(result.get("entries", []))}

        elif subcmd == "read":
            if not subargs:
                raise ValueError("kb read requires a path")
            from .storage.kb_ops import read_kb
            entry = asyncio.get_event_loop().run_until_complete(read_kb(subargs.strip()))
            if entry is None:
                return {"error": f"Not found: {subargs}"}
            return {"path": entry.path, "content": entry.content}

        elif subcmd == "search":
            if not subargs:
                raise ValueError("kb search requires a query")
            from .storage.kb_ops import search_kb
            results = asyncio.get_event_loop().run_until_complete(search_kb(subargs.strip()))
            return {
                "query": subargs,
                "results": [{"path": r.path, "match": r.match_type, "preview": r.preview} for r in results],
            }

        else:
            return {"error": f"Unknown kb subcommand: {subcmd}. Use: list, read, search, sync"}

    async def _cmd_kb_sync(self, args: str) -> dict:
        """Sync KB to S3 storage.

        Usage:
            /kb sync [target]           - Sync to target (default: minio-local)
            /kb sync status [target]    - Show sync status
            /kb sync targets            - List configured targets
            /kb sync verify [target]    - Verify remote integrity
            /kb sync --dry-run          - Show what would sync
            /kb sync --resume           - Resume interrupted sync
        """
        from .storage.sync_engine import (
            SyncEngine,
            get_sync_target,
            get_sync_status,
            list_sync_targets,
            verify_sync,
        )
        from .storage.grid_state import get_database_url

        parts = args.split()
        db_url = get_database_url()

        # Parse subcommand
        if "status" in parts:
            idx = parts.index("status")
            target_name = parts[idx + 1] if len(parts) > idx + 1 else "minio-local"
            return await get_sync_status(target_name, db_url)

        elif "targets" in parts:
            targets = await list_sync_targets(db_url)
            return {"targets": targets}

        elif "verify" in parts:
            idx = parts.index("verify")
            target_name = parts[idx + 1] if len(parts) > idx + 1 else "minio-local"
            return await verify_sync(
                target_name,
                self.config.kb.root,
                db_url,
                sample_size=20,
            )

        else:
            # Actual sync
            target_name = "minio-local"
            dry_run = "--dry-run" in parts or "-n" in parts
            resume = "--resume" in parts

            # Find target name if specified (non-flag argument)
            for p in parts:
                if not p.startswith("-"):
                    target_name = p
                    break

            target = await get_sync_target(target_name, db_url)
            if not target:
                return {"error": f"Unknown sync target: {target_name}"}

            engine = SyncEngine(
                source_root=self.config.kb.root,
                target=target,
                db_url=db_url,
            )

            # Progress callback
            def progress(current: int, total: int, path: str, action: str) -> None:
                if self.format == "text":
                    # Truncate path for display
                    display_path = path[:50] + "..." if len(path) > 50 else path
                    print(
                        f"\r[{current}/{total}] {action}: {display_path:<55}",
                        end="",
                        file=self.error,
                        flush=True,
                    )

            result = await engine.sync(
                progress_callback=progress if self.format == "text" else None,
                resume=resume,
                dry_run=dry_run,
            )

            if self.format == "text":
                print("", file=self.error)  # Newline after progress

            return {
                "target": target_name,
                "dry_run": dry_run,
                "files_scanned": result.files_scanned,
                "files_uploaded": result.files_uploaded,
                "files_skipped": result.files_skipped,
                "files_failed": result.files_failed,
                "bytes_uploaded": result.bytes_uploaded,
                "orphans_found": result.orphans_found,
                "duration_ms": result.duration_ms,
                "errors": result.errors[:10] if result.errors else [],
            }

    def _parse_coord(self, coord: str) -> tuple[int, int]:
        """Parse coordinate string like 'K10' to (x, y)."""
        coord = coord.strip().upper()
        if len(coord) < 2:
            raise ValueError(f"Invalid coordinate: {coord}")

        col = coord[0]
        row_str = coord[1:]

        # Handle 'I' skip
        if col >= 'J':
            x = ord(col) - ord('A') - 1
        else:
            x = ord(col) - ord('A')

        if not (0 <= x < 19):
            raise ValueError(f"Invalid column: {col}")

        try:
            row = int(row_str)
        except ValueError:
            raise ValueError(f"Invalid row: {row_str}")

        y = 19 - row
        if not (0 <= y < 19):
            raise ValueError(f"Invalid row: {row}")

        return x, y

    def _coord_string(self, x: int, y: int) -> str:
        """Convert x, y to coordinate string."""
        col = chr(65 + x + (1 if x >= 8 else 0))
        row = 19 - y
        return f"{col}{row}"

    def _render_grid_ascii(self) -> str:
        """Render simple ASCII grid with optional dynamics overlay."""
        from .core.state import OverlayMode

        # Build gradient lookup if in dynamics mode
        gradient_lookup = {}
        if self.state.overlay_mode == OverlayMode.DYNAMICS and self.state.gradient_field:
            for gv in self.state.gradient_field:
                if isinstance(gv, (list, tuple)) and len(gv) >= 4:
                    x, y = int(gv[0]), int(gv[1])
                    gx, gy = float(gv[2]), float(gv[3])
                    gradient_lookup[(x, y)] = (gx, gy)

        def get_arrow(gx: float, gy: float) -> str:
            """Convert gradient vector to Unicode arrow."""
            import math
            mag = math.sqrt(gx*gx + gy*gy)
            if mag < 0.001:
                return "·"
            angle = math.atan2(gy, gx)
            # 8 directions
            idx = int((angle + math.pi) / (2 * math.pi) * 8 + 0.5) % 8
            arrows = ["←", "↙", "↓", "↘", "→", "↗", "↑", "↖"]
            return arrows[idx]

        lines = []
        for y in range(19):
            row = []
            for x in range(19):
                if (x, y) == (self.state.cursor_x, self.state.cursor_y):
                    row.append("X")
                elif (x, y) in self.state.black_stones:
                    row.append("#")
                elif (x, y) in self.state.white_stones:
                    row.append("O")
                elif (x, y) in gradient_lookup:
                    gx, gy = gradient_lookup[(x, y)]
                    row.append(get_arrow(gx, gy))
                else:
                    row.append(".")
            lines.append(f"{19-y:2} " + " ".join(row))
        lines.append("   " + " ".join(chr(65+i) if i < 8 else chr(66+i) for i in range(19)))
        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────────
    # Profile Management
    # ─────────────────────────────────────────────────────────────────────

    def _cmd_profile(self, args: str) -> dict:
        """Set or get active profile.

        Usage:
            /profile              - Show current profile
            /profile cloudera     - Switch to cloudera profile
            /profile weathership  - Switch to weathership profile
        """
        if args:
            profile_name = args.strip().lower()
            try:
                from .core.config import load_config
                self.config = load_config(profile=profile_name)

                # Execute startup commands for the new profile
                startup_results = []
                for cmd in self.config.startup.commands:
                    result = self.execute(cmd)
                    startup_results.append({
                        "command": cmd,
                        "success": result.get("success", False),
                    })

                return {
                    "profile": self.config.profile,
                    "switched": True,
                    "startup_commands": startup_results,
                }
            except Exception as e:
                raise ValueError(f"Failed to load profile '{profile_name}': {e}")
        else:
            return {
                "profile": self.config.profile,
                "startup_commands": list(self.config.startup.commands),
            }

    # ─────────────────────────────────────────────────────────────────────
    # Project Notes with Bidirectional Linking
    # ─────────────────────────────────────────────────────────────────────

    def _cmd_project(self, args: str) -> dict:
        """Create project note with bidirectional linking.

        Creates a Zettelkasten-style project note in scratch with:
        - Link to project agenda
        - prev: link to most recent note of same type
        - next: initially empty (filled when next note created)

        Usage:
            /project charter   - Create charter note
            /project standup   - Create standup note
            /project review    - Create review note

        The prev/next links are automatically maintained across sessions.
        """
        if not args:
            # List existing project types
            from pathlib import Path
            from .core.project_notes import list_project_types

            kb_root = Path(self.config.kb.root)
            types = list_project_types(kb_root)

            raise ValueError(
                f"project requires type (e.g., /project charter)\n"
                f"Existing types: {', '.join(types) if types else 'none'}"
            )

        project_type = args.strip().lower().replace(" ", "_")

        from pathlib import Path
        from .core.project_notes import create_project_note, get_project_chain

        kb_root = Path(self.config.kb.root)
        note_path, content = create_project_note(kb_root, project_type)

        # Get chain info for response
        chain = get_project_chain(kb_root, project_type)

        return {
            "created": str(note_path),
            "project_type": project_type,
            "chain_length": len(chain),
            "content_preview": content[:300],
        }

    # ─────────────────────────────────────────────────────────────────────
    # Thoughts - Cognition and Pattern Detection
    # ─────────────────────────────────────────────────────────────────────

    async def _cmd_thoughts(self, args: str) -> dict:
        """Trigger cognition and view thoughts.

        Analyzes recent KB entries and activity to:
        - Detect patterns across research areas
        - Find cross-domain connections
        - Generate curiosity-driven questions
        - Self-observe (recursive thinking about thoughts)
        - Audit engine health

        Usage:
            /thoughts           - Trigger cognition cycle, create thoughts note
            /thoughts deep      - Run deeper analysis
            /thoughts recent    - Show recent thoughts without triggering new cycle
            /thoughts recent 5  - Show last 5 thoughts
            /thoughts self      - Trigger self-observation (thoughts about thoughts)
            /thoughts audit     - Trigger engine audit
            /thoughts chain [id]- Show thought chain
        """
        try:
            from .agents.cognition import (
                trigger_cognition,
                get_cognition_agent,
                CognitionContext,
            )
        except ImportError:
            return {
                "error": "Cognition module not available",
                "suggestion": "Ensure agents module is installed",
                "thoughts": [],
            }

        args_lower = args.strip().lower() if args else ""

        # /thoughts self - trigger self-observation
        if args_lower == "self":
            try:
                agent = get_cognition_agent(profile=self.config.profile)
                context = CognitionContext()
                context.active_thoughts = await agent.get_active_thoughts(limit=20)
                context.recent_kb_entries = await agent._get_recent_kb_entries()

                thoughts = await agent._observe_own_thoughts(context)
                for thought in thoughts:
                    await agent._save_thought(thought)

                return {
                    "mode": "self_observation",
                    "self_observations": len(thoughts),
                    "thoughts": [
                        {
                            "title": t.title,
                            "type": t.thought_type.value,
                            "generation": t.generation,
                            "note_path": t.note_path,
                            "content": t.content[:200] + "..." if len(t.content) > 200 else t.content,
                        }
                        for t in thoughts
                    ],
                }
            except Exception as e:
                return {"error": str(e), "mode": "self_observation", "thoughts": []}

        # /thoughts audit - trigger engine audit
        if args_lower == "audit":
            try:
                agent = get_cognition_agent(profile=self.config.profile)
                context = CognitionContext()

                thoughts = await agent._audit_engine_health(context)
                for thought in thoughts:
                    await agent._save_thought(thought)

                return {
                    "mode": "engine_audit",
                    "audit_thoughts": len(thoughts),
                    "thoughts": [
                        {
                            "title": t.title,
                            "type": t.thought_type.value,
                            "note_path": t.note_path,
                            "content": t.content[:200] + "..." if len(t.content) > 200 else t.content,
                        }
                        for t in thoughts
                    ],
                }
            except Exception as e:
                return {"error": str(e), "mode": "engine_audit", "thoughts": []}

        # /thoughts chain [id] - show thought chain
        if args_lower.startswith("chain"):
            parts = args_lower.split()
            thought_id = parts[1] if len(parts) > 1 else None

            try:
                import asyncpg

                conn = await asyncpg.connect(self.config.database.url)
                try:
                    if not thought_id:
                        thought_id = await conn.fetchval(
                            """
                            SELECT id FROM cognition_thoughts
                            WHERE thought_chain_id IS NOT NULL
                            ORDER BY created_at DESC LIMIT 1
                            """
                        )
                        if not thought_id:
                            return {"error": "No thought chains found", "mode": "chain"}

                    rows = await conn.fetch(
                        """
                        WITH RECURSIVE chain AS (
                            SELECT id, title, thought_type, generation, predecessor_id,
                                   content, salience, created_at, note_path
                            FROM cognition_thoughts WHERE id = $1::uuid
                            UNION ALL
                            SELECT t.id, t.title, t.thought_type, t.generation, t.predecessor_id,
                                   t.content, t.salience, t.created_at, t.note_path
                            FROM cognition_thoughts t
                            JOIN chain c ON t.id = c.predecessor_id
                        )
                        SELECT * FROM chain ORDER BY generation, created_at
                        """,
                        str(thought_id),
                    )

                    return {
                        "mode": "chain",
                        "chain_length": len(rows),
                        "chain": [
                            {
                                "id": str(r["id"]),
                                "title": r["title"],
                                "type": r["thought_type"],
                                "generation": r["generation"],
                                "note_path": r["note_path"],
                                "content_preview": r["content"][:150] + "..." if r["content"] and len(r["content"]) > 150 else r["content"],
                            }
                            for r in rows
                        ],
                    }
                finally:
                    await conn.close()
            except Exception as e:
                return {"error": str(e), "mode": "chain"}

        # /thoughts recent [n] - just show existing thoughts
        if args_lower.startswith("recent"):
            parts = args_lower.split()
            try:
                limit = int(parts[1]) if len(parts) > 1 else 10
            except ValueError:
                limit = 10

            try:
                agent = get_cognition_agent(profile=self.config.profile)
                thoughts = await agent.get_active_thoughts(limit=limit)
                return {
                    "mode": "recent",
                    "thoughts": [
                        {
                            "title": t.title,
                            "content": t.content[:150] + "..." if len(t.content) > 150 else t.content,
                            "type": t.thought_type.value,
                            "generation": t.generation,
                            "note_path": t.note_path,
                            "confidence": t.confidence,
                            "created_at": t.created_at.isoformat() if t.created_at else None,
                        }
                        for t in thoughts
                    ],
                    "count": len(thoughts),
                }
            except Exception as e:
                return {"error": str(e), "mode": "recent", "thoughts": []}

        # Default: trigger full cognition cycle
        depth = "deep" if args_lower == "deep" else "moderate"

        try:
            result = await trigger_cognition(
                reason="cli_thoughts",
                max_thoughts=5 if depth != "deep" else 10,
                profile=self.config.profile,
            )

            return {
                "mode": "cognition",
                "thoughts_generated": len(result.thoughts) if hasattr(result, 'thoughts') else 0,
                "patterns_detected": result.patterns_detected,
                "connections_found": result.connections_found,
                "self_observations": result.self_observations,
                "engine_audits": result.engine_audits,
                "thoughts": [
                    {
                        "title": t.title,
                        "content": t.content[:150] + "..." if len(t.content) > 150 else t.content,
                        "type": t.thought_type.value,
                        "generation": t.generation,
                        "note_path": t.note_path,
                    }
                    for t in (result.thoughts if hasattr(result, 'thoughts') else [])
                ][:5],  # Preview first 5
            }
        except Exception as e:
            return {
                "error": str(e),
                "mode": "cognition",
                "thoughts_generated": 0,
            }

    # ─────────────────────────────────────────────────────────────────────
    # Health - Comprehensive System Diagnostics
    # ─────────────────────────────────────────────────────────────────────

    async def _cmd_health(self, args: str) -> dict:
        """Run comprehensive health diagnostics.

        Applies heuristics from the KB to diagnose system state
        and suggest interventions.

        Usage:
            /health           - Run full health check
            /health quick     - Run critical checks only
            /health engine    - Check engine/gRPC health
            /health data      - Check database/KB health
            /health cognition - Check cognition daemon
            /health inference - Check inference endpoints
            /health diagnose <service> - Deep diagnostics for a service
            /health fix [service]      - Fix unhealthy services
            /health fix --dry-run      - Show fix plan without executing
            /health watch <cmd>        - Execute command and watch for fallbacks/stubs
            /health history [endpoint] - Show healing event history
            /health sequence <id>      - Show detailed healing sequence
            /health stats [hours]      - Show healing statistics (default: 24h)
        """
        from pathlib import Path

        try:
            from .health import HealthChecker, CheckStatus
        except ImportError:
            return {
                "error": "Health module not available",
                "suggestion": "Ensure health module is installed",
            }

        args_parts = args.strip().split() if args else []
        subcmd = args_parts[0].lower() if args_parts else ""
        subargs = args_parts[1:] if len(args_parts) > 1 else []

        kb_root = Path(self.config.kb.root) if hasattr(self.config.kb, "root") else Path("build/dev")
        checker = HealthChecker(kb_root)

        # Attach self-healing coordinator for automatic remediation
        try:
            coordinator = await self._get_healing_coordinator()
            if coordinator:
                checker.set_healing_coordinator(coordinator)
        except Exception:
            pass  # Continue without auto-healing if coordinator unavailable

        # Handle diagnose subcommand
        if subcmd == "diagnose":
            service = subargs[0] if subargs else None
            return await self._health_diagnose(checker, service)

        # Handle fix subcommand
        if subcmd == "fix":
            return await self._health_fix(checker, subargs)

        # Handle watch subcommand
        if subcmd == "watch":
            watch_cmd = " ".join(subargs) if subargs else None
            return await self._health_watch(watch_cmd)

        # Handle history subcommand - show healing event history
        if subcmd == "history":
            endpoint = subargs[0] if subargs else None
            return await self._health_history(endpoint)

        # Handle sequence subcommand - show detailed healing sequence
        if subcmd == "sequence":
            sequence_id = subargs[0] if subargs else None
            return await self._health_sequence(sequence_id)

        # Handle stats subcommand - show healing statistics
        if subcmd == "stats":
            hours = int(subargs[0]) if subargs else 24
            return await self._health_stats(hours)

        # Run appropriate checks
        if subcmd == "quick":
            report = await checker.run_quick()
            check_type = "quick"
        elif subcmd in ("engine", "data", "cognition", "inference"):
            report = await checker.run_category(subcmd)
            check_type = subcmd
        else:
            report = await checker.run_all()
            check_type = "full"

        # Format results as structured data
        checks = []
        for check in report.checks:
            check_dict = {
                "name": check.name,
                "status": check.status.value,
                "message": check.message,
                "duration_ms": check.duration_ms,
            }
            if check.details:
                check_dict["details"] = check.details
            if check.suggestion:
                check_dict["suggestion"] = check.suggestion
            if check.heuristic_id:
                check_dict["heuristic"] = check.heuristic_id
            checks.append(check_dict)

        # Get self-healing status if relevant
        healing_info = None
        if coordinator and report.failures > 0:
            healing_status = coordinator.get_status()
            if healing_status.get("endpoint_states"):
                healing_info = {
                    "active": True,
                    "endpoint_states": healing_status["endpoint_states"],
                    "global_failures": healing_status.get("global_failures", 0),
                }

        # Generate markdown report and save to scratch
        from datetime import datetime
        import os

        now = datetime.now()
        status_icon = "✅" if report.healthy else "❌"

        md_report = f"""# Health Report {status_icon}

**Type:** {check_type}
**Generated:** {now.strftime("%Y-%m-%d %H:%M:%S")}
**Duration:** {report.duration_ms}ms

## Summary

{report.summary()}

| Metric | Count |
|--------|-------|
| Passed | {report.passed} |
| Warnings | {report.warnings} |
| Failures | {report.failures} |
| Skipped | {report.skipped} |

## Check Results

| Check | Status | Duration | Message |
|-------|--------|----------|---------|
"""
        for check in report.checks:
            status_emoji = {"pass": "✓", "warn": "⚠", "fail": "✗", "skip": "○"}.get(
                check.status.value, "?"
            )
            msg = check.message[:60] + "..." if len(check.message) > 60 else check.message
            md_report += f"| {check.name} | {status_emoji} {check.status.value} | {check.duration_ms}ms | {msg} |\n"

        # Add details for non-passing checks
        issues = [c for c in report.checks if c.status.value in ("warn", "fail")]
        if issues:
            md_report += "\n## Issues Detail\n\n"
            for check in issues:
                md_report += f"### {check.name}\n\n"
                md_report += f"**Status:** {check.status.value}\n"
                md_report += f"**Message:** {check.message}\n\n"
                if check.details:
                    md_report += "**Details:**\n```json\n"
                    import json
                    md_report += json.dumps(check.details, indent=2, default=str)
                    md_report += "\n```\n\n"
                if check.suggestion:
                    md_report += f"**Suggestion:** {check.suggestion}\n\n"
                if check.heuristic_id:
                    md_report += f"**Heuristic:** `{check.heuristic_id}`\n\n"

        # Add interventions if any
        if report.interventions:
            md_report += "\n## Recommended Interventions\n\n"
            for intervention in report.interventions:
                md_report += f"- {intervention}\n"

        # Add self-healing status
        if healing_info:
            md_report += "\n## Self-Healing Status\n\n"
            md_report += f"**Active:** Yes\n"
            md_report += f"**Global Failures:** {healing_info.get('global_failures', 0)}\n\n"
            if healing_info.get("endpoint_states"):
                md_report += "**Endpoint States:**\n"
                for ep, state in healing_info["endpoint_states"].items():
                    md_report += f"- {ep}: tier {state.get('tier', '?')}, attempts {state.get('attempts', '?')}\n"

        # Add action links
        md_report += "\n## Actions\n\n"
        for check in report.checks:
            if check.status.value == "fail":
                # Add relevant fix actions
                if "endpoint" in check.name.lower():
                    md_report += f"- [[action:/health fix]] - Fix unhealthy services\n"
                    break
        md_report += "- [[action:/health history]] - View healing history\n"
        md_report += "- [[action:/health stats]] - View healing statistics\n"

        md_report += f"""
---
*Generated by `/health {check_type}` command*
"""

        # Save to KB scratch using zettelkasten format
        today = now.strftime("%Y-%m-%d")
        timestamp = now.strftime("%H%M%S")

        kb_base = Path(os.environ.get("GAIUS_KB_PATH", "build/dev/scratch"))
        save_dir = kb_base / today
        save_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{timestamp}_health_{check_type}.md"
        filepath = save_dir / filename
        filepath.write_text(md_report)

        # Return both the path (for TUI to open) and structured data
        return {
            "report_path": str(filepath),
            "type": check_type,
            "healthy": report.healthy,
            "summary": report.summary(),
            "timestamp": report.timestamp.isoformat(),
            "duration_ms": report.duration_ms,
            "passed": report.passed,
            "warnings": report.warnings,
            "failures": report.failures,
            "skipped": report.skipped,
            "checks": checks,
            "interventions": report.interventions,
            "metrics": report.metrics if report.metrics else None,
            "self_healing": healing_info,
            "message": f"Report saved to {filepath}",
        }

    async def _health_diagnose(self, checker, service: str | None) -> dict:
        """Deep diagnostic for a specific service.

        Args:
            checker: HealthChecker instance
            service: Service name to diagnose (None lists available services)
        """
        from .health.service_fixes import list_services, get_strategy

        if not service:
            return {
                "error": "Missing service argument",
                "available_services": list_services(),
                "usage": "/health diagnose <service>",
            }

        # Map service name to health check category
        service_to_category = {
            "engine": "engine",
            "grpc": "engine",
            "postgres": "data",
            "postgresql": "data",
            "database": "data",
            "qdrant": "data",
            "minio": "data",
            "s3": "data",
            "endpoints": "inference",
            "inference": "inference",
        }

        category = service_to_category.get(service.lower(), "engine")

        # Run health check for this category
        report = await checker.run_category(category)

        # Find the relevant check result
        relevant_checks = []
        for check in report.checks:
            check_name_lower = check.name.lower()
            if service.lower() in check_name_lower or service.lower() in (check.heuristic_id or "").lower():
                relevant_checks.append(check)

        # If no specific check found, include all from category
        if not relevant_checks:
            relevant_checks = report.checks

        # Load heuristic details if available
        heuristic_info = None
        for check in relevant_checks:
            if check.heuristic_id:
                heuristic = checker.loader.get(check.heuristic_id)
                if heuristic:
                    heuristic_info = {
                        "id": heuristic.id,
                        "name": heuristic.name,
                        "symptom": heuristic.symptom,
                        "cause": heuristic.cause,
                        "observation_level": heuristic.observation_level,
                        "solution_level": heuristic.solution_level,
                    }
                    break

        # Get fix strategy info
        strategy = get_strategy(service)
        fix_available = strategy is not None

        # Build diagnostic result
        observations = []
        for check in relevant_checks:
            obs = {
                "check": check.name,
                "status": check.status.value,
                "message": check.message,
            }
            if check.details:
                obs["details"] = check.details
            observations.append(obs)

        return {
            "service": service,
            "category": category,
            "healthy": all(c.status.value == "pass" for c in relevant_checks),
            "observations": observations,
            "heuristic": heuristic_info,
            "fix_available": fix_available,
            "fix_command": f"/health fix {service}" if fix_available else None,
        }

    async def _health_fix(self, checker, args: list[str]) -> dict:
        """Fix unhealthy services.

        Args:
            checker: HealthChecker instance
            args: Arguments like ['engine'] or ['--dry-run', 'engine']
        """
        from .health.remediation import RemediationExecutor, RemediationPlan
        from .health.service_fixes import get_strategy, list_services

        # Parse flags
        dry_run = "--dry-run" in args
        force = "--force" in args
        args = [a for a in args if not a.startswith("--")]
        service = args[0] if args else None

        # List available services if requested
        if service == "list" or service == "--list":
            return {
                "available_services": list_services(),
                "usage": "/health fix <service> [--dry-run] [--force]",
            }

        # Get strategy for service (or all services if none specified)
        if service:
            strategy = get_strategy(service)
            if not strategy:
                return {
                    "error": f"Unknown service: {service}",
                    "available_services": list_services(),
                    "usage": "/health fix <service>",
                }
            strategies = [(service, strategy)]
        else:
            # Fix all unhealthy services
            report = await checker.run_quick()
            strategies = []

            # Map failed checks to services
            check_to_service = {
                "grpc connection": "engine",
                "optillm": None,  # Can't fix optillm, it's managed externally
                "vllm": None,  # Same
                "database": "postgres",
                "qdrant": "qdrant",
                "s3/minio": "minio",
            }

            for check in report.checks:
                if check.status.value in ("fail", "warn"):
                    for pattern, svc in check_to_service.items():
                        if pattern in check.name.lower() and svc:
                            strat = get_strategy(svc)
                            if strat:
                                strategies.append((svc, strat))
                                break

            if not strategies:
                return {
                    "message": "No fixable issues found",
                    "healthy": report.healthy,
                    "summary": report.summary(),
                }

        # Create remediation plans
        executor = RemediationExecutor()
        results = []

        for svc_name, strategy in strategies:
            # Create plan from strategy
            actions = strategy.create_fix_actions()
            plan = RemediationPlan(service=svc_name, actions=actions)

            # Execute plan
            result = await executor.execute(plan, dry_run=dry_run, force=force)

            results.append({
                "service": svc_name,
                "success": result.success,
                "dry_run": result.dry_run,
                "actions": [
                    {
                        "name": ar.action.name,
                        "success": ar.success,
                        "output": ar.output[:500] if ar.output else None,
                        "error": ar.error[:500] if ar.error else None,
                        "duration_ms": ar.duration_ms,
                    }
                    for ar in result.action_results
                ],
                "summary": result.summary,
            })

        # If not dry run, re-run health check to verify
        if not dry_run:
            verification = await checker.run_quick()
            verification_summary = {
                "healthy": verification.healthy,
                "summary": verification.summary(),
                "passed": verification.passed,
                "failures": verification.failures,
            }
        else:
            verification_summary = None

        return {
            "dry_run": dry_run,
            "services_fixed": len(results),
            "results": results,
            "verification": verification_summary,
        }

    async def _health_watch(self, watch_cmd: str | None) -> dict:
        """Execute a command while watching for fallbacks and stubs.

        Monitors log output and telemetry for patterns indicating:
        - Stub implementations
        - Legacy fallbacks
        - Not implemented features
        - No-op behavior

        Args:
            watch_cmd: Command to execute and watch (e.g., "/evolve status")

        Returns:
            Watch result with observations
        """
        from .health.watcher import CommandWatcher, format_watch_result

        if not watch_cmd:
            return {
                "error": "Missing command to watch",
                "usage": "/health watch <command>",
                "examples": [
                    "/health watch /evolve status",
                    "/health watch /kb search test",
                    "/health watch /thoughts recent",
                ],
                "description": (
                    "Executes the command while monitoring for fallbacks, stubs, "
                    "and incomplete implementations. Helps identify functionality "
                    "that is not yet fully implemented."
                ),
            }

        # Parse the command to watch
        watch_cmd = watch_cmd.strip()
        if watch_cmd.startswith("/"):
            # It's a CLI command - we need to execute it through our command system
            cmd_parts = watch_cmd[1:].split(maxsplit=1)
            cmd_name = cmd_parts[0]
            cmd_args = cmd_parts[1] if len(cmd_parts) > 1 else ""

            # Get the command method
            method_name = f"_cmd_{cmd_name}"
            if not hasattr(self, method_name):
                return {
                    "error": f"Unknown command: /{cmd_name}",
                    "suggestion": "Use /help to see available commands",
                }

            method = getattr(self, method_name)

            async def command_fn():
                return await method(cmd_args)

        else:
            return {
                "error": "Command must start with /",
                "usage": "/health watch /<command>",
            }

        # Execute with watching
        watcher = CommandWatcher()
        result = await watcher.watch_command(command_fn, watch_cmd)

        return format_watch_result(result)

    async def _health_history(self, endpoint: str | None) -> dict:
        """Show healing event history from database.

        Args:
            endpoint: Filter by endpoint (None for all)

        Returns:
            Dict with recent healing events
        """
        try:
            import asyncpg
            import os
            from gaius.core.config import get_database_url
            db_url = get_database_url()
            pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)

            if not pool:
                return {"error": "Database not available"}

            async with pool.acquire() as conn:
                if endpoint:
                    # Get events for specific endpoint
                    rows = await conn.fetch(
                        """
                        SELECT event_type, endpoint, tier, payload, created_at
                        FROM healing_events
                        WHERE endpoint = $1
                        AND created_at > NOW() - INTERVAL '24 hours'
                        ORDER BY created_at DESC
                        LIMIT 50
                        """,
                        endpoint,
                    )
                else:
                    # Get all recent events
                    rows = await conn.fetch(
                        """
                        SELECT event_type, endpoint, tier, payload, created_at
                        FROM healing_events
                        WHERE created_at > NOW() - INTERVAL '24 hours'
                        ORDER BY created_at DESC
                        LIMIT 50
                        """
                    )

                events = [
                    {
                        "event_type": row["event_type"],
                        "endpoint": row["endpoint"],
                        "tier": row["tier"],
                        "payload": row["payload"],
                        "timestamp": row["created_at"].isoformat(),
                    }
                    for row in rows
                ]

                result = {
                    "endpoint": endpoint or "all",
                    "events": events,
                    "count": len(events),
                    "period": "24h",
                }

            await pool.close()
            return result

        except Exception as e:
            return {"error": f"Failed to get history: {e}"}

    async def _health_sequence(self, sequence_id: str | None) -> dict:
        """Show detailed healing sequence by ID.

        Args:
            sequence_id: UUID of the sequence to show

        Returns:
            Dict with all events in the sequence
        """
        if not sequence_id:
            return {
                "error": "Missing sequence_id",
                "usage": "/health sequence <uuid>",
                "hint": "Use /health history to find sequence IDs",
            }

        try:
            from uuid import UUID
            seq_uuid = UUID(sequence_id)
        except ValueError:
            return {"error": f"Invalid UUID: {sequence_id}"}

        try:
            import asyncpg
            import os
            from gaius.core.config import get_database_url
            db_url = get_database_url()
            pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)

            if not pool:
                return {"error": "Database not available"}

            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT sequence_num, event_type, tier, payload, created_at
                    FROM healing_events
                    WHERE sequence_id = $1
                    ORDER BY sequence_num
                    """,
                    seq_uuid,
                )

                if not rows:
                    await pool.close()
                    return {"error": f"No events found for sequence {sequence_id}"}

                events = [
                    {
                        "seq": row["sequence_num"],
                        "event_type": row["event_type"],
                        "tier": row["tier"],
                        "payload": row["payload"],
                        "timestamp": row["created_at"].isoformat(),
                    }
                    for row in rows
                ]

                # Get endpoint from first event
                endpoint = events[0]["payload"].get("endpoint", "unknown") if events else "unknown"

                result = {
                    "sequence_id": sequence_id,
                    "endpoint": endpoint,
                    "events": events,
                    "event_count": len(events),
                }

            await pool.close()
            return result

        except Exception as e:
            return {"error": f"Failed to get sequence: {e}"}

    async def _health_stats(self, hours: int = 24) -> dict:
        """Show healing statistics.

        Args:
            hours: How far back to analyze

        Returns:
            Dict with healing statistics
        """
        try:
            import asyncpg
            import os
            from .health.healing_state_store import HealingStateStore

            from gaius.core.config import get_database_url
            db_url = get_database_url()
            pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)

            if not pool:
                return {"error": "Database not available"}

            store = HealingStateStore(pool=pool)
            stats = await store.get_healing_stats(hours=hours)

            await pool.close()

            return {
                "period_hours": hours,
                **stats,
            }

        except Exception as e:
            return {"error": f"Failed to get stats: {e}"}

    # ─────────────────────────────────────────────────────────────────────
    # Heal - Self-Healing System
    # ─────────────────────────────────────────────────────────────────────

    async def _cmd_heal(self, args: str) -> dict:
        """Tiered self-healing system for endpoint recovery.

        Provides 3-tier approach:
        - Tier 0: Procedural restart (code-only, no agents)
        - Tier 1: Local agent intervention (using healthy endpoints)
        - Tier 2: Remote API escalation (prepared remediation paths)

        Usage:
            /heal status           - Show self-healing status
            /heal trigger <endpoint> - Manually trigger healing for endpoint
            /heal history          - Show healing attempt history
            /heal history <endpoint> - Show history for specific endpoint
            /heal tiers            - Show tier availability
        """
        from pathlib import Path

        args_parts = args.strip().split() if args else []
        subcmd = args_parts[0].lower() if args_parts else "status"
        subargs = args_parts[1:] if len(args_parts) > 1 else []

        # Initialize coordinator (needs orchestrator service)
        try:
            from .client.engine_proxy import use_engine_proxy
            if not use_engine_proxy():
                return {
                    "error": "Engine not reachable",
                    "suggestion": "Start the engine with: gaius-engine",
                }
        except ImportError:
            return {
                "error": "Engine client not available",
                "suggestion": "Self-healing requires the engine",
            }

        # Get or create coordinator
        coordinator = await self._get_healing_coordinator()
        if not coordinator:
            return {
                "error": "Could not initialize self-healing coordinator",
                "suggestion": "Check engine connectivity",
            }

        if subcmd == "status":
            return await self._heal_status(coordinator)

        elif subcmd == "trigger":
            if not subargs:
                return {
                    "error": "Missing endpoint argument",
                    "usage": "/heal trigger <endpoint>",
                }
            endpoint = subargs[0]
            return await self._heal_trigger(coordinator, endpoint)

        elif subcmd == "history":
            endpoint = subargs[0] if subargs else None
            return self._heal_history(coordinator, endpoint)

        elif subcmd == "tiers":
            return self._heal_tiers(coordinator)

        else:
            return {
                "error": f"Unknown subcommand: {subcmd}",
                "usage": "/heal [status|trigger|history|tiers]",
            }

    async def _get_healing_coordinator(self):
        """Get or create the self-healing coordinator.

        Creates coordinator with event recorder and state store for
        persistence across CLI invocations.
        """
        # Check if we have a cached coordinator
        if hasattr(self, "_healing_coordinator") and self._healing_coordinator:
            return self._healing_coordinator

        try:
            from .health import SelfHealingCoordinator
            from .client.engine_proxy import get_orchestrator_proxy

            # Get orchestrator proxy - this wraps the engine's orchestrator service
            orchestrator = await get_orchestrator_proxy()

            # Set up event persistence components
            event_recorder = None
            state_store = None

            try:
                import asyncpg
                from gaius.core.config import get_database_url
                db_url = get_database_url()
                pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)

                if pool:
                    from .health.healing_events import HealingEventRecorder
                    from .health.healing_state_store import HealingStateStore

                    event_recorder = HealingEventRecorder(pool=pool)
                    state_store = HealingStateStore(pool=pool)
            except Exception as e:
                import logging
                logging.getLogger(__name__).debug(
                    f"Event persistence unavailable: {e}"
                )

            # Create coordinator with default config and persistence
            self._healing_coordinator = SelfHealingCoordinator(
                orchestrator_service=orchestrator,
                tier0_config={"max_attempts": 3, "cooldown_seconds": 60},
                tier1_config={"required_healthy_endpoints": 1},
                tier2_config={"enabled": True, "budget_limit_daily": 50},
                event_recorder=event_recorder,
                state_store=state_store,
            )

            return self._healing_coordinator

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to create coordinator: {e}")
            return None

    async def _heal_status(self, coordinator) -> dict:
        """Get self-healing status."""
        status = coordinator.get_status()

        # Also get tier availability info which may need async
        tier_info = []
        for tier in coordinator.tiers:
            info = {
                "type": tier.tier_type.name,
                "available": tier.is_available(),
            }
            tier_info.append(info)

        return {
            "tiers": tier_info,
            "endpoint_states": status["endpoint_states"],
            "global_failures": status["global_failures"],
            "global_cooldown": status["global_cooldown_until"],
            "active_healings": len(status["endpoint_states"]),
        }

    async def _heal_trigger(self, coordinator, endpoint: str) -> dict:
        """Manually trigger healing for an endpoint.

        This command implements full escalation: it keeps trying healing
        actions through all tiers until success or all options exhausted.
        Cooldowns are shortened for interactive use.
        """
        import asyncio
        from .health import HealthIssue

        # For manual triggers, use shorter cooldowns
        original_cooldowns = []
        for tier in coordinator.tiers:
            if hasattr(tier, 'COOLDOWN_SECONDS'):
                original_cooldowns.append(tier.COOLDOWN_SECONDS)
                tier.COOLDOWN_SECONDS = 2  # Short cooldown for manual

        # Create a manual issue
        issue = HealthIssue(
            endpoint=endpoint,
            issue_type="manual_trigger",
            error_message="Manually triggered healing",
            check_name="manual",
            severity="warning",
        )

        # Track all attempts for reporting
        attempts = []
        max_total_attempts = 10  # Safety limit
        attempt_count = 0

        while attempt_count < max_total_attempts:
            attempt_count += 1

            # Clear any cooldowns for manual trigger
            state = coordinator._get_or_create_state(endpoint)
            state.cooldown_until = None

            # Trigger healing
            result = await coordinator.handle_health_issue(issue)

            attempts.append({
                "attempt": attempt_count,
                "tier": result.tier.name if result.tier else None,
                "action": result.action,
                "success": result.success,
                "reason": result.reason,
                "deferred": result.deferred,
            })

            if result.success:
                break

            if result.deferred:
                # Skip deferred results (cooldown active), wait briefly and continue
                await asyncio.sleep(0.5)
                continue

            # Check if we've exhausted all tiers
            current_state = coordinator._states.get(endpoint)
            if current_state and current_state.current_tier >= 2:
                # At tier 2 - check if it returned manual intervention
                if result.action == "manual_intervention_required" or result.action == "FAILOVER_MANUAL":
                    break

            # Brief pause between attempts
            await asyncio.sleep(1)

        # Restore original cooldowns
        idx = 0
        for tier in coordinator.tiers:
            if hasattr(tier, 'COOLDOWN_SECONDS') and idx < len(original_cooldowns):
                tier.COOLDOWN_SECONDS = original_cooldowns[idx]
                idx += 1

        # Determine final result
        final_result = attempts[-1] if attempts else {}

        return {
            "endpoint": endpoint,
            "triggered": True,
            "success": final_result.get("success", False),
            "action": final_result.get("action"),
            "tier": final_result.get("tier"),
            "reason": final_result.get("reason"),
            "deferred": final_result.get("deferred", False),
            "total_attempts": len(attempts),
            "attempts": attempts,
        }

    def _heal_history(self, coordinator, endpoint: str | None = None) -> dict:
        """Get healing attempt history."""
        history = coordinator.get_healing_history(endpoint=endpoint, limit=20)

        return {
            "endpoint": endpoint or "all",
            "count": len(history),
            "history": history,
        }

    def _heal_tiers(self, coordinator) -> dict:
        """Get tier availability information."""
        tiers = []
        for tier in coordinator.tiers:
            tier_info = {
                "type": tier.tier_type.name,
                "tier_num": tier.tier_type.value,
                "available": tier.is_available(),
            }

            # Add tier-specific info
            if hasattr(tier, "MAX_ATTEMPTS"):
                tier_info["max_attempts"] = tier.MAX_ATTEMPTS
            if hasattr(tier, "COOLDOWN_SECONDS"):
                tier_info["cooldown_seconds"] = tier.COOLDOWN_SECONDS
            if hasattr(tier, "ALLOWED_ACTIONS"):
                tier_info["allowed_actions"] = tier.ALLOWED_ACTIONS
            if hasattr(tier, "REMEDIATION_PATHS"):
                tier_info["remediation_codes"] = list(tier.REMEDIATION_PATHS.keys())

            tiers.append(tier_info)

        return {"tiers": tiers}

    def format_output(self, result: dict) -> str:
        """Format result based on output format."""
        if self.format == "json":
            return json.dumps(result, indent=2)
        else:
            # Text format
            if not result["success"]:
                return f"Error: {result.get('error', 'Unknown error')}"

            data = result["data"]
            if not data:
                return "OK"

            lines = []
            for key, value in data.items():
                if isinstance(value, dict):
                    lines.append(f"{key}:")
                    for k, v in value.items():
                        lines.append(f"  {k}: {v}")
                elif isinstance(value, list):
                    lines.append(f"{key}:")
                    for item in value:
                        if isinstance(item, dict):
                            lines.append(f"  - {item}")
                        else:
                            lines.append(f"  - {item}")
                else:
                    lines.append(f"{key}: {value}")
            return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────────────
    # AIOps / MLOps Commands
    # ─────────────────────────────────────────────────────────────────────────

    async def _cmd_aiops(self, args: str) -> dict:
        """AIOps: Infrastructure health management with KB reports.

        Generates reports as scratch KB documents with action links.

        Usage:
            /aiops              - Generate AIOps health report
            /aiops status       - Show pending remediations
            /aiops approve <id> - Approve pending remediation
            /aiops history      - Show recent events
        """
        parts = args.strip().split() if args else []
        subcmd = parts[0].lower() if parts else "report"
        subargs = parts[1:] if len(parts) > 1 else []

        if subcmd == "report" or not args.strip():
            return await self._generate_aiops_report()
        elif subcmd == "status":
            return await self._aiops_pending_approvals()
        elif subcmd == "approve" and subargs:
            return await self._aiops_approve(subargs[0])
        elif subcmd == "history":
            return await self._aiops_history()
        else:
            return {"error": "Usage: /aiops [report|status|approve <id>|history]"}

    async def _generate_aiops_report(self) -> dict:
        """Generate AIOps health report as KB scratch document."""
        from datetime import datetime
        from pathlib import Path
        import os

        # Collect health data
        gpu_health = await self._get_gpu_health_data()
        endpoint_status = await self._get_endpoint_status_data()
        pending_approvals = await self._get_pending_approvals("aiops")
        recent_events = await self._get_recent_aiops_events(limit=10)

        # Build report markdown
        now = datetime.now()
        report = f"""# AIOps Health Report

Generated: {now.isoformat()}

## GPU Health

| GPU | Temp | VRAM Used | Utilization | Status |
|-----|------|-----------|-------------|--------|
"""
        for gpu in gpu_health:
            status_icon = "✓" if gpu.get("healthy", True) else "⚠"
            report += f"| {gpu.get('index', '?')} | {gpu.get('temp', '?')}°C | {gpu.get('vram_used', '?'):.1f}/{gpu.get('vram_total', '?'):.1f}GB | {gpu.get('util', '?')}% | {status_icon} |\n"

        report += f"""
## Endpoint Status

| Endpoint | Status | PID | Uptime | GPU |
|----------|--------|-----|--------|-----|
"""
        for ep in endpoint_status:
            uptime = ep.get('uptime', 'N/A')
            if isinstance(uptime, (int, float)):
                uptime = f"{uptime:.0f}s"
            report += f"| {ep.get('name', '?')} | {ep.get('status', '?')} | {ep.get('pid', 'N/A')} | {uptime} | {ep.get('gpu_ids', [])} |\n"

        # Add action links for issues
        unhealthy_endpoints = [ep for ep in endpoint_status if ep.get("status") in ("UNHEALTHY", "FAILED", "unhealthy", "failed")]
        if pending_approvals or unhealthy_endpoints:
            report += "\n## Required Actions\n\n"

            for ep in unhealthy_endpoints:
                ep_name = ep.get('name', 'unknown')
                if ep.get("status") in ("UNHEALTHY", "unhealthy"):
                    report += f"- [[action:/health fix {ep_name}]] - Restart unhealthy endpoint\n"
                elif ep.get("status") in ("FAILED", "failed"):
                    report += f"- [[action:/gpu restart {ep_name}]] - Force restart failed endpoint\n"

            for approval in pending_approvals:
                report += f"- [[action:/aiops approve {approval.get('id', '?')}]] - {approval.get('description', 'Pending action')}\n"

        report += f"""
## Recent Events

| Time | Category | Severity | Endpoint | Status |
|------|----------|----------|----------|--------|
"""
        for event in recent_events:
            created = event.get('created_at', '')
            if hasattr(created, 'strftime'):
                created = created.strftime('%H:%M:%S')
            report += f"| {created} | {event.get('category', '?')} | {event.get('severity', '?')} | {event.get('endpoint', '-')} | {event.get('status', '?')} |\n"

        if not recent_events:
            report += "| - | - | - | - | No recent events |\n"

        report += """
---
*Generated by /aiops command. Action links execute on Enter when selected in the graph panel.*
"""

        # Save to KB scratch
        today = now.strftime("%Y-%m-%d")
        timestamp = now.strftime("%H%M%S")

        kb_base = Path(os.environ.get("GAIUS_KB_PATH", "build/dev/scratch"))
        save_dir = kb_base / today
        save_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{timestamp}_aiops_report.md"
        filepath = save_dir / filename
        filepath.write_text(report)

        return {
            "report_path": str(filepath),
            "gpu_count": len(gpu_health),
            "endpoints": len(endpoint_status),
            "unhealthy_endpoints": len(unhealthy_endpoints),
            "pending_actions": len(pending_approvals),
            "recent_events": len(recent_events),
            "message": f"Report saved to {filepath}",
        }

    async def _get_gpu_health_data(self) -> list[dict]:
        """Get GPU health metrics."""
        gpus = []
        try:
            import pynvml
            pynvml.nvmlInit()
            device_count = pynvml.nvmlDeviceGetCount()

            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)

                gpus.append({
                    "index": i,
                    "temp": temp,
                    "vram_used": memory.used / (1024**3),
                    "vram_total": memory.total / (1024**3),
                    "util": util.gpu,
                    "healthy": temp < 85 and memory.used < memory.total * 0.95,
                })

            pynvml.nvmlShutdown()
        except ImportError:
            gpus.append({"index": 0, "error": "pynvml not available"})
        except Exception as e:
            gpus.append({"index": 0, "error": str(e)})

        return gpus

    async def _get_endpoint_status_data(self) -> list[dict]:
        """Get endpoint status from orchestrator."""
        endpoints = []
        try:
            # Try to get status from engine via gRPC
            from .engine.client import get_engine_client
            client = get_engine_client()

            if client and await client.ping():
                status = await client.orchestrator_status()
                for ep in status.get("endpoints", []):
                    endpoints.append({
                        "name": ep.get("agent_alias", ep.get("name", "?")),
                        "status": ep.get("status", "UNKNOWN"),
                        "pid": ep.get("pid"),
                        "uptime": ep.get("uptime_seconds", "N/A"),
                        "gpu_ids": ep.get("gpu_ids", []),
                    })
        except Exception as e:
            # Fallback: check vLLM processes directly
            try:
                import subprocess
                result = subprocess.run(
                    ["pgrep", "-a", "-f", "vllm.entrypoints"],
                    capture_output=True, text=True
                )
                if result.stdout:
                    for line in result.stdout.strip().split("\n"):
                        parts = line.split(maxsplit=1)
                        if parts:
                            endpoints.append({
                                "name": "vllm",
                                "status": "running",
                                "pid": int(parts[0]),
                            })
            except Exception:
                pass

        return endpoints

    async def _get_pending_approvals(self, event_type: str) -> list[dict]:
        """Get pending remediation approvals from database."""
        approvals = []
        try:
            import asyncpg
            import os

            from gaius.core.config import get_database_url
            db_url = get_database_url()
            conn = await asyncpg.connect(db_url)

            try:
                rows = await conn.fetch(
                    """
                    SELECT id, action_command, description, severity, created_at, expires_at
                    FROM remediation_approvals
                    WHERE event_type = $1 AND status = 'pending' AND expires_at > NOW()
                    ORDER BY created_at DESC
                    LIMIT 10
                    """,
                    event_type
                )
                for row in rows:
                    approvals.append({
                        "id": row["id"],
                        "action": row["action_command"],
                        "description": row["description"],
                        "severity": row["severity"],
                        "created_at": row["created_at"],
                        "expires_at": row["expires_at"],
                    })
            finally:
                await conn.close()
        except Exception:
            pass

        return approvals

    async def _get_recent_aiops_events(self, limit: int = 10) -> list[dict]:
        """Get recent AIOps events from database."""
        events = []
        try:
            import asyncpg
            import os

            from gaius.core.config import get_database_url
            db_url = get_database_url()
            conn = await asyncpg.connect(db_url)

            try:
                rows = await conn.fetch(
                    """
                    SELECT id, category, severity, status, endpoint, description, created_at
                    FROM aiops_events
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    limit
                )
                for row in rows:
                    events.append({
                        "id": row["id"],
                        "category": row["category"],
                        "severity": row["severity"],
                        "status": row["status"],
                        "endpoint": row["endpoint"],
                        "description": row["description"],
                        "created_at": row["created_at"],
                    })
            finally:
                await conn.close()
        except Exception:
            pass

        return events

    async def _aiops_pending_approvals(self) -> dict:
        """Show pending remediation approvals."""
        approvals = await self._get_pending_approvals("aiops")
        return {
            "pending_count": len(approvals),
            "approvals": approvals,
        }

    async def _aiops_approve(self, approval_id: str) -> dict:
        """Approve a pending remediation action."""
        try:
            import asyncpg
            import os
            from datetime import datetime

            from gaius.core.config import get_database_url
            db_url = get_database_url()
            conn = await asyncpg.connect(db_url)

            try:
                # Get the approval
                row = await conn.fetchrow(
                    """
                    SELECT id, action_command, event_type, event_id
                    FROM remediation_approvals
                    WHERE id = $1 AND status = 'pending'
                    """,
                    int(approval_id)
                )

                if not row:
                    return {"error": f"Approval {approval_id} not found or already processed"}

                # Mark as approved
                await conn.execute(
                    """
                    UPDATE remediation_approvals
                    SET status = 'approved', approved_by = 'user', approved_at = $1
                    WHERE id = $2
                    """,
                    datetime.now(),
                    int(approval_id)
                )

                # Execute the action
                action_cmd = row["action_command"]
                result = self.execute(action_cmd)

                return {
                    "approved": True,
                    "action": action_cmd,
                    "result": result,
                }
            finally:
                await conn.close()

        except Exception as e:
            return {"error": str(e)}

    async def _aiops_history(self) -> dict:
        """Show recent AIOps event history."""
        events = await self._get_recent_aiops_events(limit=20)
        return {
            "event_count": len(events),
            "events": events,
        }

    async def _cmd_mlops(self, args: str) -> dict:
        """MLOps: Model lifecycle management with KB reports.

        Generates reports as scratch KB documents with action links.

        Usage:
            /mlops              - Generate MLOps model report
            /mlops agents       - Show agent version status
            /mlops evolution    - Show evolution metrics
            /mlops promote <id> - Promote agent version
            /mlops history      - Show recent events
        """
        parts = args.strip().split() if args else []
        subcmd = parts[0].lower() if parts else "report"
        subargs = parts[1:] if len(parts) > 1 else []

        if subcmd == "report" or not args.strip():
            return await self._generate_mlops_report()
        elif subcmd == "agents":
            return await self._mlops_agent_status()
        elif subcmd == "evolution":
            return await self._mlops_evolution_metrics()
        elif subcmd == "promote" and subargs:
            return await self._mlops_promote(subargs[0])
        elif subcmd == "history":
            return await self._mlops_history()
        else:
            return {"error": "Usage: /mlops [report|agents|evolution|promote <id>|history]"}

    async def _generate_mlops_report(self) -> dict:
        """Generate MLOps model lifecycle report as KB scratch document."""
        from datetime import datetime
        from pathlib import Path
        import os

        # Collect MLOps data
        agent_versions = await self._get_agent_versions()
        evolution_status = await self._get_evolution_status()
        recent_events = await self._get_recent_mlops_events(limit=10)

        # Build report markdown
        now = datetime.now()
        report = f"""# MLOps Model Lifecycle Report

Generated: {now.isoformat()}

## Agent Versions

| Agent | Active Version | Score | Evaluations | Last Updated |
|-------|----------------|-------|-------------|--------------|
"""
        for agent in agent_versions:
            report += f"| {agent.get('agent_id', '?')} | {agent.get('version_id', 'N/A')[:12] if agent.get('version_id') else 'N/A'} | {agent.get('avg_score', 'N/A'):.2f if isinstance(agent.get('avg_score'), (int, float)) else 'N/A'} | {agent.get('eval_count', 0)} | {agent.get('created_at', 'N/A')} |\n"

        if not agent_versions:
            report += "| - | - | - | - | No agent versions found |\n"

        report += f"""
## Evolution Status

| Metric | Value |
|--------|-------|
| Daemon Running | {evolution_status.get('daemon_running', 'Unknown')} |
| Total Cycles | {evolution_status.get('total_cycles', 0)} |
| Last Cycle | {evolution_status.get('last_cycle', 'N/A')} |
| Next Agent | {evolution_status.get('next_agent', 'N/A')} |
| GPU Idle | {evolution_status.get('gpu_idle', 'Unknown')} |
"""

        # Add action links for improvements
        report += "\n## Available Actions\n\n"
        for agent in agent_versions:
            agent_id = agent.get('agent_id', 'unknown')
            report += f"- [[action:/evolve trigger {agent_id}]] - Trigger evolution for {agent_id}\n"

        if evolution_status.get('daemon_running') == 'stopped':
            report += "- [[action:/evolve start]] - Start evolution daemon\n"

        report += f"""
## Recent Events

| Time | Category | Agent | Severity | Status |
|------|----------|-------|----------|--------|
"""
        for event in recent_events:
            created = event.get('created_at', '')
            if hasattr(created, 'strftime'):
                created = created.strftime('%H:%M:%S')
            report += f"| {created} | {event.get('category', '?')} | {event.get('agent_id', '-')} | {event.get('severity', '?')} | {event.get('status', '?')} |\n"

        if not recent_events:
            report += "| - | - | - | - | No recent events |\n"

        report += """
---
*Generated by /mlops command. Action links execute on Enter when selected in the graph panel.*
"""

        # Save to KB scratch
        today = now.strftime("%Y-%m-%d")
        timestamp = now.strftime("%H%M%S")

        kb_base = Path(os.environ.get("GAIUS_KB_PATH", "build/dev/scratch"))
        save_dir = kb_base / today
        save_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{timestamp}_mlops_report.md"
        filepath = save_dir / filename
        filepath.write_text(report)

        return {
            "report_path": str(filepath),
            "agents": len(agent_versions),
            "evolution_running": evolution_status.get('daemon_running', False),
            "recent_events": len(recent_events),
            "message": f"Report saved to {filepath}",
        }

    async def _get_agent_versions(self) -> list[dict]:
        """Get agent version information from database."""
        versions = []
        try:
            import asyncpg
            import os

            from gaius.core.config import get_database_url
            db_url = get_database_url()
            conn = await asyncpg.connect(db_url)

            try:
                rows = await conn.fetch(
                    """
                    SELECT agent_id, version_id, avg_overall_score, total_evaluations, created_at, is_active
                    FROM agent_versions
                    WHERE is_active = true
                    ORDER BY agent_id
                    """
                )
                for row in rows:
                    created = row["created_at"]
                    if hasattr(created, 'strftime'):
                        created = created.strftime('%Y-%m-%d %H:%M')
                    versions.append({
                        "agent_id": row["agent_id"],
                        "version_id": row["version_id"],
                        "avg_score": row["avg_overall_score"],
                        "eval_count": row["total_evaluations"],
                        "created_at": created,
                        "is_active": row["is_active"],
                    })
            finally:
                await conn.close()
        except Exception:
            pass

        return versions

    async def _get_evolution_status(self) -> dict:
        """Get evolution daemon status."""
        status = {
            "daemon_running": "unknown",
            "total_cycles": 0,
            "last_cycle": "N/A",
            "next_agent": "N/A",
            "gpu_idle": "unknown",
        }

        try:
            # Try to get status from engine
            from .engine.client import get_engine_client
            client = get_engine_client()

            if client and await client.ping():
                evo_status = await client.evolution_status()
                status.update({
                    "daemon_running": "running" if evo_status.get("daemon_running") else "stopped",
                    "total_cycles": evo_status.get("cycles_completed", 0),
                    "last_cycle": evo_status.get("last_cycle_time", "N/A"),
                    "next_agent": evo_status.get("next_agent", "N/A"),
                    "gpu_idle": "yes" if evo_status.get("gpu_idle") else "no",
                })
        except Exception:
            pass

        return status

    async def _get_recent_mlops_events(self, limit: int = 10) -> list[dict]:
        """Get recent MLOps events from database."""
        events = []
        try:
            import asyncpg
            import os

            from gaius.core.config import get_database_url
            db_url = get_database_url()
            conn = await asyncpg.connect(db_url)

            try:
                rows = await conn.fetch(
                    """
                    SELECT id, category, severity, status, agent_id, description, created_at
                    FROM mlops_events
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    limit
                )
                for row in rows:
                    events.append({
                        "id": row["id"],
                        "category": row["category"],
                        "severity": row["severity"],
                        "status": row["status"],
                        "agent_id": row["agent_id"],
                        "description": row["description"],
                        "created_at": row["created_at"],
                    })
            finally:
                await conn.close()
        except Exception:
            pass

        return events

    async def _mlops_agent_status(self) -> dict:
        """Show agent version status."""
        versions = await self._get_agent_versions()
        return {
            "agent_count": len(versions),
            "agents": versions,
        }

    async def _mlops_evolution_metrics(self) -> dict:
        """Show evolution metrics and trends."""
        status = await self._get_evolution_status()
        return status

    async def _mlops_promote(self, version_id: str) -> dict:
        """Promote an agent version to active."""
        try:
            import asyncpg
            import os
            from datetime import datetime

            from gaius.core.config import get_database_url
            db_url = get_database_url()
            conn = await asyncpg.connect(db_url)

            try:
                # Get the version
                row = await conn.fetchrow(
                    """
                    SELECT agent_id, version_id
                    FROM agent_versions
                    WHERE version_id = $1
                    """,
                    version_id
                )

                if not row:
                    return {"error": f"Version {version_id} not found"}

                agent_id = row["agent_id"]

                # Deactivate other versions for this agent
                await conn.execute(
                    """
                    UPDATE agent_versions
                    SET is_active = false
                    WHERE agent_id = $1 AND is_active = true
                    """,
                    agent_id
                )

                # Activate this version
                await conn.execute(
                    """
                    UPDATE agent_versions
                    SET is_active = true
                    WHERE version_id = $1
                    """,
                    version_id
                )

                return {
                    "promoted": True,
                    "agent_id": agent_id,
                    "version_id": version_id,
                }
            finally:
                await conn.close()

        except Exception as e:
            return {"error": str(e)}

    async def _mlops_history(self) -> dict:
        """Show recent MLOps event history."""
        events = await self._get_recent_mlops_events(limit=20)
        return {
            "event_count": len(events),
            "events": events,
        }

    # =========================================================================
    # FMEA Commands - Failure Mode and Effects Analysis
    # =========================================================================

    async def _cmd_fmea(self, args: str) -> dict:
        """
        /fmea                - Show FMEA summary (top RPN issues)
        /fmea catalog        - List all failure modes
        /fmea detail <id>    - Show failure mode details
        /fmea history        - Recent FMEA incidents
        /fmea approve <id>   - Approve pending remediation
        """
        parts = args.strip().split() if args else []
        subcmd = parts[0] if parts else "summary"

        if subcmd == "summary" or subcmd == "":
            return await self._fmea_summary()
        elif subcmd == "catalog":
            return await self._fmea_catalog()
        elif subcmd == "detail" and len(parts) > 1:
            return await self._fmea_detail(parts[1])
        elif subcmd == "history":
            return await self._fmea_history()
        elif subcmd == "approve" and len(parts) > 1:
            return await self._fmea_approve(parts[1])
        else:
            return {"error": "Usage: /fmea [summary|catalog|detail <id>|history|approve <id>]"}

    async def _fmea_summary(self) -> dict:
        """Generate FMEA summary with top RPN issues."""
        from datetime import datetime
        import asyncpg

        try:
            from gaius.core.config import get_database_url
            db_url = get_database_url()
            conn = await asyncpg.connect(db_url)

            try:
                # Check if fmea_catalog table exists
                table_exists = await conn.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'fmea_catalog'
                    )
                    """
                )

                if not table_exists:
                    return {
                        "error": "FMEA not initialized. Run migrations and seed the catalog.",
                        "hint": "DATABASE_URL=... dbmate migrate && psql $DATABASE_URL -f db/seeds/fmea_catalog.sql"
                    }

                # Get top RPN issues from recent events
                top_issues = await conn.fetch(
                    """
                    SELECT
                        ae.id,
                        ae.failure_mode_id,
                        ae.rpn_score,
                        ae.runtime_severity as s,
                        ae.runtime_occurrence as o,
                        ae.runtime_detection as d,
                        ae.status,
                        ae.category,
                        ae.description,
                        ae.created_at
                    FROM aiops_events ae
                    WHERE ae.rpn_score IS NOT NULL
                    ORDER BY ae.rpn_score DESC, ae.created_at DESC
                    LIMIT 10
                    """
                )

                # Get pending approvals with high RPN
                pending = await conn.fetch(
                    """
                    SELECT
                        ra.id,
                        ra.failure_mode_id,
                        ra.rpn_score,
                        ra.action_command,
                        ra.description,
                        ra.created_at
                    FROM remediation_approvals ra
                    WHERE ra.status = 'pending'
                    AND ra.expires_at > NOW()
                    ORDER BY ra.rpn_score DESC NULLS LAST
                    LIMIT 5
                    """
                )

                # Get failure mode catalog stats
                catalog_stats = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) as total_modes,
                        COUNT(*) FILTER (WHERE base_severity * base_occurrence * base_detection >= 200) as high_rpn_modes
                    FROM fmea_catalog
                    """
                )

                # Build summary report
                now = datetime.now()
                report = f"""# FMEA Health Summary

Generated: {now.isoformat()}

## Catalog Overview

- Total Failure Modes: {catalog_stats['total_modes']}
- High RPN Modes (>=200): {catalog_stats['high_rpn_modes']}

## Top RPN Issues (Requires Attention)

| ID | Failure Mode | RPN | S×O×D | Status | Category |
|----|--------------|-----|-------|--------|----------|
"""
                for issue in top_issues:
                    fm_id = issue['failure_mode_id'] or issue['category']
                    s = issue['s'] or '?'
                    o = issue['o'] or '?'
                    d = issue['d'] or '?'
                    rpn = issue['rpn_score'] or 0
                    report += f"| {issue['id']} | {fm_id} | {rpn} | {s}×{o}×{d} | {issue['status']} | {issue['category']} |\n"

                if not top_issues:
                    report += "| - | No FMEA events recorded | - | - | - | - |\n"

                if pending:
                    report += "\n## Pending Approvals\n\n"
                    for p in pending:
                        fm_id = p['failure_mode_id'] or 'N/A'
                        rpn = p['rpn_score'] or 'N/A'
                        report += f"- [[action:/fmea approve {p['id']}]] - {p['description']} (RPN={rpn})\n"

                report += "\n## RPN Thresholds\n\n"
                report += "| RPN Range | Tier | Action |\n"
                report += "|-----------|------|--------|\n"
                report += "| 1-100 | Tier 0 | Auto-remediate immediately |\n"
                report += "| 101-200 | Tier 1 | Auto-remediate with logging |\n"
                report += "| 201-400 | Tier 2 | Require user approval |\n"
                report += "| 401-1000 | Manual | Human intervention required |\n"

                # Save to KB scratch
                report_path = await self._save_to_kb("FMEA Summary", report, "fmea")

                return {
                    "report_path": str(report_path),
                    "total_failure_modes": catalog_stats['total_modes'],
                    "high_rpn_modes": catalog_stats['high_rpn_modes'],
                    "top_rpn_count": len(top_issues),
                    "pending_approvals": len(pending),
                }

            finally:
                await conn.close()

        except Exception as e:
            return {"error": str(e)}

    async def _fmea_catalog(self) -> dict:
        """List all failure modes in the FMEA catalog."""
        import asyncpg

        try:
            from gaius.core.config import get_database_url
            db_url = get_database_url()
            conn = await asyncpg.connect(db_url)

            try:
                rows = await conn.fetch(
                    """
                    SELECT
                        failure_mode_id,
                        category,
                        name,
                        base_severity,
                        base_occurrence,
                        base_detection,
                        (base_severity * base_occurrence * base_detection) as base_rpn,
                        escalation_tier
                    FROM fmea_catalog
                    ORDER BY category, base_severity * base_occurrence * base_detection DESC
                    """
                )

                # Group by category
                categories: dict = {}
                for row in rows:
                    cat = row['category']
                    if cat not in categories:
                        categories[cat] = []
                    categories[cat].append({
                        "id": row['failure_mode_id'],
                        "name": row['name'],
                        "base_rpn": row['base_rpn'],
                        "s": row['base_severity'],
                        "o": row['base_occurrence'],
                        "d": row['base_detection'],
                        "tier": row['escalation_tier'],
                    })

                return {
                    "total_modes": len(rows),
                    "categories": categories,
                }

            finally:
                await conn.close()

        except Exception as e:
            return {"error": str(e)}

    async def _fmea_detail(self, failure_mode_id: str) -> dict:
        """Show detailed information about a failure mode."""
        import asyncpg

        try:
            from gaius.core.config import get_database_url
            db_url = get_database_url()
            conn = await asyncpg.connect(db_url)

            try:
                # Get failure mode from catalog
                row = await conn.fetchrow(
                    """
                    SELECT *
                    FROM fmea_catalog
                    WHERE failure_mode_id = $1
                    """,
                    failure_mode_id.upper()
                )

                if not row:
                    return {"error": f"Failure mode {failure_mode_id} not found"}

                # Get occurrence history
                occurrences = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE occurred_at > NOW() - INTERVAL '24 hours') as last_24h,
                        COUNT(*) FILTER (WHERE occurred_at > NOW() - INTERVAL '7 days') as last_7d,
                        COUNT(*) FILTER (WHERE occurred_at > NOW() - INTERVAL '30 days') as last_30d
                    FROM fmea_occurrences
                    WHERE failure_mode_id = $1
                    """,
                    failure_mode_id.upper()
                )

                # Get outcome stats
                outcomes = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE success) as successes,
                        AVG(duration_ms)::int as avg_duration_ms,
                        AVG(downtime_seconds)::int as avg_downtime_s
                    FROM fmea_outcomes
                    WHERE failure_mode_id = $1
                    """,
                    failure_mode_id.upper()
                )

                base_rpn = row['base_severity'] * row['base_occurrence'] * row['base_detection']

                return {
                    "failure_mode_id": row['failure_mode_id'],
                    "category": row['category'],
                    "name": row['name'],
                    "description": row['description'],
                    "base_scores": {
                        "severity": row['base_severity'],
                        "occurrence": row['base_occurrence'],
                        "detection": row['base_detection'],
                        "rpn": base_rpn,
                    },
                    "detection_method": row['detection_method'],
                    "recommended_actions": row['recommended_actions'],
                    "escalation_tier": row['escalation_tier'],
                    "occurrences": {
                        "last_24h": occurrences['last_24h'] if occurrences else 0,
                        "last_7d": occurrences['last_7d'] if occurrences else 0,
                        "last_30d": occurrences['last_30d'] if occurrences else 0,
                    },
                    "outcomes": {
                        "total": outcomes['total'] if outcomes else 0,
                        "successes": outcomes['successes'] if outcomes else 0,
                        "avg_duration_ms": outcomes['avg_duration_ms'] if outcomes else None,
                        "avg_downtime_seconds": outcomes['avg_downtime_s'] if outcomes else None,
                    },
                }

            finally:
                await conn.close()

        except Exception as e:
            return {"error": str(e)}

    async def _fmea_history(self) -> dict:
        """Show recent FMEA incident history."""
        import asyncpg

        try:
            from gaius.core.config import get_database_url
            db_url = get_database_url()
            conn = await asyncpg.connect(db_url)

            try:
                # Get recent AIOps events with FMEA data
                rows = await conn.fetch(
                    """
                    SELECT
                        ae.id,
                        ae.failure_mode_id,
                        ae.category,
                        ae.rpn_score,
                        ae.runtime_severity,
                        ae.runtime_occurrence,
                        ae.runtime_detection,
                        ae.status,
                        ae.endpoint,
                        ae.description,
                        ae.created_at
                    FROM aiops_events ae
                    WHERE ae.failure_mode_id IS NOT NULL OR ae.rpn_score IS NOT NULL
                    ORDER BY ae.created_at DESC
                    LIMIT 20
                    """
                )

                events = []
                for row in rows:
                    events.append({
                        "id": row['id'],
                        "failure_mode_id": row['failure_mode_id'],
                        "category": row['category'],
                        "rpn_score": row['rpn_score'],
                        "severity": row['runtime_severity'],
                        "occurrence": row['runtime_occurrence'],
                        "detection": row['runtime_detection'],
                        "status": row['status'],
                        "endpoint": row['endpoint'],
                        "description": row['description'][:80] if row['description'] else None,
                        "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                    })

                return {
                    "event_count": len(events),
                    "events": events,
                }

            finally:
                await conn.close()

        except Exception as e:
            return {"error": str(e)}

    async def _fmea_approve(self, approval_id: str) -> dict:
        """Approve a pending FMEA remediation action."""
        import asyncpg

        try:
            approval_id_int = int(approval_id)
        except ValueError:
            return {"error": f"Invalid approval ID: {approval_id}"}

        try:
            from gaius.core.config import get_database_url
            db_url = get_database_url()
            conn = await asyncpg.connect(db_url)

            try:
                # Get the pending approval
                row = await conn.fetchrow(
                    """
                    SELECT *
                    FROM remediation_approvals
                    WHERE id = $1 AND status = 'pending'
                    """,
                    approval_id_int
                )

                if not row:
                    return {"error": f"No pending approval with ID {approval_id}"}

                # Check if expired
                from datetime import datetime
                if row['expires_at'] < datetime.now(row['expires_at'].tzinfo):
                    return {"error": f"Approval {approval_id} has expired"}

                # Approve it
                await conn.execute(
                    """
                    UPDATE remediation_approvals
                    SET status = 'approved', approved_by = 'cli', approved_at = NOW()
                    WHERE id = $1
                    """,
                    approval_id_int
                )

                return {
                    "approved": True,
                    "id": approval_id_int,
                    "action_command": row['action_command'],
                    "failure_mode_id": row['failure_mode_id'],
                    "message": f"Approved: {row['action_command']}",
                }

            finally:
                await conn.close()

        except Exception as e:
            return {"error": str(e)}

    async def _cmd_flow(self, args: str) -> dict:
        """Metaflow pipeline management.

        Usage:
            /flow                    - Show available flows and status
            /flow list               - List registered flows
            /flow run <name> <url>   - Run a flow (e.g., /flow run docling https://arxiv.org/abs/...)
            /flow lineage <kb_path>  - Query lineage for a KB file
            /flow config [local|k8s] - Show/switch Metaflow configuration

        Docling flow options (default: full run with all features enabled):
            /flow run docling <url>              - Full run: PDF + topics + scoring
            /flow run docling <url> --no-topics  - Disable topic modeling
            /flow run docling <url> --no-scoring - Disable LLM scoring
            /flow run docling <url> --no-archive - Don't save PDF to KB
            /flow run docling <url> --no-gpu     - CPU-only mode
            /flow run docling <url> --model=lda  - Use LDA instead of BERTopic
            /flow run docling <url> --topics=10  - Set number of topics (LDA/LSA)
            /flow run docling <url> --rubric=strict - Use alternative rubric
            /flow run docling <url> --remote-scoring - Use remote LLM for scoring
        """
        parts = args.strip().split() if args else []
        subcmd = parts[0].lower() if parts else "list"

        if subcmd == "list":
            return self._flow_list()

        elif subcmd == "run":
            if len(parts) < 3:
                return {"error": "Usage: /flow run <flow_name> <args...>"}
            flow_name = parts[1]
            flow_args = parts[2:]
            return await self._flow_run(flow_name, flow_args)

        elif subcmd == "lineage":
            if len(parts) < 2:
                return {"error": "Usage: /flow lineage <kb_path>"}
            kb_path = parts[1]
            return await self._flow_lineage(kb_path)

        elif subcmd == "config":
            mode = parts[1] if len(parts) > 1 else None
            return self._flow_config(mode)

        else:
            return {"error": f"Unknown flow subcommand: {subcmd}"}

    def _flow_list(self) -> dict:
        """List available flows."""
        try:
            from gaius.flows import FLOW_REGISTRY

            flows = []
            for name, flow_cls in FLOW_REGISTRY.items():
                doc = flow_cls.__doc__ or ""
                first_line = doc.split("\n")[0].strip() if doc else ""
                flows.append({
                    "name": name,
                    "description": first_line,
                    "class": f"{flow_cls.__module__}.{flow_cls.__name__}",
                })

            return {
                "flows": flows,
                "total": len(flows),
                "message": f"Found {len(flows)} registered flow(s)" if flows else "No flows registered. Import gaius.flows.docling to register flows.",
            }

        except Exception as e:
            return {"error": str(e)}

    async def _flow_run(self, flow_name: str, flow_args: list[str]) -> dict:
        """Run a Metaflow flow with GPU resource management.

        For GPU-intensive flows (like docling), this will:
        1. Check GPU memory availability
        2. Evict idle vLLM endpoints if needed
        3. Run the flow
        4. Restore evicted endpoints after completion
        """
        try:
            from gaius.flows import FLOW_REGISTRY
            from gaius.flows.config import apply_metaflow_config

            if flow_name not in FLOW_REGISTRY:
                # Try to import the flow module to register it
                if flow_name == "docling":
                    from gaius.flows.docling import ArxivDoclingFlow  # noqa: F401
                    from gaius.flows import FLOW_REGISTRY

            if flow_name not in FLOW_REGISTRY:
                return {
                    "error": f"Unknown flow: {flow_name}",
                    "available": list(FLOW_REGISTRY.keys()),
                }

            # Apply local config
            apply_metaflow_config("local")

            # For docling flow, we expect a URL
            if flow_name == "docling":
                if not flow_args:
                    return {"error": "docling flow requires an arXiv URL argument"}

                arxiv_url = flow_args[0]

                # Parse flags - defaults enable all features for full runs
                archive_pdf = "--no-archive" not in flow_args
                no_gpu = "--no-gpu" in flow_args
                enable_topics = "--no-topics" not in flow_args
                enable_scoring = "--no-scoring" not in flow_args
                use_remote_scoring = "--remote-scoring" in flow_args

                # Parse value-based options
                topic_model_type = "bertopic"  # default: neural topics
                scoring_rubric = "default"
                num_topics = None

                for arg in flow_args:
                    if arg.startswith("--model="):
                        topic_model_type = arg.split("=", 1)[1]
                    elif arg.startswith("--rubric="):
                        scoring_rubric = arg.split("=", 1)[1]
                    elif arg.startswith("--topics="):
                        try:
                            num_topics = int(arg.split("=", 1)[1])
                        except ValueError:
                            pass

                # Use GPU-aware runner
                from gaius.flows.runner import run_flow_with_gpu_management
                from gaius.flows.docling.flow import ArxivDoclingFlow

                # Build flow args for subprocess - full run with all features
                subprocess_args = [
                    f"--arxiv_url={arxiv_url}",
                    f"--archive_pdf={archive_pdf}",
                    f"--enable_topics={enable_topics}",
                    f"--topic_model_type={topic_model_type}",
                    f"--enable_scoring={enable_scoring}",
                    f"--scoring_rubric={scoring_rubric}",
                    f"--use_remote_scoring={use_remote_scoring}",
                ]
                if num_topics is not None:
                    subprocess_args.append(f"--num_topics={num_topics}")

                result = await run_flow_with_gpu_management(
                    flow_class=ArxivDoclingFlow,
                    flow_args=subprocess_args,
                    require_gpu=not no_gpu,
                    estimated_memory_mb=16000,  # Docling needs ~16GB
                )

                return {
                    "flow": flow_name,
                    "url": arxiv_url,
                    "success": result.success,
                    "workload_id": result.workload_id,
                    "evicted_endpoints": result.evicted_endpoints,
                    "restored_endpoints": result.restored_endpoints,
                    "output_path": result.output_path,
                    "duration_s": result.duration_s,
                    "error": result.error,
                    "gpu_management": not no_gpu,
                    "options": {
                        "topics": enable_topics,
                        "topic_model": topic_model_type,
                        "num_topics": num_topics,
                        "scoring": enable_scoring,
                        "rubric": scoring_rubric,
                        "remote_scoring": use_remote_scoring,
                    },
                }

            return {"error": f"Flow {flow_name} not yet implemented via CLI"}

        except Exception as e:
            import traceback
            return {"error": str(e), "traceback": traceback.format_exc()}

    async def _flow_lineage(self, kb_path: str) -> dict:
        """Query lineage for a KB file."""
        try:
            from gaius.hx.lineage.graph import LineageGraphQuery

            query = LineageGraphQuery()
            path = await query.get_kb_lineage(kb_path)

            if not path.nodes:
                return {
                    "kb_path": kb_path,
                    "lineage": None,
                    "message": "No lineage found for this KB path",
                }

            return {
                "kb_path": kb_path,
                "nodes": [
                    {"type": n.node_type, "id": n.id, "properties": n.properties}
                    for n in path.nodes
                ],
                "edges": [
                    {"type": e.edge_type, "from": e.from_id, "to": e.to_id}
                    for e in path.edges
                ],
                "node_count": len(path.nodes),
                "edge_count": len(path.edges),
            }

        except Exception as e:
            return {"error": str(e)}

    def _flow_config(self, mode: str | None = None) -> dict:
        """Show or switch Metaflow configuration."""
        try:
            from gaius.flows.config import load_metaflow_config, get_config_path

            if mode:
                config = load_metaflow_config(mode)
                path = get_config_path(mode)
                return {
                    "mode": mode,
                    "config_path": str(path),
                    "config": config,
                    "exists": path.exists(),
                }

            # Show both configs
            local_config = load_metaflow_config("local")
            k8s_config = load_metaflow_config("k8s")

            return {
                "local": {
                    "path": str(get_config_path("local")),
                    "exists": get_config_path("local").exists(),
                    "config": local_config,
                },
                "k8s": {
                    "path": str(get_config_path("k8s")),
                    "exists": get_config_path("k8s").exists(),
                    "config": k8s_config,
                },
            }

        except Exception as e:
            return {"error": str(e)}

    async def _cmd_fetch(self, args: str) -> dict:
        """Fetch arXiv paper with topic modeling and scoring.

        Shortcut for /flow run docling. Default: full run with all features.

        Usage:
            /fetch <arxiv_url>              - Full run: PDF → markdown → topics → scoring → KB
            /fetch <url> --no-topics        - Disable topic modeling
            /fetch <url> --no-scoring       - Disable LLM scoring
            /fetch <url> --model=lda        - Use LDA instead of BERTopic
            /fetch <url> --topics=10        - Set number of topics (LDA/LSA only)
            /fetch <url> --rubric=strict    - Use alternative rubric
            /fetch <url> --remote-scoring   - Use remote LLM for scoring
            /fetch <url> --no-gpu           - CPU-only mode (slower)

        Examples:
            /fetch https://arxiv.org/abs/2312.12345
            /fetch 2312.12345 --model=bertopic --rubric=default
        """
        if not args.strip():
            return {
                "error": "Usage: /fetch <arxiv_url> [options]",
                "help": self._cmd_fetch.__doc__,
            }

        # Delegate to /flow run docling with args
        flow_args = f"run docling {args}"
        return await self._cmd_flow(flow_args)


def main():
    """CLI entry point."""
    # Initialize telemetry early with CLI entry point
    try:
        from .core.config import get_config
        from .core.telemetry import init_from_config
        config = get_config()
        init_from_config(config, entry_point="cli")
    except Exception:
        pass  # Telemetry init failure is non-fatal

    parser = argparse.ArgumentParser(
        description="Gaius CLI - Non-interactive command mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python -m gaius.cli --cmd "/info K10"
  uv run python -m gaius.cli --cmd "/domain pension" --cmd "/state"
  echo "/info" | uv run python -m gaius.cli
        """
    )
    parser.add_argument(
        "--cmd", "-c",
        action="append",
        dest="commands",
        help="Command to execute (can be repeated)"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)"
    )

    args = parser.parse_args()

    cli = GaiusCLI()
    cli.format = args.format

    commands = args.commands or []

    # Read from stdin if no commands and stdin is not a tty
    if not commands and not sys.stdin.isatty():
        for line in sys.stdin:
            line = line.strip()
            if line:
                commands.append(line)

    if not commands:
        parser.print_help()
        sys.exit(1)

    exit_code = 0
    for cmd in commands:
        result = cli.execute(cmd)
        output = cli.format_output(result)
        print(output)
        if not result["success"]:
            exit_code = 1

    # Flush telemetry before exit (CLI commands are short-lived)
    try:
        from .core.telemetry import flush_telemetry
        flush_telemetry(timeout_ms=3000)
    except Exception:
        pass  # Telemetry flush failure is non-fatal

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
