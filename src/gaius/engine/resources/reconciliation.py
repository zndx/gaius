"""FSM-based reconciliation for GPU endpoint and infrastructure state management.

This module implements a Kubernetes-style reconciliation loop that:
1. Observes reality (nvidia-smi, ports, health checks, process table)
2. Compares to expected state
3. Detects drift and triggers remediation

Implements BaseDaemon protocol with REQUIRED criticality - engine starts with
ERROR logged if this daemon fails.

The key insight: each endpoint AND infrastructure process is an independent FSM,
and the reconciliation loop drives state transitions based on observations.

Scope:
- GPU inference endpoints (vLLM, optillm)
- Infrastructure processes (kubectl port-forwards, devenv processes)
- Port conflicts from orphaned processes

Design Principles:
- Fail-fast: Surface errors immediately with Guru Meditation codes
- Observable: All state transitions logged with context
- Self-healing: Automatic recovery from common failure modes
- Coexistent: Dynamic ports allow multiple services on same host

Related:
- docs/scratch/2025-12-20/230000_engine_fsm_reconciliation.md
"""

import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING

import httpx

from ..services.base_daemon import (
    BaseDaemon,
    DaemonCriticality,
    DaemonHealth,
)

if TYPE_CHECKING:
    from ..daemon_registry import DaemonRegistry
    from ..services.health_observer_service import HealthObserverService
    from ..services.agenda_tracker import AgendaTracker

logger = logging.getLogger(__name__)


# =============================================================================
# Endpoint State Machine
# =============================================================================


class EndpointState(Enum):
    """State of an inference endpoint in the FSM.

    State transitions:
        ABSENT → ALLOCATED → STARTING → HEALTHY ↔ UNHEALTHY → STOPPING → ABSENT
                                            ↓
                                         ORPHANED (detected via reconciliation)
                                            ↓
                                         ABSENT (after cleanup)

    Special states:
        ORPHANED: Process exists but engine doesn't track it
        CONFLICT: Port in use by different service
        FAILED: Unrecoverable error (wrong model, config issue)
    """

    ABSENT = "absent"  # No process, no GPU allocation
    ALLOCATED = "allocated"  # GPUs reserved, process not started
    STARTING = "starting"  # Process launched, health checks pending
    HEALTHY = "healthy"  # Process running, responding to /health
    UNHEALTHY = "unhealthy"  # Process exists but not responding
    STOPPING = "stopping"  # Graceful shutdown in progress
    ORPHANED = "orphaned"  # Process exists but engine doesn't track it
    CONFLICT = "conflict"  # Port in use by different service
    FAILED = "failed"  # Unrecoverable error


@dataclass
class EndpointObservation:
    """Observations about an endpoint from multiple sources.

    This is the "ground truth" gathered from the system, used to
    determine actual state vs expected state.

    Attributes:
        name: Endpoint name (e.g., "orchestrator", "reasoning")
        timestamp: When observation was made
        expected_state: What the engine thinks the state is
        expected_port: Port the engine expects
        expected_gpus: GPU IDs the engine expects
        expected_model: Model the engine expects

        # From nvidia-smi
        gpu_pids: PIDs using expected GPUs (set)
        gpu_memory_mb: Memory used per GPU {gpu_id: mb}

        # From ss/netstat
        port_pid: PID listening on expected port (None if nothing)
        port_in_use: Whether the port has any listener

        # From /proc
        tracked_pid: PID the engine is tracking
        tracked_pid_alive: Whether that PID exists

        # From HTTP health checks
        health_ok: Whether /health returned 200
        health_latency_ms: Response time
        model_loaded: Model ID from /v1/models (None if not available)
    """

    name: str
    timestamp: datetime = field(default_factory=datetime.now)

    # Expected state (from engine's internal tracking)
    expected_state: EndpointState = EndpointState.ABSENT
    expected_port: Optional[int] = None
    expected_gpus: list[int] = field(default_factory=list)
    expected_model: Optional[str] = None

    # From nvidia-smi
    gpu_pids: set[int] = field(default_factory=set)
    gpu_memory_mb: dict[int, int] = field(default_factory=dict)

    # From port scan
    port_pid: Optional[int] = None
    port_in_use: bool = False

    # From process table
    tracked_pid: Optional[int] = None
    tracked_pid_alive: bool = False

    # From HTTP health
    health_ok: bool = False
    health_latency_ms: int = 0
    model_loaded: Optional[str] = None

    @property
    def has_gpu_memory(self) -> bool:
        """Whether any expected GPU has significant memory usage."""
        return any(mb > 100 for mb in self.gpu_memory_mb.values())

    @property
    def has_orphan_process(self) -> bool:
        """Whether there's a process on port but engine doesn't track it."""
        return self.port_in_use and not self.tracked_pid_alive


# =============================================================================
# Infrastructure Process State Machine
# =============================================================================


class InfraProcessState(Enum):
    """State of an infrastructure process (port-forwards, devenv processes).

    Unlike inference endpoints, infrastructure processes are simpler:
    - They should be managed by process-compose/devenv
    - Orphans have PPID=1 (reparented to init)
    - Conflicts block other processes from binding
    """

    ABSENT = "absent"  # No process
    RUNNING = "running"  # Process running, managed by devenv
    ORPHANED = "orphaned"  # Process running but PPID=1 (orphaned)
    CONFLICT = "conflict"  # Port blocked by unrelated process


@dataclass
class InfraProcessObservation:
    """Observation of an infrastructure process.

    Attributes:
        name: Process identifier (e.g., "metaflow-port-forwards")
        expected_ports: Ports this process should own
        timestamp: When observation was made

        # From ss/netstat - per port
        port_pids: Dict mapping port to PID using it
        port_process_names: Dict mapping port to process name

        # From /proc - process lineage
        pid_ppids: Dict mapping PID to its parent PID
        pid_cmdlines: Dict mapping PID to command line
    """

    name: str
    expected_ports: list[int] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    # Port ownership
    port_pids: dict[int, Optional[int]] = field(default_factory=dict)
    port_process_names: dict[int, str] = field(default_factory=dict)

    # Process lineage
    pid_ppids: dict[int, int] = field(default_factory=dict)
    pid_cmdlines: dict[int, str] = field(default_factory=dict)

    def get_orphan_pids(self) -> list[int]:
        """Get PIDs that are orphaned (PPID=1) on our expected ports."""
        orphans = []
        for port in self.expected_ports:
            pid = self.port_pids.get(port)
            if pid and self.pid_ppids.get(pid) == 1:
                orphans.append(pid)
        return orphans

    def get_conflict_ports(self) -> dict[int, int]:
        """Get ports blocked by processes we don't recognize.

        Returns:
            Dict mapping port to blocking PID
        """
        conflicts = {}
        for port in self.expected_ports:
            pid = self.port_pids.get(port)
            if pid:
                cmdline = self.pid_cmdlines.get(pid, "")
                process_name = self.port_process_names.get(port, "")
                ppid = self.pid_ppids.get(pid, 0)

                # It's NOT a conflict if:
                # 1. It's an orphan (PPID=1) - handled separately
                # 2. Process name matches what we expect
                # 3. It's a kubectl port-forward (legitimate infra)
                # 4. It's tilt (dev environment manager)
                is_orphan = ppid == 1
                is_expected = self.name in cmdline
                is_kubectl_portforward = "kubectl" in process_name and "port-forward" in cmdline
                is_tilt = "tilt" in process_name

                if not is_orphan and not is_expected and not is_kubectl_portforward and not is_tilt:
                    conflicts[port] = pid

        return conflicts


