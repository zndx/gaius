"""NiFi State Manager - Oracle for state capture and comparison.

This module provides the NiFiStateManager class which serves as the "oracle"
for BDD-grounded evaluation. It captures the current state of NiFi flows,
compares states semantically, and manages ground truth for browser agent
evaluation.

Guru Meditation Codes:
    #NF.00000002.STATECAPTURE - Failed to capture process group state
    #NF.00000003.STATEAPPLY - Failed to apply target state
    #NF.00000004.CLEARFAILED - Failed to clear process group

Example:
    async with NiFiStateManager(config) as mgr:
        # Capture ground truth after API creates flow
        expected = await mgr.capture_state(process_group_id)

        # Browser agent makes changes...

        # Capture and compare
        actual = await mgr.capture_state(process_group_id)
        diff = mgr.compare_states(expected, actual)
        print(f"Match: {diff.is_match}, Accuracy: {diff.accuracy:.1%}")
"""

import logging
from typing import Any, Optional

from ..config import NiFiConfig
from .client import NiFiClient
from .models import (
    ConnectionMismatch,
    ConnectionState,
    FlowState,
    ProcessorMismatch,
    ProcessorState,
    SemanticDiff,
)

logger = logging.getLogger(__name__)


class NiFiStateManagerError(Exception):
    """Base exception for NiFiStateManager errors."""

    pass


class StateCaptureError(NiFiStateManagerError):
    """Failed to capture process group state.

    Guru Meditation: #NF.00000002.STATECAPTURE
    """

    def __init__(self, process_group_id: str, reason: str):
        self.process_group_id = process_group_id
        self.reason = reason
        super().__init__(
            f"State capture failed for process group {process_group_id}.\n"
            f"  Reason: {reason}\n"
            f"  Guru Meditation: #NF.00000002.STATECAPTURE\n"
            f"  Try: /health fix nifi"
        )


class StateApplyError(NiFiStateManagerError):
    """Failed to apply target state.

    Guru Meditation: #NF.00000003.STATEAPPLY
    """

    def __init__(self, process_group_id: str, reason: str):
        self.process_group_id = process_group_id
        self.reason = reason
        super().__init__(
            f"State apply failed for process group {process_group_id}.\n"
            f"  Reason: {reason}\n"
            f"  Guru Meditation: #NF.00000003.STATEAPPLY\n"
            f"  Try: /health fix nifi"
        )


class ClearProcessGroupError(NiFiStateManagerError):
    """Failed to clear process group.

    Guru Meditation: #NF.00000004.CLEARFAILED
    """

    def __init__(self, process_group_id: str, reason: str):
        self.process_group_id = process_group_id
        self.reason = reason
        super().__init__(
            f"Clear process group failed for {process_group_id}.\n"
            f"  Reason: {reason}\n"
            f"  Guru Meditation: #NF.00000004.CLEARFAILED\n"
            f"  Try: /health fix nifi"
        )


