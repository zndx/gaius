"""State client for thin TUI architecture.

Provides a dedicated client for the State service, enabling:
- Instant TUI startup via cached state from Postgres
- State subscription for real-time updates
- UI preference persistence across sessions
- Unified state access for TUI/CLI/MCP

This is the primary client for Phase 1 of the thin TUI architecture.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, AsyncIterator, Callable, Optional

if TYPE_CHECKING:
    from ..engine.generated import GaiusServiceAsyncStub

# Suppress gRPC fork warnings before importing grpc
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "0")

import grpc
from grpc import aio
from google.protobuf import empty_pb2
from google.protobuf.json_format import MessageToDict

logger = logging.getLogger(__name__)


class ConnectionStatus(Enum):
    """Connection status for thin client UI."""
    PENDING = "pending"       # Not yet attempted
    CONNECTING = "connecting"  # Connection in progress
    CONNECTED = "connected"    # Successfully connected
    OFFLINE = "offline"        # Engine unavailable, using cached state
    ERROR = "error"            # Connection failed with error


@dataclass
class GridPosition:
    """Position on the 19x19 grid."""
    x: int
    y: int
    path: str = ""
    title: str = ""
    cluster_id: int = -1


@dataclass
class BoundingBox:
    """Bounding box for TDA features."""
    x_min: int
    y_min: int
    x_max: int
    y_max: int
    persistence: float = 0.0


@dataclass
class TDAFeatures:
    """TDA features for grid state."""
    h0_count: int = 0
    h1_count: int = 0
    h2_count: int = 0
    h1_cycles: list[BoundingBox] = field(default_factory=list)
    h2_voids: list[BoundingBox] = field(default_factory=list)
    components: list[BoundingBox] = field(default_factory=list)
    risk_scores: list[float] = field(default_factory=list)
    entropy: float = 0.0


@dataclass
class GeometryFeatures:
    """Geometry features for grid state."""
    # gradient_field: list of [x, y, gx, gy] - coordinates and gradient vector
    gradient_field: list = field(default_factory=list)
    # curvature_map: 19x19 nested list (reconstructed from flat 361-element list)
    curvature_map: list[list[float]] = field(default_factory=list)
    # divergence_map: 19x19 nested list (reconstructed from flat 361-element list)
    divergence_map: list[list[float]] = field(default_factory=list)


@dataclass
class GridState:
    """Complete grid state for TUI rendering.

    This represents the full state needed to render the TUI grid,
    loaded from either cached Postgres state (instant startup) or
    fresh computation via Engine.
    """
    snapshot_id: str = ""
    generation: int = 0
    updated_at_ms: int = 0

    # Grid data
    documents: list[GridPosition] = field(default_factory=list)
    clusters: list[tuple[int, int]] = field(default_factory=list)
    allocations: list[int] = field(default_factory=list)  # 361 values (19x19)

    # Features
    tda: TDAFeatures = field(default_factory=TDAFeatures)
    geometry: GeometryFeatures = field(default_factory=GeometryFeatures)

    # Metadata
    n_documents: int = 0
    projection_method: str = "umap"
    embedding_model: str = ""

    # Source indicator
    from_cache: bool = False


@dataclass
class UIPreferences:
    """UI preferences for persistence."""
    client_id: str = ""
    cursor_x: int = 9
    cursor_y: int = 9
    view_mode: str = "go"
    overlay_mode: str = "none"
    iso_mode: str = "curvature"
    center_panel_mode: str = "graph"
    left_panel_visible: bool = True
    right_panel_visible: bool = True
    domain: str = ""


@dataclass
class StateUpdate:
    """State update from subscription stream."""

    class Type(Enum):
        FULL_REFRESH = 0
        GENERATION_CHANGED = 1
        COMPUTATION_STARTED = 2
        COMPUTATION_PROGRESS = 3
        COMPUTATION_COMPLETE = 4
        ERROR = 5

    type: Type
    generation: int = 0
    state: Optional[GridState] = None
    progress: float = 0.0
    message: str = ""


class StateClient:
    """Client for State service in thin TUI architecture.

    Provides:
    - get_current_state(): Load state for instant startup
    - subscribe_state(): Stream state updates
    - get/save_preferences(): UI preference persistence
    - prune_snapshots(): Cleanup old snapshots

    Works in both online (Engine connected) and offline (cached only) modes.

    Usage:
        client = StateClient()

        # Instant startup - load cached state
        state = await client.get_current_state("build/dev")
        if state:
            render_grid(state)

        # Background sync - subscribe to updates
        async for update in client.subscribe_state("build/dev"):
            if update.type == StateUpdate.Type.GENERATION_CHANGED:
                render_grid(update.state)
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 50051,
        connect_timeout: float = 2.0,
        request_timeout: float = 10.0,
    ):
        """Initialize state client.

        Args:
            host: Engine gRPC host
            port: Engine gRPC port
            connect_timeout: Connection timeout (keep low for instant startup)
            request_timeout: Request timeout for state operations
        """
        self.host = os.environ.get("GAIUS_GRPC_HOST", host)
        self.port = int(os.environ.get("GAIUS_GRPC_PORT", str(port)))
        self.connect_timeout = connect_timeout
        self.request_timeout = request_timeout

        self._channel: Optional[aio.Channel] = None
        self._stub: Optional["GaiusServiceAsyncStub"] = None
        self._status = ConnectionStatus.PENDING
        self._status_callbacks: list[Callable[[ConnectionStatus], None]] = []

        # Background subscription task
        self._subscription_task: Optional[asyncio.Task] = None
        self._state_callbacks: list[Callable[[StateUpdate], None]] = []

    @property
    def status(self) -> ConnectionStatus:
        """Current connection status."""
        return self._status

    @property
    def is_connected(self) -> bool:
        """Whether connected to Engine."""
        return self._status == ConnectionStatus.CONNECTED

    def on_status_change(self, callback: Callable[[ConnectionStatus], None]) -> None:
        """Register callback for connection status changes."""
        self._status_callbacks.append(callback)

    def _set_status(self, status: ConnectionStatus) -> None:
        """Update status and notify callbacks."""
        if status != self._status:
            self._status = status
            for callback in self._status_callbacks:
                try:
                    callback(status)
                except Exception as e:
                    logger.warning(f"Status callback error: {e}")

    async def connect(self) -> bool:
        """Connect to Engine gRPC service.

        Returns:
            True if connected, False if offline (cached mode)
        """
        if self._status == ConnectionStatus.CONNECTED:
            return True

        self._set_status(ConnectionStatus.CONNECTING)
        target = f"{self.host}:{self.port}"

        try:
            self._channel = aio.insecure_channel(
                target,
                options=[
                    ("grpc.max_receive_message_length", 50 * 1024 * 1024),
                    ("grpc.max_send_message_length", 50 * 1024 * 1024),
                ],
            )

            await asyncio.wait_for(
                self._channel.channel_ready(),
                timeout=self.connect_timeout,
            )

            # Import stub lazily to avoid import cycles
            from ..engine.generated import GaiusServiceAsyncStub
            self._stub = GaiusServiceAsyncStub(self._channel)

            self._set_status(ConnectionStatus.CONNECTED)
            logger.info(f"StateClient connected to {target}")
            return True

        except asyncio.TimeoutError:
            logger.debug(f"StateClient connection timeout to {target}")
            self._set_status(ConnectionStatus.OFFLINE)
            return False
        except grpc.RpcError as e:
            logger.debug(f"StateClient connection failed: {e}")
            self._set_status(ConnectionStatus.OFFLINE)
            return False
        except Exception as e:
            logger.debug(f"StateClient connection error: {e}")
            self._set_status(ConnectionStatus.ERROR)
            return False

    async def disconnect(self) -> None:
        """Disconnect from Engine."""
        if self._subscription_task:
            self._subscription_task.cancel()
            try:
                await self._subscription_task
            except asyncio.CancelledError:
                pass

        if self._channel:
            await self._channel.close(grace=None)

        self._channel = None
        self._stub = None
        self._set_status(ConnectionStatus.PENDING)

    async def get_current_state(
        self,
        kb_root: str,
        client_id: str = "tui",
        since_generation: int = 0,
        include_geometry: bool = True,
    ) -> Optional[GridState]:
        """Get current grid state for instant TUI startup.

        Attempts to load from Engine first, falls back to cached Postgres
        state if Engine is unavailable.

        Args:
            kb_root: KB root directory
            client_id: Client identifier
            since_generation: Only return if generation > this (0 = always return)
            include_geometry: Include geometry features

        Returns:
            GridState if available, None if no state exists
        """
        # Try Engine first if connected
        if self._status == ConnectionStatus.CONNECTED:
            try:
                return await self._get_state_from_engine(
                    kb_root, client_id, since_generation, include_geometry
                )
            except Exception as e:
                logger.warning(f"Engine state fetch failed: {e}")
                self._set_status(ConnectionStatus.OFFLINE)

        # Try to connect if not connected
        if self._status in (ConnectionStatus.PENDING, ConnectionStatus.OFFLINE):
            connected = await self.connect()
            if connected:
                try:
                    return await self._get_state_from_engine(
                        kb_root, client_id, since_generation, include_geometry
                    )
                except Exception as e:
                    logger.warning(f"Engine state fetch failed after connect: {e}")
                    self._set_status(ConnectionStatus.OFFLINE)

        # Fall back to cached state from Postgres
        return await self._get_state_from_cache(kb_root)

    async def _get_state_from_engine(
        self,
        kb_root: str,
        client_id: str,
        since_generation: int,
        include_geometry: bool,
    ) -> Optional[GridState]:
        """Fetch state from Engine via gRPC."""
        from ..engine.generated import GetStateRequest

        request = GetStateRequest(
            kb_root=kb_root,
            client_id=client_id,
            since_generation=since_generation,
            include_geometry=include_geometry,
        )

        assert self._stub is not None  # Guaranteed by is_connected check in caller
        response = await self._stub.GetCurrentState(
            request,
            timeout=self.request_timeout,
        )

        # Convert protobuf to dataclass
        return self._proto_to_grid_state(response)

    async def _get_state_from_cache(self, kb_root: str) -> Optional[GridState]:
        """Load cached state directly from Postgres."""
        from ..storage.grid_state import load_current_state_fast

        try:
            cached = await load_current_state_fast(kb_root)
            if not cached:
                return None

            # Convert storage dataclass to client dataclass
            documents = [
                GridPosition(
                    x=d.get("x", 0),
                    y=d.get("y", 0),
                    path=d.get("path", ""),
                    title=d.get("title", ""),
                    cluster_id=d.get("cluster_id", -1),
                )
                for d in cached.documents
            ]

            # Flatten allocations to 361 values
            allocations = []
            for row in cached.allocations:
                allocations.extend(row)

            # Convert TDA features
            tda = TDAFeatures(
                h0_count=cached.h0_count,
                h1_count=cached.h1_count,
                h2_count=cached.h2_count,
                h1_cycles=[
                    BoundingBox(
                        x_min=b.get("x_min", 0),
                        y_min=b.get("y_min", 0),
                        x_max=b.get("x_max", 0),
                        y_max=b.get("y_max", 0),
                        persistence=b.get("persistence", 0.0),
                    )
                    for b in cached.h1_cycles
                ],
                h2_voids=[
                    BoundingBox(
                        x_min=b.get("x_min", 0),
                        y_min=b.get("y_min", 0),
                        x_max=b.get("x_max", 0),
                        y_max=b.get("y_max", 0),
                        persistence=b.get("persistence", 0.0),
                    )
                    for b in cached.h2_voids
                ],
                components=[
                    BoundingBox(
                        x_min=b.get("x_min", 0),
                        y_min=b.get("y_min", 0),
                        x_max=b.get("x_max", 0),
                        y_max=b.get("y_max", 0),
                        persistence=b.get("persistence", 0.0),
                    )
                    for b in cached.components
                ],
                risk_scores=cached.risk_scores,
                entropy=cached.entropy,
            )

            updated_ms = 0
            if cached.updated_at:
                updated_ms = int(cached.updated_at.timestamp() * 1000)

            return GridState(
                snapshot_id=str(cached.snapshot_id) if cached.snapshot_id else "",
                generation=cached.generation,
                updated_at_ms=updated_ms,
                documents=documents,
                clusters=cached.clusters,
                allocations=allocations,
                tda=tda,
                n_documents=cached.n_documents,
                projection_method=cached.projection_method,
                embedding_model=cached.embedding_model,
                from_cache=True,
            )

        except Exception as e:
            logger.warning(f"Cache state load failed: {e}")
            return None

    def _proto_to_grid_state(self, proto) -> Optional[GridState]:
        """Convert protobuf GridState to dataclass."""
        if not proto or proto.generation == 0:
            return None

        documents = [
            GridPosition(
                x=p.x,
                y=p.y,
                path=p.id,  # proto uses 'id' for document path
                title="",   # proto GridPosition doesn't have title
                cluster_id=p.cluster,  # proto uses 'cluster' not 'cluster_id'
            )
            for p in proto.documents
        ]

        clusters = [(p.x, p.y) for p in proto.clusters]

        # Convert TDA if present
        tda = TDAFeatures()
        if proto.HasField("tda"):
            tda = TDAFeatures(
                h0_count=proto.tda.h0_count,
                h1_count=proto.tda.h1_count,
                h2_count=proto.tda.h2_count,
                h1_cycles=[
                    BoundingBox(
                        x_min=b.x_min,
                        y_min=b.y_min,
                        x_max=b.x_max,
                        y_max=b.y_max,
                        persistence=b.persistence,
                    )
                    for b in proto.tda.h1_cycles
                ],
                h2_voids=[
                    BoundingBox(
                        x_min=b.x_min,
                        y_min=b.y_min,
                        x_max=b.x_max,
                        y_max=b.y_max,
                        persistence=b.persistence,
                    )
                    for b in proto.tda.h2_voids
                ],
                # Note: proto TDAFeatures doesn't have components field
                components=[],
                risk_scores=list(proto.tda.risk_scores),
                entropy=proto.tda.entropy,
            )

        # Convert geometry if present
        geometry = GeometryFeatures()
        if proto.HasField("geometry"):
            # gradient_field: proto has GradientVector with x, y, gx, gy
            gradient_field = [
                [g.x, g.y, g.gx, g.gy] for g in proto.geometry.gradient_field
            ]

            # Convert flat 361-element curvature_map to 19x19 nested list
            curvature_map = []
            if proto.geometry.curvature_map:
                flat = list(proto.geometry.curvature_map)
                curvature_map = [flat[i*19:(i+1)*19] for i in range(19)]

            # Convert flat 361-element divergence_map to 19x19 nested list
            divergence_map = []
            if proto.geometry.divergence_map:
                flat = list(proto.geometry.divergence_map)
                divergence_map = [flat[i*19:(i+1)*19] for i in range(19)]

            geometry = GeometryFeatures(
                gradient_field=gradient_field,
                curvature_map=curvature_map,
                divergence_map=divergence_map,
            )

        return GridState(
            snapshot_id=proto.snapshot_id,
            generation=proto.generation,
            updated_at_ms=proto.updated_at_ms,
            documents=documents,
            clusters=clusters,
            allocations=list(proto.allocations),
            tda=tda,
            geometry=geometry,
            n_documents=proto.n_documents,
            projection_method=proto.projection_method,
            embedding_model=proto.embedding_model,
            from_cache=False,
        )

    async def subscribe_state(
        self,
        kb_root: str,
        client_id: str = "tui",
    ) -> AsyncIterator[StateUpdate]:
        """Subscribe to state updates.

        Yields StateUpdate objects when the grid state changes.
        Generation-based: only yields when generation increments.

        Args:
            kb_root: KB root directory
            client_id: Client identifier

        Yields:
            StateUpdate objects
        """
        if not self.is_connected:
            connected = await self.connect()
            if not connected:
                # Yield offline indicator and return
                yield StateUpdate(
                    type=StateUpdate.Type.ERROR,
                    message="Engine offline - using cached state",
                )
                return

        try:
            from ..engine.generated import SubscribeStateRequest

            request = SubscribeStateRequest(
                kb_root=kb_root,
                client_id=client_id,
            )

            assert self._stub is not None  # Guaranteed by is_connected check above
            async for update in self._stub.SubscribeState(request):
                yield self._proto_to_state_update(update)

        except grpc.RpcError as e:
            if e.code() != grpc.StatusCode.CANCELLED:
                logger.warning(f"State subscription error: {e}")
                self._set_status(ConnectionStatus.OFFLINE)
                yield StateUpdate(
                    type=StateUpdate.Type.ERROR,
                    message=f"Subscription failed: {e.details()}",
                )

    def _proto_to_state_update(self, proto) -> StateUpdate:
        """Convert protobuf StateUpdate to dataclass."""
        type_map = {
            0: StateUpdate.Type.FULL_REFRESH,
            1: StateUpdate.Type.GENERATION_CHANGED,
            2: StateUpdate.Type.COMPUTATION_STARTED,
            3: StateUpdate.Type.COMPUTATION_PROGRESS,
            4: StateUpdate.Type.COMPUTATION_COMPLETE,
            5: StateUpdate.Type.ERROR,
        }

        state = None
        if proto.HasField("state"):
            state = self._proto_to_grid_state(proto.state)

        return StateUpdate(
            type=type_map.get(proto.type, StateUpdate.Type.ERROR),
            generation=proto.generation,
            state=state,
            progress=proto.progress,
            message=proto.message,
        )

    async def get_preferences(self, client_id: str = "tui") -> Optional[UIPreferences]:
        """Get UI preferences for client.

        Falls back to Postgres cache if Engine unavailable.

        Args:
            client_id: Client identifier

        Returns:
            UIPreferences if found, None otherwise
        """
        # Try Engine first
        if self.is_connected:
            try:
                from ..engine.generated import GetPreferencesRequest

                request = GetPreferencesRequest(client_id=client_id)
                assert self._stub is not None  # Guaranteed by is_connected check
                response = await self._stub.GetPreferences(
                    request,
                    timeout=self.request_timeout,
                )

                return UIPreferences(
                    client_id=response.client_id,
                    cursor_x=response.cursor_x,
                    cursor_y=response.cursor_y,
                    view_mode=response.view_mode,
                    overlay_mode=response.overlay_mode,
                    iso_mode=response.iso_mode,
                    center_panel_mode=response.center_panel_mode,
                    left_panel_visible=response.left_panel_visible,
                    right_panel_visible=response.right_panel_visible,
                    domain=response.domain,
                )
            except Exception as e:
                logger.debug(f"Engine preferences fetch failed: {e}")

        # Fall back to Postgres
        try:
            from ..storage.grid_state import load_ui_preferences

            prefs = await load_ui_preferences(client_id)
            if prefs:
                return UIPreferences(
                    client_id=prefs.client_id,
                    cursor_x=prefs.cursor_x,
                    cursor_y=prefs.cursor_y,
                    view_mode=prefs.view_mode,
                    overlay_mode=prefs.overlay_mode,
                    iso_mode=prefs.iso_mode,
                    center_panel_mode=prefs.center_panel_mode,
                    left_panel_visible=prefs.left_panel_visible,
                    right_panel_visible=prefs.right_panel_visible,
                    domain=prefs.domain or "",
                )
        except Exception as e:
            logger.debug(f"Cache preferences load failed: {e}")

        return None

    async def save_preferences(self, prefs: UIPreferences) -> bool:
        """Save UI preferences.

        Saves to both Engine (if connected) and Postgres cache.

        Args:
            prefs: Preferences to save

        Returns:
            True if saved successfully
        """
        success = False

        # Try Engine first
        if self.is_connected:
            try:
                from ..engine.generated import SavePreferencesRequest, UIPreferences as ProtoUIPreferences

                # Wrap in UIPreferences proto message
                ui_prefs = ProtoUIPreferences(
                    client_id=prefs.client_id,
                    cursor_x=prefs.cursor_x,
                    cursor_y=prefs.cursor_y,
                    view_mode=prefs.view_mode,
                    overlay_mode=prefs.overlay_mode,
                    iso_mode=prefs.iso_mode,
                    center_panel_mode=prefs.center_panel_mode,
                    left_panel_visible=prefs.left_panel_visible,
                    right_panel_visible=prefs.right_panel_visible,
                    domain=prefs.domain or "",
                )
                request = SavePreferencesRequest(preferences=ui_prefs)
                assert self._stub is not None  # Guaranteed by is_connected check
                await self._stub.SavePreferences(
                    request,
                    timeout=self.request_timeout,
                )
                success = True
            except Exception as e:
                logger.debug(f"Engine preferences save failed: {e}")

        # Also save to Postgres for offline access
        try:
            from ..storage.grid_state import save_ui_preferences, UIPreferences as StorageUIPreferences

            storage_prefs = StorageUIPreferences(
                client_id=prefs.client_id,
                cursor_x=prefs.cursor_x,
                cursor_y=prefs.cursor_y,
                view_mode=prefs.view_mode,
                overlay_mode=prefs.overlay_mode,
                iso_mode=prefs.iso_mode,
                center_panel_mode=prefs.center_panel_mode,
                left_panel_visible=prefs.left_panel_visible,
                right_panel_visible=prefs.right_panel_visible,
                domain=prefs.domain if prefs.domain else None,
            )
            cache_success = await save_ui_preferences(storage_prefs)
            success = success or cache_success
        except Exception as e:
            logger.debug(f"Cache preferences save failed: {e}")

        return success

    async def prune_snapshots(
        self,
        kb_root: str,
        keep_count: Optional[int] = None,
        older_than_days: Optional[int] = None,
        dry_run: bool = False,
    ) -> tuple[int, list[str]]:
        """Prune old grid snapshots.

        Args:
            kb_root: KB root directory
            keep_count: Keep only this many most recent
            older_than_days: Delete older than this many days
            dry_run: Just return what would be deleted

        Returns:
            Tuple of (count, list of snapshot IDs that were/would be deleted)
        """
        if self.is_connected:
            try:
                from ..engine.generated import PruneSnapshotsRequest

                request = PruneSnapshotsRequest(
                    kb_root=kb_root,
                    keep_count=keep_count or 0,
                    older_than_days=older_than_days or 0,
                    dry_run=dry_run,
                )
                assert self._stub is not None  # Guaranteed by is_connected check
                response = await self._stub.PruneSnapshots(
                    request,
                    timeout=self.request_timeout,
                )
                # Note: gRPC response doesn't include deleted_ids, only count
                return response.deleted_count, []
            except Exception as e:
                logger.warning(f"Engine prune failed: {e}")

        # Fall back to direct Postgres
        try:
            from ..storage.grid_state import prune_snapshots

            count, ids = await prune_snapshots(
                kb_root=kb_root,
                keep_count=keep_count,
                older_than_days=older_than_days,
                dry_run=dry_run,
            )
            return count, [str(i) for i in ids]
        except Exception as e:
            logger.warning(f"Cache prune failed: {e}")
            return 0, []


# =============================================================================
# Module-level convenience
# =============================================================================

_state_client: Optional[StateClient] = None


async def get_state_client() -> StateClient:
    """Get or create the state client singleton."""
    global _state_client

    if _state_client is None:
        _state_client = StateClient()

    return _state_client


def reset_state_client() -> None:
    """Reset the state client singleton."""
    global _state_client
    _state_client = None