@dataclass
class InfraReconciliationResult:
    """Result of reconciling an infrastructure process."""

    name: str
    state: InfraProcessState
    orphan_pids_killed: list[int] = field(default_factory=list)
    conflict_ports: dict[int, int] = field(default_factory=dict)
    action_taken: Optional[str] = None
    success: bool = True
    message: str = ""


@dataclass
class ReconciliationResult:
    """Result of reconciling an endpoint.

    Attributes:
        endpoint: Endpoint name
        expected_state: What engine thinks
        actual_state: What we observed
        is_drifted: Whether states don't match
        action_taken: What remediation was applied (if any)
        error: Error message if reconciliation failed
    """

    endpoint: str
    expected_state: EndpointState
    actual_state: EndpointState
    is_drifted: bool = False
    action_taken: Optional[str] = None
    error: Optional[str] = None

    @property
    def drift_description(self) -> str:
        """Human-readable drift description."""
        if not self.is_drifted:
            return f"{self.endpoint}: OK ({self.actual_state.value})"
        return (
            f"{self.endpoint}: DRIFT "
            f"(expected={self.expected_state.value}, "
            f"actual={self.actual_state.value})"
        )


# =============================================================================
# Observation Sources
# =============================================================================


async def observe_gpu_processes() -> dict[int, dict[str, Any]]:
    """Query nvidia-smi for GPU process information.

    Returns:
        Dict mapping GPU ID to dict with:
            - pids: set of PIDs using this GPU
            - memory_mb: total memory used on this GPU
            - processes: list of {pid, memory_mb, name}
    """
    try:
        # nvidia-smi query for compute processes
        result = await asyncio.get_event_loop().run_in_executor(
            None, _query_nvidia_smi_processes
        )
        return result
    except Exception as e:
        logger.warning(f"Failed to query nvidia-smi processes: {e}")
        return {}


def _query_nvidia_smi_processes() -> dict[int, dict[str, Any]]:
    """Synchronous nvidia-smi process query."""
    try:
        # Query format: gpu_index, pid, used_memory, process_name
        cmd = [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid,used_memory,process_name",
            "--format=csv,noheader,nounits",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if result.returncode != 0:
            return {}

        # Also get GPU index to UUID mapping
        uuid_cmd = [
            "nvidia-smi",
            "--query-gpu=index,uuid",
            "--format=csv,noheader",
        ]
        uuid_result = subprocess.run(uuid_cmd, capture_output=True, text=True, timeout=5)

        uuid_to_index = {}
        if uuid_result.returncode == 0:
            for line in uuid_result.stdout.strip().split("\n"):
                if "," in line:
                    parts = line.split(",")
                    idx = int(parts[0].strip())
                    uuid = parts[1].strip()
                    uuid_to_index[uuid] = idx

        gpu_info: dict[int, dict[str, Any]] = {}

        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue

            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                continue

            uuid, pid_str, mem_str, name = parts[0], parts[1], parts[2], parts[3]

            try:
                gpu_id = uuid_to_index.get(uuid, -1)
                if gpu_id < 0:
                    continue

                pid = int(pid_str)
                memory_mb = int(mem_str) if mem_str.isdigit() else 0

                if gpu_id not in gpu_info:
                    gpu_info[gpu_id] = {
                        "pids": set(),
                        "memory_mb": 0,
                        "processes": [],
                    }

                gpu_info[gpu_id]["pids"].add(pid)
                gpu_info[gpu_id]["memory_mb"] += memory_mb
                gpu_info[gpu_id]["processes"].append({
                    "pid": pid,
                    "memory_mb": memory_mb,
                    "name": name,
                })

            except (ValueError, IndexError):
                continue

        return gpu_info

    except subprocess.TimeoutExpired:
        logger.warning("nvidia-smi timed out")
        return {}
    except FileNotFoundError:
        logger.warning("nvidia-smi not found")
        return {}
    except Exception as e:
        logger.warning(f"nvidia-smi error: {e}")
        return {}


async def observe_port_listeners(ports: list[int]) -> dict[int, Optional[int]]:
    """Query which PIDs are listening on specified ports.

    Args:
        ports: List of ports to check

    Returns:
        Dict mapping port to PID (None if not listening)
    """
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _query_port_listeners(ports)
        )
        return result
    except Exception as e:
        logger.warning(f"Failed to query port listeners: {e}")
        return {p: None for p in ports}