class NiFiStateManager:
    """Oracle for NiFi state capture, comparison, and ground truth management.

    This is the central component for BDD-grounded evaluation:
    - capture_state(): Snapshot current flow state as ground truth
    - compare_states(): Semantic comparison of expected vs actual
    - clear_process_group(): Reset flow for clean test slate
    - apply_state(): Recreate flow from saved state (future)

    Key Design Principle:
        Semantic comparison by NAME/TYPE, not by position or ID.
        This allows browser-created flows to match API-created flows
        even when layout differs.
    """

    def __init__(self, config: Optional[NiFiConfig] = None):
        """Initialize state manager.

        Args:
            config: NiFi configuration. If None, uses defaults from environment.
        """
        self.config = config or NiFiConfig()
        self._client: Optional[NiFiClient] = None

    async def connect(self) -> bool:
        """Initialize NiFi client connection."""
        self._client = NiFiClient(self.config)
        return await self._client.connect()

    async def close(self) -> None:
        """Close NiFi client connection."""
        if self._client:
            await self._client.close()
            self._client = None

    async def __aenter__(self) -> "NiFiStateManager":
        await self.connect()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    @property
    def client(self) -> NiFiClient:
        """Get the underlying NiFi client."""
        if not self._client:
            raise RuntimeError("NiFiStateManager not connected. Use 'async with'.")
        return self._client

    # =========================================================================
    # State Capture
    # =========================================================================

    async def get_root_process_group_id(self) -> str:
        """Get the ID of the root process group."""
        try:
            root = await self.client.get_root_process_group()
            return root["processGroupFlow"]["id"]
        except Exception as e:
            raise StateCaptureError("root", f"Failed to get root: {e}")

    async def capture_state(
        self,
        process_group_id: str,
        recursive: bool = True,
    ) -> FlowState:
        """Capture the current state of a process group.

        This creates a snapshot of all processors, connections, and
        optionally child groups. Used as ground truth for BDD evaluation.

        Args:
            process_group_id: ID of the process group to capture
            recursive: If True, also capture child process groups

        Returns:
            FlowState containing full state snapshot

        Raises:
            StateCaptureError: If capture fails
        """
        try:
            # Get process group contents
            contents = await self.client.get_process_group_contents(process_group_id)
            pg_flow = contents.get("processGroupFlow", {})
            flow = pg_flow.get("flow", {})

            # Build processor name lookup for connection resolution
            processor_names: dict[str, str] = {}
            processors: list[ProcessorState] = []

            for proc_entity in flow.get("processors", []):
                comp = proc_entity.get("component", {})
                proc_id = comp.get("id", "")
                proc_name = comp.get("name", "")
                processor_names[proc_id] = proc_name

                processors.append(
                    ProcessorState(
                        id=proc_id,
                        name=proc_name,
                        type=comp.get("type", ""),
                        state=proc_entity.get("status", {})
                        .get("runStatus", "STOPPED"),
                        properties=comp.get("config", {}).get("properties", {}),
                        relationships=self._extract_relationships(comp),
                    )
                )

            # Capture connections with resolved names
            connections: list[ConnectionState] = []
            for conn_entity in flow.get("connections", []):
                comp = conn_entity.get("component", {})
                source_id = comp.get("source", {}).get("id", "")
                dest_id = comp.get("destination", {}).get("id", "")

                connections.append(
                    ConnectionState(
                        id=comp.get("id", ""),
                        name=comp.get("name", ""),
                        source_id=source_id,
                        source_name=processor_names.get(source_id, source_id),
                        destination_id=dest_id,
                        destination_name=processor_names.get(dest_id, dest_id),
                        selected_relationships=comp.get("selectedRelationships", []),
                    )
                )

            # Recursively capture child groups
            child_groups: list[FlowState] = []
            if recursive:
                for pg_entity in flow.get("processGroups", []):
                    child_id = pg_entity.get("id", "")
                    if child_id:
                        child_state = await self.capture_state(child_id, recursive=True)
                        child_groups.append(child_state)

            return FlowState(
                process_group_id=process_group_id,
                process_group_name=pg_flow.get("breadcrumb", {})
                .get("breadcrumb", {})
                .get("name", ""),
                processors=processors,
                connections=connections,
                child_groups=child_groups,
            )

        except StateCaptureError:
            raise
        except Exception as e:
            raise StateCaptureError(process_group_id, str(e))

    def _extract_relationships(self, processor_component: dict) -> list[str]:
        """Extract available relationships from processor component."""
        relationships = processor_component.get("relationships", [])
        return [r.get("name", "") for r in relationships if r.get("name")]

    # =========================================================================
    # State Comparison
    # =========================================================================

    def compare_states(
        self,
        expected: FlowState,
        actual: FlowState,
    ) -> SemanticDiff:
        """Compare expected and actual states semantically.

        Comparison is done by NAME, not by position or ID:
        - Processors matched by name
        - Connections matched by source_name->dest_name[relationships]

        This allows browser-created flows to match API-created flows
        even when canvas positions differ.

        Args:
            expected: Ground truth state (typically from API)
            actual: State to verify (typically from browser agent)

        Returns:
            SemanticDiff with detailed comparison results
        """
        diff = SemanticDiff()

        # Compare processors by name
        expected_procs = {p.semantic_key(): p for p in expected.processors}
        actual_procs = {p.semantic_key(): p for p in actual.processors}

        # Find missing and extra processors
        diff.missing_processors = list(
            set(expected_procs.keys()) - set(actual_procs.keys())
        )
        diff.extra_processors = list(
            set(actual_procs.keys()) - set(expected_procs.keys())
        )

        # Compare matching processors for type/property differences
        for name in set(expected_procs.keys()) & set(actual_procs.keys()):
            exp_proc = expected_procs[name]
            act_proc = actual_procs[name]
            mismatch = self._compare_processors(exp_proc, act_proc)
            if mismatch:
                diff.processor_mismatches.append(mismatch)

        # Compare connections by semantic key
        expected_conns = {c.semantic_key(): c for c in expected.connections}
        actual_conns = {c.semantic_key(): c for c in actual.connections}

        diff.missing_connections = list(
            set(expected_conns.keys()) - set(actual_conns.keys())
        )
        diff.extra_connections = list(
            set(actual_conns.keys()) - set(expected_conns.keys())
        )

        # Compare matching connections
        for key in set(expected_conns.keys()) & set(actual_conns.keys()):
            exp_conn = expected_conns[key]
            act_conn = actual_conns[key]
            mismatch = self._compare_connections(exp_conn, act_conn)
            if mismatch:
                diff.connection_mismatches.append(mismatch)

        # Recursively compare child groups by name
        expected_groups = {g.process_group_name: g for g in expected.child_groups}
        actual_groups = {g.process_group_name: g for g in actual.child_groups}

        for name in set(expected_groups.keys()) | set(actual_groups.keys()):
            if name in expected_groups and name in actual_groups:
                child_diff = self.compare_states(
                    expected_groups[name], actual_groups[name]
                )
                if not child_diff.is_match:
                    diff.child_group_diffs[name] = child_diff
            elif name in expected_groups:
                # Missing child group - create diff showing all missing
                empty = FlowState(
                    process_group_id="",
                    process_group_name=name,
                )
                diff.child_group_diffs[name] = self.compare_states(
                    expected_groups[name], empty
                )
            else:
                # Extra child group - create diff showing all extra
                empty = FlowState(
                    process_group_id="",
                    process_group_name=name,
                )
                diff.child_group_diffs[name] = self.compare_states(
                    empty, actual_groups[name]
                )

        return diff

    def _compare_processors(
        self,
        expected: ProcessorState,
        actual: ProcessorState,
    ) -> Optional[ProcessorMismatch]:
        """Compare two processors for type/property differences."""
        has_diff = False
        mismatch = ProcessorMismatch(name=expected.name)

        # Compare types
        if expected.type != actual.type:
            mismatch.expected_type = expected.type
            mismatch.actual_type = actual.type
            has_diff = True

        # Compare states
        if expected.state != actual.state:
            mismatch.state_diff = (expected.state, actual.state)
            has_diff = True

        # Compare properties (only significant ones)
        for key, exp_val in expected.properties.items():
            act_val = actual.properties.get(key)
            if exp_val != act_val and exp_val is not None:
                mismatch.property_diffs[key] = (exp_val, act_val)
                has_diff = True

        return mismatch if has_diff else None

    def _compare_connections(
        self,
        expected: ConnectionState,
        actual: ConnectionState,
    ) -> Optional[ConnectionMismatch]:
        """Compare two connections for relationship differences."""
        exp_rels = set(expected.selected_relationships)
        act_rels = set(actual.selected_relationships)

        if exp_rels != act_rels:
            return ConnectionMismatch(
                semantic_key=expected.semantic_key(),
                expected_relationships=sorted(exp_rels),
                actual_relationships=sorted(act_rels),
            )
        return None

    # =========================================================================
    # Clear Process Group
    # =========================================================================

    async def clear_process_group(
        self,
        process_group_id: str,
        recursive: bool = True,
    ) -> None:
        """Clear all contents of a process group.

        Order of operations:
        1. Stop all running processors
        2. Drop all connection queues
        3. Delete all connections
        4. Delete all processors
        5. Recursively clear/delete child groups (if recursive=True)

        Args:
            process_group_id: ID of the process group to clear
            recursive: If True, also clear child process groups

        Raises:
            ClearProcessGroupError: If clearing fails
        """
        try:
            # Get current contents
            contents = await self.client.get_process_group_contents(process_group_id)
            flow = contents.get("processGroupFlow", {}).get("flow", {})

            # 1. Stop all running processors
            for proc_entity in flow.get("processors", []):
                proc_id = proc_entity.get("id", "")
                status = proc_entity.get("status", {}).get("runStatus", "STOPPED")
                revision = proc_entity.get("revision", {}).get("version", 0)

                if status == "RUNNING":
                    logger.debug(f"Stopping processor {proc_id}")
                    await self.client.stop_processor(proc_id, revision)
                    # Refresh revision after state change
                    proc = await self.client.get_processor(proc_id)
                    revision = proc.get("revision", {}).get("version", 0)

            # 2. Drop all connection queues
            for conn_entity in flow.get("connections", []):
                conn_id = conn_entity.get("id", "")
                queue_size = (
                    conn_entity.get("status", {})
                    .get("aggregateSnapshot", {})
                    .get("flowFilesQueued", 0)
                )
                if queue_size > 0:
                    logger.debug(f"Dropping queue for connection {conn_id}")
                    await self.client.drop_connection_queue(conn_id)

            # 3. Delete all connections
            for conn_entity in flow.get("connections", []):
                conn_id = conn_entity.get("id", "")
                # Refresh to get latest version
                conn = await self.client.get_connection(conn_id)
                revision = conn.get("revision", {}).get("version", 0)
                logger.debug(f"Deleting connection {conn_id}")
                await self.client.delete_connection(conn_id, revision)

            # 4. Delete all processors
            for proc_entity in flow.get("processors", []):
                proc_id = proc_entity.get("id", "")
                # Refresh to get latest version
                proc = await self.client.get_processor(proc_id)
                revision = proc.get("revision", {}).get("version", 0)
                logger.debug(f"Deleting processor {proc_id}")
                await self.client.delete_processor(proc_id, revision)

            # 5. Recursively clear/delete child groups
            if recursive:
                for pg_entity in flow.get("processGroups", []):
                    child_id = pg_entity.get("id", "")
                    if child_id:
                        # First clear the child
                        await self.clear_process_group(child_id, recursive=True)
                        # Then delete the empty group
                        pg = await self.client.get_process_group(child_id)
                        revision = pg.get("revision", {}).get("version", 0)
                        logger.debug(f"Deleting process group {child_id}")
                        await self.client.delete_process_group(child_id, revision)

        except ClearProcessGroupError:
            raise
        except Exception as e:
            raise ClearProcessGroupError(process_group_id, str(e))

    # =========================================================================
    # State Application (Future)
    # =========================================================================

    async def apply_state(
        self,
        process_group_id: str,
        target_state: FlowState,
    ) -> None:
        """Apply a target state to a process group.

        This recreates the flow from a saved FlowState snapshot.
        Typically used to reset to a known good state for testing.

        Note: This is a future feature. Current implementation raises
        NotImplementedError.

        Args:
            process_group_id: ID of the process group to apply to
            target_state: The state to recreate

        Raises:
            StateApplyError: If application fails
        """
        # TODO: Implement state application
        # 1. Clear the process group
        # 2. Create processors from target_state
        # 3. Create connections from target_state
        # 4. Recursively apply child groups
        raise NotImplementedError(
            "State application is not yet implemented.\n"
            "  Guru Meditation: #NF.00000003.STATEAPPLY\n"
            "  Use clear_process_group() and manually recreate flow."
        )