def _query_port_listeners(ports: list[int]) -> dict[int, Optional[int]]:
    """Synchronous port listener query using ss."""
    result = {p: None for p in ports}

    try:
        # ss -tlnp shows TCP listeners with PIDs
        cmd = ["ss", "-tlnp"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if proc.returncode != 0:
            return result

        for line in proc.stdout.split("\n"):
            for port in ports:
                # Match patterns like ":8080" or "0.0.0.0:8080"
                if f":{port}" in line:
                    # Extract PID from "users:(("name",pid=12345,fd=5))"
                    if "pid=" in line:
                        try:
                            pid_part = line.split("pid=")[1].split(",")[0]
                            result[port] = int(pid_part)
                        except (IndexError, ValueError):
                            pass
                    break

        return result

    except subprocess.TimeoutExpired:
        logger.warning("ss command timed out")
        return result
    except FileNotFoundError:
        logger.warning("ss command not found")
        return result
    except Exception as e:
        logger.warning(f"ss command error: {e}")
        return result


def is_pid_alive(pid: int) -> bool:
    """Check if a process with given PID exists."""
    if pid is None or pid <= 0:
        return False
    try:
        # /proc/<pid>/status exists if process is alive
        with open(f"/proc/{pid}/status", "r") as f:
            return True
    except (FileNotFoundError, PermissionError):
        return False


def get_pid_ppid(pid: int) -> Optional[int]:
    """Get parent PID for a process.

    Args:
        pid: Process ID

    Returns:
        Parent PID, or None if process doesn't exist
    """
    try:
        with open(f"/proc/{pid}/status", "r") as f:
            for line in f:
                if line.startswith("PPid:"):
                    return int(line.split()[1])
    except (FileNotFoundError, PermissionError, ValueError, IndexError):
        pass
    return None


def get_pid_cmdline(pid: int) -> str:
    """Get command line for a process.

    Args:
        pid: Process ID

    Returns:
        Command line string, or empty if not available
    """
    try:
        with open(f"/proc/{pid}/cmdline", "r") as f:
            # cmdline uses null bytes as separators
            return f.read().replace("\x00", " ").strip()
    except (FileNotFoundError, PermissionError):
        return ""


def _query_port_listeners_detailed(ports: list[int]) -> dict[int, dict[str, Any]]:
    """Query port listeners with process details.

    Args:
        ports: List of ports to check

    Returns:
        Dict mapping port to {pid, name, ppid, cmdline}
    """
    result = {p: {} for p in ports}

    try:
        cmd = ["ss", "-tlnp"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if proc.returncode != 0:
            return result

        for line in proc.stdout.split("\n"):
            for port in ports:
                if f":{port}" in line:
                    # Extract PID and name from "users:(("name",pid=12345,fd=5))"
                    if "pid=" in line:
                        try:
                            # Get process name
                            name_match = line.split('(("')[1].split('",')[0] if '(("' in line else ""

                            # Get PID
                            pid_part = line.split("pid=")[1].split(",")[0]
                            pid = int(pid_part)

                            # Get PPID and cmdline from /proc
                            ppid = get_pid_ppid(pid)
                            cmdline = get_pid_cmdline(pid)

                            result[port] = {
                                "pid": pid,
                                "name": name_match,
                                "ppid": ppid,
                                "cmdline": cmdline,
                            }
                        except (IndexError, ValueError):
                            pass
                    break

        return result

    except subprocess.TimeoutExpired:
        logger.warning("ss command timed out")
        return result
    except FileNotFoundError:
        logger.warning("ss command not found")
        return result
    except Exception as e:
        logger.warning(f"ss command error: {e}")
        return result


async def observe_infra_process(
    name: str,
    expected_ports: list[int],
) -> InfraProcessObservation:
    """Observe an infrastructure process's port ownership.

    Args:
        name: Process identifier (e.g., "metaflow-port-forwards")
        expected_ports: Ports this process should own

    Returns:
        InfraProcessObservation with current state
    """
    obs = InfraProcessObservation(name=name, expected_ports=expected_ports)

    try:
        # Query port listeners with details
        port_details = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _query_port_listeners_detailed(expected_ports)
        )

        for port, details in port_details.items():
            if details:
                pid = details.get("pid")
                obs.port_pids[port] = pid
                obs.port_process_names[port] = details.get("name", "")
                if pid:
                    obs.pid_ppids[pid] = details.get("ppid", 0)
                    obs.pid_cmdlines[pid] = details.get("cmdline", "")

    except Exception as e:
        logger.warning(f"Failed to observe infra process {name}: {e}")

    return obs


async def remediate_infra_orphans(
    obs: InfraProcessObservation,
) -> InfraReconciliationResult:
    """Remediate orphaned infrastructure processes.

    Kills processes with PPID=1 that are holding ports we need.

    Args:
        obs: Infrastructure process observation

    Returns:
        InfraReconciliationResult with outcome
    """
    orphan_pids = obs.get_orphan_pids()
    killed = []
    failed = []

    for pid in orphan_pids:
        cmdline = obs.pid_cmdlines.get(pid, "unknown")
        logger.info(
            f"#EN.00000013.ORPHAN_INFRA Killing orphaned process PID {pid}: {cmdline[:80]}"
        )

        if await kill_orphan_process(pid):
            killed.append(pid)
            logger.info(f"Successfully killed orphaned PID {pid}")
        else:
            failed.append(pid)
            logger.warning(f"Failed to kill orphaned PID {pid}")

    if failed:
        return InfraReconciliationResult(
            name=obs.name,
            state=InfraProcessState.ORPHANED,
            orphan_pids_killed=killed,
            action_taken="kill_orphans",
            success=False,
            message=f"Killed {len(killed)} orphans, failed to kill {failed}",
        )

    if killed:
        return InfraReconciliationResult(
            name=obs.name,
            state=InfraProcessState.ABSENT,  # Ports now free
            orphan_pids_killed=killed,
            action_taken="kill_orphans",
            success=True,
            message=f"Killed {len(killed)} orphaned processes, ports now available",
        )

    # No orphans to kill
    conflicts = obs.get_conflict_ports()
    if conflicts:
        return InfraReconciliationResult(
            name=obs.name,
            state=InfraProcessState.CONFLICT,
            conflict_ports=conflicts,
            action_taken="detect_conflict",
            success=False,
            message=f"Ports blocked by non-orphan processes: {conflicts}",
        )

    # Check if any ports are in use at all
    in_use = [p for p, pid in obs.port_pids.items() if pid]
    if in_use:
        return InfraReconciliationResult(
            name=obs.name,
            state=InfraProcessState.RUNNING,
            success=True,
            message=f"Process running normally on ports {in_use}",
        )

    return InfraReconciliationResult(
        name=obs.name,
        state=InfraProcessState.ABSENT,
        success=True,
        message="No process on expected ports",
    )


async def check_endpoint_health(
    port: int,
    timeout_seconds: float = 5.0,
) -> tuple[bool, int, Optional[str]]:
    """Check endpoint health via HTTP.

    Args:
        port: Port to check
        timeout_seconds: Request timeout

    Returns:
        Tuple of (health_ok, latency_ms, model_id)
    """
    start = datetime.now()
    model_id = None

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            # First check /health
            health_resp = await client.get(f"http://localhost:{port}/health")
            health_ok = health_resp.status_code == 200

            latency_ms = int((datetime.now() - start).total_seconds() * 1000)

            # If healthy, get model info
            if health_ok:
                try:
                    models_resp = await client.get(f"http://localhost:{port}/v1/models")
                    if models_resp.status_code == 200:
                        data = models_resp.json()
                        if data.get("data") and len(data["data"]) > 0:
                            model_id = data["data"][0].get("id")
                except Exception:
                    pass  # Model info is optional

            return (health_ok, latency_ms, model_id)

    except httpx.ConnectError:
        return (False, 0, None)
    except httpx.TimeoutException:
        return (False, int(timeout_seconds * 1000), None)
    except Exception as e:
        logger.debug(f"Health check failed for port {port}: {e}")
        return (False, 0, None)


# =============================================================================
# State Reconciliation Logic
# =============================================================================


def reconcile_state(obs: EndpointObservation) -> EndpointState:
    """Determine actual endpoint state from observations.

    This is the core reconciliation logic that compares what we
    observe to what we expect and determines the true state.

    Args:
        obs: Observations gathered from multiple sources

    Returns:
        The actual EndpointState based on observations
    """
    # Case 1: Engine thinks HEALTHY
    if obs.expected_state == EndpointState.HEALTHY:
        # Health check is the ultimate source of truth - if responding, it's healthy
        # (even if PID tracking has issues, the service is actually running)
        if obs.health_ok:
            return EndpointState.HEALTHY

        # Not responding to health checks
        if not obs.tracked_pid_alive:
            # Process died - check if GPU memory is still held
            if obs.has_gpu_memory:
                return EndpointState.ORPHANED
            return EndpointState.ABSENT

        # Process alive but not responding to health checks
        return EndpointState.UNHEALTHY

    # Case 2: Engine thinks ABSENT but something unexpected is happening
    if obs.expected_state == EndpointState.ABSENT:
        # Check for orphaned GPU memory (leaked CUDA contexts)
        if obs.has_gpu_memory and not obs.tracked_pid_alive:
            # GPU memory allocated but no process - this is ORPHANED
            return EndpointState.ORPHANED

        if obs.port_in_use:
            # Check if it's our expected model
            if obs.model_loaded == obs.expected_model:
                # Externally started, adopt it
                return EndpointState.HEALTHY
            else:
                # Wrong service on our port
                return EndpointState.CONFLICT
        # Really absent
        return EndpointState.ABSENT

    # Case 3: Engine thinks STARTING
    if obs.expected_state == EndpointState.STARTING:
        if not obs.tracked_pid_alive:
            return EndpointState.FAILED
        if obs.health_ok:
            return EndpointState.HEALTHY
        # Still starting
        return EndpointState.STARTING

    # Case 4: Engine thinks UNHEALTHY
    if obs.expected_state == EndpointState.UNHEALTHY:
        if not obs.tracked_pid_alive:
            return EndpointState.ABSENT
        if obs.health_ok:
            return EndpointState.HEALTHY
        return EndpointState.UNHEALTHY

    # Case 5: Engine thinks STOPPING
    if obs.expected_state == EndpointState.STOPPING:
        if not obs.tracked_pid_alive and not obs.has_gpu_memory:
            return EndpointState.ABSENT
        return EndpointState.STOPPING

    # Case 6: Engine thinks ALLOCATED (GPUs reserved, not started)
    if obs.expected_state == EndpointState.ALLOCATED:
        # Check if something unexpectedly started
        if obs.port_in_use and obs.health_ok:
            return EndpointState.HEALTHY
        return EndpointState.ALLOCATED

    # Case 7: Already ORPHANED or CONFLICT - check if resolved
    if obs.expected_state == EndpointState.ORPHANED:
        if not obs.has_gpu_memory and not obs.port_in_use:
            return EndpointState.ABSENT
        return EndpointState.ORPHANED

    if obs.expected_state == EndpointState.CONFLICT:
        if not obs.port_in_use:
            return EndpointState.ABSENT
        return EndpointState.CONFLICT

    # Default: trust expected state
    return obs.expected_state


# =============================================================================
# Remediation Actions
# =============================================================================


@dataclass
class RemediationAction:
    """A remediation action to be taken.

    Attributes:
        action_type: Type of action (kill_process, clear_gpu, restart_endpoint, etc.)
        target: What the action targets (endpoint name, PID, GPU ID)
        severity: How severe (info, warning, critical)
        requires_approval: Whether user approval is needed
        description: Human-readable description
    """

    action_type: str
    target: str
    severity: str = "warning"
    requires_approval: bool = False
    description: str = ""


@dataclass
class RemediationResult:
    """Result of a remediation action.

    Attributes:
        action: The action that was taken
        success: Whether it succeeded
        message: Result message
        new_state: The state after remediation
    """

    action: RemediationAction
    success: bool
    message: str
    new_state: Optional[EndpointState] = None


async def kill_orphan_process(pid: int) -> bool:
    """Kill an orphaned process.

    Args:
        pid: Process ID to kill

    Returns:
        True if successfully killed or already dead
    """
    if not is_pid_alive(pid):
        return True  # Already dead

    try:
        import os
        import signal

        os.kill(pid, signal.SIGTERM)
        # Wait briefly for graceful shutdown
        await asyncio.sleep(1.0)

        if is_pid_alive(pid):
            # Force kill
            os.kill(pid, signal.SIGKILL)
            await asyncio.sleep(0.5)

        return not is_pid_alive(pid)

    except ProcessLookupError:
        return True  # Process already gone
    except PermissionError:
        logger.error(f"Permission denied killing PID {pid}")
        return False
    except Exception as e:
        logger.error(f"Failed to kill PID {pid}: {e}")
        return False


async def clear_gpu_memory(gpu_ids: list[int]) -> bool:
    """Attempt to clear GPU memory for specified GPUs.

    This is a best-effort operation. For truly stuck CUDA contexts,
    nvidia-smi --gpu-reset may be required (needs root).

    Args:
        gpu_ids: List of GPU IDs to clear

    Returns:
        True if memory appears to be freed
    """
    try:
        # First, try to find and kill any processes using these GPUs
        gpu_info = await observe_gpu_processes()

        killed_any = False
        for gpu_id in gpu_ids:
            if gpu_id in gpu_info:
                for pid in gpu_info[gpu_id]["pids"]:
                    if await kill_orphan_process(pid):
                        killed_any = True
                        logger.info(f"Killed orphan PID {pid} on GPU {gpu_id}")

        if killed_any:
            # Wait for GPU memory to be freed
            await asyncio.sleep(2.0)

        # Check if memory is now free
        new_gpu_info = await observe_gpu_processes()
        all_clear = True
        for gpu_id in gpu_ids:
            if gpu_id in new_gpu_info and new_gpu_info[gpu_id]["memory_mb"] > 100:
                all_clear = False

        return all_clear

    except Exception as e:
        logger.error(f"Failed to clear GPU memory: {e}")
        return False


async def remediate_orphaned(
    obs: EndpointObservation,
    resource_manager: Any,
) -> RemediationResult:
    """Remediate an ORPHANED endpoint.

    Steps:
    1. Kill any orphan processes on the GPUs
    2. Clear GPU memory
    3. Release allocation in resource manager

    Args:
        obs: Endpoint observation
        resource_manager: ResourceManager instance

    Returns:
        RemediationResult with outcome
    """
    action = RemediationAction(
        action_type="clear_orphaned",
        target=obs.name,
        severity="warning",
        description=f"Clear orphaned GPU memory on {obs.expected_gpus}",
    )

    try:
        # Kill any processes on our GPUs
        pids_killed = []
        for pid in obs.gpu_pids:
            if await kill_orphan_process(pid):
                pids_killed.append(pid)

        # Try to clear GPU memory
        memory_cleared = await clear_gpu_memory(obs.expected_gpus)

        # Release allocation if we have one
        if obs.name in resource_manager.allocations:
            try:
                await resource_manager.release(obs.name)
                logger.info(f"Released allocation for {obs.name}")
            except Exception as e:
                logger.warning(f"Failed to release allocation: {e}")

        if memory_cleared:
            return RemediationResult(
                action=action,
                success=True,
                message=f"Cleared orphaned state: killed PIDs {pids_killed}, freed GPU memory",
                new_state=EndpointState.ABSENT,
            )
        else:
            return RemediationResult(
                action=action,
                success=False,
                message=(
                    f"Killed PIDs {pids_killed} but GPU memory still held. "
                    "May need nvidia-smi --gpu-reset (requires root)."
                ),
                new_state=EndpointState.ORPHANED,
            )

    except Exception as e:
        return RemediationResult(
            action=action,
            success=False,
            message=f"Remediation failed: {e}",
            new_state=EndpointState.ORPHANED,
        )


async def remediate_unhealthy(
    obs: EndpointObservation,
    orchestrator_service: Any,
) -> RemediationResult:
    """Remediate an UNHEALTHY endpoint by restarting it.

    Args:
        obs: Endpoint observation
        orchestrator_service: OrchestratorService instance

    Returns:
        RemediationResult with outcome
    """
    action = RemediationAction(
        action_type="restart_endpoint",
        target=obs.name,
        severity="warning",
        description=f"Restart unhealthy endpoint {obs.name}",
    )

    try:
        # Use orchestrator to restart
        status = await orchestrator_service.restart_endpoint(obs.name)

        if status.status == "healthy":
            return RemediationResult(
                action=action,
                success=True,
                message=f"Restarted {obs.name}, now healthy on port {status.port}",
                new_state=EndpointState.HEALTHY,
            )
        else:
            return RemediationResult(
                action=action,
                success=False,
                message=f"Restart completed but status is {status.status}",
                new_state=EndpointState.UNHEALTHY,
            )

    except Exception as e:
        return RemediationResult(
            action=action,
            success=False,
            message=f"Restart failed: {e}",
            new_state=EndpointState.UNHEALTHY,
        )


async def remediate_conflict(
    obs: EndpointObservation,
) -> RemediationResult:
    """Handle a CONFLICT state (port in use by wrong service).

    This is a warning-only action - we don't automatically kill
    unknown services as they may be intentional.

    Args:
        obs: Endpoint observation

    Returns:
        RemediationResult with warning
    """
    action = RemediationAction(
        action_type="alert_conflict",
        target=obs.name,
        severity="critical",
        requires_approval=True,
        description=f"Port {obs.expected_port} in use by PID {obs.port_pid}",
    )

    return RemediationResult(
        action=action,
        success=False,
        message=(
            f"#EN.00000012.CONFLICT Port {obs.expected_port} is in use by "
            f"PID {obs.port_pid} (not our expected service). "
            f"Manual intervention required: kill PID or reassign port."
        ),
        new_state=EndpointState.CONFLICT,
    )


async def remediate(
    obs: EndpointObservation,
    actual_state: EndpointState,
    desired_state: EndpointState,
    resource_manager: Any,
    orchestrator_service: Optional[Any] = None,
) -> Optional[RemediationResult]:
    """Take remediation action based on drift.

    Args:
        obs: Current observation
        actual_state: What we observed
        desired_state: What we want
        resource_manager: ResourceManager instance
        orchestrator_service: OrchestratorService instance (optional)

    Returns:
        RemediationResult if action was taken, None otherwise
    """
    # ORPHANED: Clean up leaked resources
    if actual_state == EndpointState.ORPHANED:
        logger.info(f"#EN.00000011.ORPHAN Remediating orphaned endpoint {obs.name}")
        return await remediate_orphaned(obs, resource_manager)

    # UNHEALTHY: Restart if we have orchestrator
    if actual_state == EndpointState.UNHEALTHY and orchestrator_service:
        # Skip remediation for endpoints currently evicted by active workloads.
        # The workload's complete_workload() will handle restoration.
        evicted = getattr(orchestrator_service, "_evicted_endpoints", set())
        if obs.name in evicted:
            logger.info(
                f"Skipping remediation for {obs.name}: "
                f"evicted by active workload (will be restored on completion)"
            )
            return None
        # (2026-09-06) Intent ceded to a coordination Activity (a peer's declared
        # run in the Signals Airflow, posture hold-uptime): not chased here
        # either — the coordination watcher restores intent when it ends.
        ceded = getattr(orchestrator_service, "_ceded", {}) or {}
        if obs.name in ceded:
            rec = ceded[obs.name] or {}
            logger.info(
                "Skipping remediation for %s: intent ceded to %s %s (%s) until %s",
                obs.name, rec.get("kind") or "activity", rec.get("activity_id"), rec.get("owner"),
                rec.get("until_ms"),
            )
            return None
        logger.info(f"Remediating unhealthy endpoint {obs.name}")
        return await remediate_unhealthy(obs, orchestrator_service)

    # CONFLICT: Alert only, no automatic action
    if actual_state == EndpointState.CONFLICT:
        return await remediate_conflict(obs)

    # No remediation needed or available
    return None


# =============================================================================
# Reconciliation Service
# =============================================================================


class ReconciliationService(BaseDaemon):
    """Service that runs the reconciliation loop.

    Periodically observes all endpoints and compares to expected state.
    Logs drift and optionally triggers remediation.

    Implements BaseDaemon protocol with REQUIRED criticality - engine starts
    but logs ERROR if this daemon fails. Reconciliation is essential for
    self-healing but the engine can function in degraded mode without it.

    Usage:
        service = ReconciliationService(resource_manager, config)
        await service.start()
        ...
        await service.stop()
    """

    @property
    def name(self) -> str:
        """Unique daemon name."""
        return "reconciliation"

    @property
    def criticality(self) -> DaemonCriticality:
        """REQUIRED - engine starts but logs ERROR if this fails."""
        return DaemonCriticality.REQUIRED

    @property
    def is_running(self) -> bool:
        """Whether the reconciliation loop is running."""
        return self._running

    def __init__(
        self,
        resource_manager: Any,  # ResourceManager from manager.py
        config: Any,  # EngineConfig
        observe_interval_seconds: float = 10.0,
        remediate: bool = True,  # Self-healing enabled by default
        orchestrator_service: Optional[Any] = None,  # For restart remediation
    ):
        """Initialize reconciliation service.

        Args:
            resource_manager: ResourceManager for GPU tracking
            config: Engine configuration
            observe_interval_seconds: How often to observe
            remediate: Whether to take remediation actions (default: True)
            orchestrator_service: OrchestratorService for endpoint restarts
        """
        self._resource_manager = resource_manager
        self._config = config
        self._interval = observe_interval_seconds
        self._remediate = remediate
        self._orchestrator_service = orchestrator_service

        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Latest observations for each endpoint
        self._observations: dict[str, EndpointObservation] = {}

        # Latest reconciliation results
        self._results: dict[str, ReconciliationResult] = {}

        # Remediation history
        self._remediation_results: dict[str, RemediationResult] = {}

        # Infrastructure process tracking
        self._infra_observations: dict[str, InfraProcessObservation] = {}
        self._infra_results: dict[str, InfraReconciliationResult] = {}

        # Infrastructure processes to monitor (name -> expected ports)
        # This can be configured or auto-discovered from process-compose
        self._infra_processes: dict[str, list[int]] = {
            "metaflow-port-forwards": [3000, 8083, 8180],  # Metaflow UI, service, API
        }

        # Drift history for metrics
        self._drift_count = 0
        # Consecutive failed-probe streaks per endpoint (progress doctrine:
        # one flapped probe must never kill a serving model).
        self._unhealthy_streak: dict[str, int] = {}
        # Consecutive healthy observations per endpoint — the FSM momentum
        # axis for efficacy-ledger stamping (a FAIL at momentum 40 is
        # scored in a different bucket than one at momentum 0).
        self._healthy_streak: dict[str, int] = {}
        # Open (unresolved) fail-forecast ids per endpoint, with whether
        # remediation ran — resolved by subsequent green probes
        # (self-recovered-noaction => the forecast was a scored miss) or
        # by a remediated streak (silver true, ambiguity noted).
        self._open_fail_forecasts: dict[str, list[tuple[Any, bool]]] = {}
        self._last_drift_time: Optional[datetime] = None
        self._remediation_count = 0
        self._successful_remediations = 0
        self._infra_orphans_killed = 0

        # HealthObserver integration for escalation
        self._health_observer: Optional["HealthObserverService"] = None

        # AgendaTracker integration for workload-centric incident tracking
        self._agenda_tracker: Optional["AgendaTracker"] = None

        # Track previous endpoint states for transition detection
        self._previous_states: dict[str, EndpointState] = {}

        # Escalation thresholds
        self._high_drift_threshold = 10  # Trigger escalation after 10 unresolved drifts
        self._consecutive_failures = 0
        self._escalation_pending = False

    async def start(self) -> None:
        """Start the reconciliation loop."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"ReconciliationService started (interval={self._interval}s, "
            f"remediate={self._remediate})"
        )

    async def stop(self) -> None:
        """Stop the reconciliation loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ReconciliationService stopped")

    async def health_check(self) -> DaemonHealth:
        """Check reconciliation service health.

        Returns:
            DaemonHealth with status and diagnostics
        """
        if not self._running:
            return DaemonHealth(
                healthy=False,
                message="Reconciliation service not running",
                guru_code="#RC.00000001.NOTRUNNING",
                details={"running": False},
            )

        # Check if reconciliation task is alive
        if self._task is None or self._task.done():
            return DaemonHealth(
                healthy=False,
                message="Reconciliation task crashed",
                guru_code="#RC.00000002.CRASHED",
                details={
                    "running": True,
                    "task_done": self._task.done() if self._task else True,
                },
            )

        # Check for excessive drift (may indicate systemic issues)
        excessive_drift = self._drift_count > 50 and self._successful_remediations < self._drift_count / 2
        if excessive_drift:
            return DaemonHealth(
                healthy=False,
                message=f"High drift with low remediation success ({self._successful_remediations}/{self._drift_count})",
                guru_code="#RC.00000003.HIGHDRIFT",
                details={
                    "running": True,
                    "drift_count": self._drift_count,
                    "remediation_count": self._remediation_count,
                    "successful_remediations": self._successful_remediations,
                },
            )

        return DaemonHealth(
            healthy=True,
            message=f"Reconciliation running ({self._drift_count} drifts, {self._successful_remediations} fixed)",
            details={
                "running": True,
                "interval_seconds": self._interval,
                "remediate_enabled": self._remediate,
                "drift_count": self._drift_count,
                "remediation_count": self._remediation_count,
                "successful_remediations": self._successful_remediations,
                "infra_orphans_killed": self._infra_orphans_killed,
            },
        )

    async def _run_loop(self) -> None:
        """Main reconciliation loop."""
        while self._running:
            try:
                await self._reconcile_all()
            except Exception as e:
                logger.error(f"Reconciliation loop error: {e}")

            await asyncio.sleep(self._interval)

    async def _reconcile_all(self) -> None:
        """Reconcile all endpoints and infrastructure processes."""
        # Phase 1: Infrastructure processes (port conflicts, orphans)
        await self._reconcile_infra_processes()

        # Phase 2: GPU endpoints
        await self._reconcile_endpoints()

    async def _reconcile_infra_processes(self) -> None:
        """Reconcile infrastructure processes (port-forwards, etc).

        This runs FIRST to clear orphaned port-forwards before
        endpoint reconciliation tries to start services.
        """
        for name, expected_ports in self._infra_processes.items():
            try:
                # Observe the process
                obs = await observe_infra_process(name, expected_ports)
                self._infra_observations[name] = obs

                # Check for orphans
                orphan_pids = obs.get_orphan_pids()

                if orphan_pids and self._remediate:
                    # Remediate orphans
                    result = await remediate_infra_orphans(obs)
                    self._infra_results[name] = result

                    if result.success and result.orphan_pids_killed:
                        self._infra_orphans_killed += len(result.orphan_pids_killed)
                        logger.info(
                            f"Infra reconciliation for {name}: {result.message}"
                        )
                    elif not result.success:
                        logger.warning(
                            f"Infra reconciliation failed for {name}: {result.message}"
                        )
                else:
                    # No orphans, just record state
                    conflicts = obs.get_conflict_ports()
                    if conflicts:
                        self._infra_results[name] = InfraReconciliationResult(
                            name=name,
                            state=InfraProcessState.CONFLICT,
                            conflict_ports=conflicts,
                            success=False,
                            message=f"Ports blocked: {conflicts}",
                        )
                    else:
                        in_use = [p for p, pid in obs.port_pids.items() if pid]
                        state = InfraProcessState.RUNNING if in_use else InfraProcessState.ABSENT
                        self._infra_results[name] = InfraReconciliationResult(
                            name=name,
                            state=state,
                            success=True,
                            message=f"Ports {in_use}" if in_use else "No listeners",
                        )

            except Exception as e:
                logger.error(f"Infra reconciliation error for {name}: {e}")

    async def _reconcile_endpoints(self) -> None:
        """Reconcile GPU inference endpoints."""
        # Get expected endpoints from config
        endpoints = self._get_expected_endpoints()

        # Gather all observations in parallel
        observations = await self._observe_all(endpoints)

        # Reconcile each endpoint
        for name, obs in observations.items():
            actual_state = reconcile_state(obs)

            # Progress doctrine: an alive-but-unresponsive probe result is
            # evidence of a BUSY server as often as a wedged one (a truly
            # dead endpoint shows up as ORPHANED/ABSENT via ConnectError +
            # dead PID and still remediates immediately below). One probe
            # must never kill a serving model — 2026-09-01: a 5s probe
            # flapped under TierSettle host load and reconciliation
            # recycled a healthy thinking 27B every cycle, mid-inference.
            # Require sustained failure before declaring drift.
            suppress_remediation = False
            momentum_before = self._healthy_streak.get(name, 0)
            if (
                obs.expected_state == EndpointState.HEALTHY
                and actual_state == EndpointState.UNHEALTHY
            ):
                streak = self._unhealthy_streak.get(name, 0) + 1
                self._unhealthy_streak[name] = streak
                self._healthy_streak[name] = 0
                if streak < 3:
                    logger.warning(
                        f"#EN.00000018.PROBEFLAP {name}: health probe failed "
                        f"({streak}/3 consecutive) — observing, not remediating"
                    )
                    # Suppress remediation ONLY; observation/result
                    # bookkeeping below must continue (an earlier
                    # `continue` here left downstream consumers reading
                    # stale observations during a flap streak).
                    suppress_remediation = True
                # Every probe FAIL on an expected-healthy endpoint is a
                # forecast in the efficacy ledger, stamped with the FSM
                # position (momentum = green streak before this failure).
                await self._ledger_record_endpoint_fail(
                    name,
                    actual_state,
                    momentum=momentum_before,
                    streak=streak,
                    will_remediate=not suppress_remediation,
                )
            else:
                self._unhealthy_streak.pop(name, None)
                if (
                    obs.expected_state == EndpointState.HEALTHY
                    and actual_state == EndpointState.HEALTHY
                ):
                    self._healthy_streak[name] = momentum_before + 1
                    # Two consecutive green probes settle any open fail
                    # forecasts: unremediated ones were scored misses
                    # (self-recovered with no action); remediated ones
                    # resolve silver-true with the ambiguity noted.
                    if self._healthy_streak[name] >= 2:
                        await self._ledger_resolve_open(name)

            is_drifted = actual_state != obs.expected_state

            result = ReconciliationResult(
                endpoint=name,
                expected_state=obs.expected_state,
                actual_state=actual_state,
                is_drifted=is_drifted,
            )

            if is_drifted and not suppress_remediation:
                self._drift_count += 1
                self._last_drift_time = datetime.now()
                logger.warning(
                    f"#EN.00000010.DRIFT {name}: "
                    f"expected={obs.expected_state.value}, "
                    f"actual={actual_state.value}"
                )

                # Phase 2: remediation
                if self._remediate:
                    remediation_result = await remediate(
                        obs=obs,
                        actual_state=actual_state,
                        desired_state=obs.expected_state,
                        resource_manager=self._resource_manager,
                        orchestrator_service=self._orchestrator_service,
                    )

                    if remediation_result:
                        self._remediation_count += 1
                        self._remediation_results[name] = remediation_result
                        result.action_taken = remediation_result.action.action_type

                        if remediation_result.success:
                            self._successful_remediations += 1
                            self._consecutive_failures = 0  # Reset on success
                            logger.info(
                                f"Remediation successful for {name}: "
                                f"{remediation_result.message}"
                            )
                            # Update actual state if remediation changed it
                            if remediation_result.new_state:
                                result.actual_state = remediation_result.new_state
                        else:
                            self._consecutive_failures += 1
                            logger.warning(
                                f"Remediation failed for {name}: "
                                f"{remediation_result.message}"
                            )

                            # Escalate to HealthObserver after threshold
                            if self._consecutive_failures >= self._high_drift_threshold:
                                logger.warning(
                                    f"#RC.00000003.HIGHDRIFT Consecutive failures ({self._consecutive_failures}) "
                                    f"exceed threshold, escalating {name} to HealthObserver"
                                )
                                await self._escalate_to_health_observer(name, result)

            self._observations[name] = obs
            self._results[name] = result

            # Notify AgendaTracker of state transitions
            await self._notify_agenda_tracker(name, obs.expected_state, actual_state)

    async def _ledger_record_endpoint_fail(
        self,
        name: str,
        actual_state: EndpointState,
        momentum: int,
        streak: int,
        will_remediate: bool,
    ) -> None:
        """Record a failed endpoint probe as an efficacy-ledger forecast.

        Non-raising by ledger contract: reconciliation behavior is
        identical with or without a ledger.
        """
        from gaius.engine.fsm import position_for_endpoint
        from gaius.engine.services.efficacy_ledger import get_ledger

        ledger = get_ledger()
        if ledger is None:
            return
        # Polarity convention: affirmative proposition, verdict carries
        # the probe's answer. The probe claims the endpoint is NOT
        # serving → verdict "fail" on "is serving" (p=0.15).
        forecast_id = await ledger.record_forecast(
            observer="probe:reconciliation.endpoint_health",
            observer_kind="probe",
            call_site="reconciliation._reconcile_endpoints",
            proposition=f"endpoint {name} is serving",
            verdict="fail",
            evidence={"streak": streak, "actual_state": actual_state.value},
            side_effect="remediate" if will_remediate else "skip_remediation",
            position=position_for_endpoint(name, actual_state.value, momentum),
        )
        if forecast_id is not None:
            self._open_fail_forecasts.setdefault(name, []).append(
                (forecast_id, will_remediate)
            )

    async def _ledger_resolve_open(self, name: str) -> None:
        """Settle open fail forecasts once the endpoint is green again.

        Unremediated fail → the endpoint recovered with NO action: the
        probe's "not serving" claim was a miss (outcome False). After a
        remediation the claim resolves silver-True but the resolver notes
        the ambiguity — a restart fixing things does not prove the
        endpoint was truly wedged.
        """
        from gaius.engine.services.efficacy_ledger import get_ledger

        ledger = get_ledger()
        open_fails = self._open_fail_forecasts.pop(name, [])
        if ledger is None or not open_fails:
            return
        # Outcomes are on the affirmative proposition "endpoint is
        # serving": self-recovery with no action → it WAS serving
        # (outcome=True — the fail verdict scores as a miss, 0.72);
        # remediation confirmed by recovery → it was NOT serving at
        # claim time (outcome=False — the fail verdict scores well),
        # with the restart ambiguity noted in provenance.
        for forecast_id, remediated in open_fails:
            if remediated:
                await ledger.resolve(
                    forecast_id,
                    outcome=False,
                    tier="silver",
                    resolver="remediated-after-streak:ambiguous",
                    note="healthy only after remediation; wedge plausible, "
                    "restart-fixed-it ambiguity noted",
                )
            else:
                await ledger.resolve(
                    forecast_id,
                    outcome=True,
                    tier="silver",
                    resolver="self-recovered-noaction",
                    note="2 consecutive green probes with no remediation — "
                    "the endpoint was serving all along",
                )

    async def _notify_agenda_tracker(
        self,
        endpoint: str,
        from_state: EndpointState,
        to_state: EndpointState,
    ) -> None:
        """Notify AgendaTracker of endpoint state transitions.

        Compares current state with previous observed state to detect
        actual transitions (not just drift).

        Args:
            endpoint: Endpoint name
            from_state: Expected state (what engine thinks)
            to_state: Actual state (what we observed)
        """
        if not self._agenda_tracker:
            return

        # Get previous observed state
        previous_state = self._previous_states.get(endpoint)

        # Update previous state
        self._previous_states[endpoint] = to_state

        # Only notify if state actually changed
        if previous_state is not None and previous_state != to_state:
            try:
                await self._agenda_tracker.on_endpoint_transition(
                    endpoint=endpoint,
                    from_state=previous_state,
                    to_state=to_state,
                )
            except Exception as e:
                logger.warning(f"Failed to notify AgendaTracker of transition: {e}")

    def _get_expected_endpoints(self) -> dict[str, dict[str, Any]]:
        """Get expected endpoint configurations.

        Returns:
            Dict mapping endpoint name to expected config
        """
        endpoints = {}

        # Get from resource manager's allocations
        for alias, alloc in self._resource_manager.allocations.items():
            endpoints[alias] = {
                "port": alloc.endpoint_port,
                "gpus": list(alloc.gpu_ids),
                "model": alloc.model,
                "state": self._allocation_to_endpoint_state(alloc.state),
                "pid": alloc.process_pid,  # PID tracking for orphan detection
            }

        # Also check config for endpoints that should exist
        if hasattr(self._config, "agents"):
            for alias, agent_config in self._config.agents.items():
                if alias not in endpoints:
                    # Not allocated - expected to be ABSENT
                    endpoints[alias] = {
                        "port": getattr(agent_config, "port", None),
                        "gpus": [],
                        "model": agent_config.model,
                        "state": EndpointState.ABSENT,
                        "pid": None,
                    }

        return endpoints

    def _allocation_to_endpoint_state(self, alloc_state) -> EndpointState:
        """Map AllocationState to EndpointState."""
        from .allocations import AllocationState

        mapping = {
            AllocationState.PENDING: EndpointState.ALLOCATED,
            AllocationState.ALLOCATED: EndpointState.ALLOCATED,
            AllocationState.ACTIVE: EndpointState.HEALTHY,
            AllocationState.RELEASING: EndpointState.STOPPING,
            AllocationState.FAILED: EndpointState.FAILED,
        }
        return mapping.get(alloc_state, EndpointState.ABSENT)

    async def _observe_all(
        self, endpoints: dict[str, dict[str, Any]]
    ) -> dict[str, EndpointObservation]:
        """Gather observations for all endpoints.

        Args:
            endpoints: Expected endpoint configurations

        Returns:
            Dict mapping endpoint name to observations
        """
        # Gather GPU process info
        gpu_info = await observe_gpu_processes()

        # Gather port info
        ports = [e["port"] for e in endpoints.values() if e["port"]]
        port_pids = await observe_port_listeners(ports) if ports else {}

        # Gather health checks in parallel
        health_tasks = {}
        for name, config in endpoints.items():
            if config["port"]:
                # Generous probe (progress doctrine): a truly-down endpoint
                # fails FAST with ConnectError regardless of this value —
                # only a busy-but-alive server rides the timeout, and vLLM's
                # /health lags many seconds under long-prefill load.
                health_tasks[name] = check_endpoint_health(
                    config["port"], timeout_seconds=30.0
                )

        health_results = {}
        if health_tasks:
            results = await asyncio.gather(*health_tasks.values(), return_exceptions=True)
            for name, result in zip(health_tasks.keys(), results):
                if isinstance(result, Exception):
                    health_results[name] = (False, 0, None)
                else:
                    health_results[name] = result

        # Build observations
        observations = {}
        for name, config in endpoints.items():
            obs = EndpointObservation(
                name=name,
                expected_state=config["state"],
                expected_port=config["port"],
                expected_gpus=config["gpus"],
                expected_model=config["model"],
            )

            # Add GPU info
            for gpu_id in config["gpus"]:
                if gpu_id in gpu_info:
                    obs.gpu_pids.update(gpu_info[gpu_id]["pids"])
                    obs.gpu_memory_mb[gpu_id] = gpu_info[gpu_id]["memory_mb"]

            # Add port info
            if config["port"]:
                obs.port_pid = port_pids.get(config["port"])
                obs.port_in_use = obs.port_pid is not None

            # Add process info
            if config["pid"]:
                obs.tracked_pid = config["pid"]
                obs.tracked_pid_alive = is_pid_alive(config["pid"])

            # Add health info
            if name in health_results:
                health_ok, latency, model_id = health_results[name]
                obs.health_ok = health_ok
                obs.health_latency_ms = latency
                obs.model_loaded = model_id

            observations[name] = obs

        return observations

    def get_status(self) -> dict[str, Any]:
        """Get reconciliation status for API.

        Returns:
            Dict with status information
        """
        return {
            "running": self._running,
            "interval_seconds": self._interval,
            "remediate_enabled": self._remediate,
            "drift_count": self._drift_count,
            "remediation_count": self._remediation_count,
            "successful_remediations": self._successful_remediations,
            "infra_orphans_killed": self._infra_orphans_killed,
            "last_drift_time": (
                self._last_drift_time.isoformat() if self._last_drift_time else None
            ),
            "endpoints": {
                name: {
                    "expected": result.expected_state.value,
                    "actual": result.actual_state.value,
                    "drifted": result.is_drifted,
                    "action": result.action_taken,
                }
                for name, result in self._results.items()
            },
            "infrastructure": {
                name: {
                    "state": result.state.value,
                    "success": result.success,
                    "message": result.message,
                    "orphans_killed": result.orphan_pids_killed,
                    "conflicts": result.conflict_ports,
                }
                for name, result in self._infra_results.items()
            },
            "remediations": {
                name: {
                    "action": rem.action.action_type,
                    "success": rem.success,
                    "message": rem.message,
                    "severity": rem.action.severity,
                }
                for name, rem in self._remediation_results.items()
            },
        }

    def set_orchestrator_service(self, orchestrator_service: Any) -> None:
        """Set the orchestrator service for UNHEALTHY remediation.

        Args:
            orchestrator_service: OrchestratorService instance
        """
        self._orchestrator_service = orchestrator_service

    def enable_remediation(self, enable: bool = True) -> None:
        """Enable or disable remediation actions.

        Args:
            enable: Whether to enable remediation
        """
        self._remediate = enable
        logger.info(f"Remediation {'enabled' if enable else 'disabled'}")

    def add_infra_process(self, name: str, ports: list[int]) -> None:
        """Add an infrastructure process to monitor.

        Args:
            name: Process identifier (e.g., "metaflow-port-forwards")
            ports: Ports this process should own
        """
        self._infra_processes[name] = ports
        logger.info(f"Added infra process {name} with ports {ports}")

    def remove_infra_process(self, name: str) -> None:
        """Remove an infrastructure process from monitoring.

        Args:
            name: Process identifier
        """
        if name in self._infra_processes:
            del self._infra_processes[name]
            logger.info(f"Removed infra process {name}")

    def set_health_observer(self, health_observer: "HealthObserverService") -> None:
        """Set reference to HealthObserver for escalation.

        When reconciliation detects persistent issues that it cannot
        remediate, it escalates to HealthObserver for ACP intervention.

        Args:
            health_observer: HealthObserverService instance
        """
        self._health_observer = health_observer
        logger.info("HealthObserver reference set in ReconciliationService")

    def set_agenda_tracker(self, agenda_tracker: "AgendaTracker") -> None:
        """Set reference to AgendaTracker for workload-centric incident tracking.

        When reconciliation detects endpoint state transitions, it notifies
        the AgendaTracker so it can track control mode (positive vs failure/restart).

        Args:
            agenda_tracker: AgendaTracker instance
        """
        self._agenda_tracker = agenda_tracker
        logger.info("AgendaTracker reference set in ReconciliationService")

    async def _escalate_to_health_observer(
        self,
        endpoint: str,
        result: ReconciliationResult,
    ) -> None:
        """Escalate a persistent reconciliation issue to HealthObserver.

        Creates a synthetic incident for HealthObserver to handle via
        the standard FMEA tiered escalation path.

        Args:
            endpoint: Affected endpoint name
            result: The reconciliation result that triggered escalation
        """
        if not self._health_observer:
            logger.warning(
                f"Cannot escalate {endpoint}: HealthObserver not configured.\n"
                "  Guru: #RC.00000004.NOOBSERVER"
            )
            return

        if not self._health_observer.running:
            logger.warning(
                f"Cannot escalate {endpoint}: HealthObserver not running.\n"
                "  Guru: #HO.00000001.NOTRUNNING"
            )
            return

        try:
            # Import HealthIncident
            from ..services.health_observer_service import HealthIncident
            from uuid import uuid4

            # Create synthetic incident for HealthObserver
            fingerprint = f"RC.DRIFT:{endpoint}"

            # Map reconciliation state to FMEA failure mode
            failure_mode_map = {
                EndpointState.ORPHANED: "GPU_ORPHAN",
                EndpointState.UNHEALTHY: "VLLM_UNHEALTHY",
                EndpointState.CONFLICT: "PORT_CONFLICT",
                EndpointState.FAILED: "ENDPOINT_FAILED",
            }
            failure_mode = failure_mode_map.get(result.actual_state, "RECONCILIATION_DRIFT")

            incident = HealthIncident(
                incident_id=uuid4(),
                fingerprint=fingerprint,
                endpoint=endpoint,
                failure_mode_id=failure_mode,
                rpn_score=200,  # High enough for Tier 2 (ACP) escalation
                rpn_severity=8,
                rpn_occurrence=5,
                rpn_detection=5,
                current_tier=2,  # Start at Tier 2 since Tier 0/1 (reconciliation) failed
                attempts=self._consecutive_failures,
            )

            # Register with HealthObserver's active incidents
            # This triggers the escalation flow including potential ACP and GitHub issues
            self._health_observer._active_incidents[fingerprint] = incident
            self._health_observer._incidents_created += 1

            # Trigger callbacks
            for callback in self._health_observer._on_incident:
                try:
                    await callback(incident)
                except Exception as e:
                    logger.warning(f"Incident callback error: {e}")

            # Attempt remediation through HealthObserver's tiered system
            await self._health_observer._attempt_remediation(incident)

            self._escalation_pending = False
            logger.info(
                f"Escalated {endpoint} to HealthObserver: {failure_mode} "
                f"(tier={incident.current_tier}, attempts={incident.attempts})"
            )

        except Exception as e:
            logger.error(
                f"Failed to escalate {endpoint} to HealthObserver: {e}\n"
                "  Guru: #RC.00000005.ESCALATIONFAIL"
            )

    async def check_infra_orphans(self) -> dict[str, InfraReconciliationResult]:
        """One-shot check for infrastructure orphans.

        Useful for pre-flight checks before starting services.

        Returns:
            Dict mapping process name to reconciliation result
        """
        results = {}
        for name, expected_ports in self._infra_processes.items():
            obs = await observe_infra_process(name, expected_ports)
            self._infra_observations[name] = obs

            orphan_pids = obs.get_orphan_pids()
            if orphan_pids:
                logger.warning(
                    f"Found orphaned processes on {name} ports: PIDs {orphan_pids}"
                )
                if self._remediate:
                    result = await remediate_infra_orphans(obs)
                    results[name] = result
                else:
                    results[name] = InfraReconciliationResult(
                        name=name,
                        state=InfraProcessState.ORPHANED,
                        success=False,
                        message=f"Orphans detected but remediation disabled: {orphan_pids}",
                    )
            else:
                conflicts = obs.get_conflict_ports()
                if conflicts:
                    results[name] = InfraReconciliationResult(
                        name=name,
                        state=InfraProcessState.CONFLICT,
                        conflict_ports=conflicts,
                        success=False,
                        message=f"Ports blocked: {conflicts}",
                    )
                else:
                    results[name] = InfraReconciliationResult(
                        name=name,
                        state=InfraProcessState.RUNNING,
                        success=True,
                        message="No orphans or conflicts",
                    )

            self._infra_results[name] = results[name]

        return results

    async def observe_once(self) -> dict[str, ReconciliationResult]:
        """Run a single observation cycle (for pre-flight checks).

        Returns:
            Dict mapping endpoint name to reconciliation result
        """
        endpoints = self._get_expected_endpoints()
        observations = await self._observe_all(endpoints)

        results = {}
        for name, obs in observations.items():
            actual_state = reconcile_state(obs)
            results[name] = ReconciliationResult(
                endpoint=name,
                expected_state=obs.expected_state,
                actual_state=actual_state,
                is_drifted=actual_state != obs.expected_state,
            )
            self._observations[name] = obs
            self._results[name] = results[name]

        return results
