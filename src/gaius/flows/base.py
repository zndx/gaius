"""Base flow class with Gaius lineage integration.

Provides automatic lineage tracking via Apache AGE graph
for all Metaflow steps.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from metaflow import FlowSpec

if TYPE_CHECKING:
    from gaius.hx.lineage.events import Dataset, Job

logger = logging.getLogger(__name__)


def get_current_quarter() -> str:
    """Get current quarter string (e.g., '2024Q4')."""
    now = datetime.now()
    quarter = (now.month - 1) // 3 + 1
    return f"{now.year}Q{quarter}"


def safe_filename(title: str, max_length: int = 50) -> str:
    """Convert title to safe filename."""
    # Remove/replace unsafe characters
    safe = title.lower()
    safe = "".join(c if c.isalnum() or c in " -_" else "" for c in safe)
    safe = safe.replace(" ", "_")
    # Truncate
    if len(safe) > max_length:
        safe = safe[:max_length]
    return safe.strip("_")


def _request_discover_landing_refresh(reason: str) -> None:
    """Ask the engine to refresh Discover's 36h landing concurrently."""
    import grpc

    from gaius.engine.generated import (
        GaiusServiceStub,
        RefreshDiscoverLandingRequest,
    )
    from gaius.flows.lattice import GURU_NOLATTICE, engine_target

    addr = engine_target()
    channel = grpc.insecure_channel(addr)
    try:
        stub = GaiusServiceStub(channel)
        resp = stub.RefreshDiscoverLanding(
            RefreshDiscoverLandingRequest(reason=reason),
            timeout=8.0,
        )
    except grpc.RpcError as e:
        raise RuntimeError(
            f"{GURU_NOLATTICE} RefreshDiscoverLanding failed at {addr}: "
            f"{e.code().name} {e.details()}\n"
            "  Guru: #DI.00000008.REFRESH\n"
            "  Try: /health fix discover"
        ) from e
    finally:
        channel.close()
    if resp.error or not resp.accepted:
        raise RuntimeError(
            f"#DI.00000008.REFRESH RefreshDiscoverLanding rejected: "
            f"{resp.error or 'not accepted'}\n"
            "  Try: /health fix discover"
        )


def _record_lineage_ol(event: object) -> None:
    """Persist a RunEvent on Signals Atlas via Engine/RecordLineage."""
    import json

    import grpc

    from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
    from gaius.engine.generated.zndx.engine.v1 import engine_pb2_grpc as zpb_grpc
    from gaius.flows.lattice import GURU_NOLATTICE, engine_target

    payload = event.to_ol_dict() if hasattr(event, "to_ol_dict") else event.to_dict()
    addr = engine_target()
    channel = grpc.insecure_channel(addr)
    last: grpc.RpcError | None = None
    try:
        stub = zpb_grpc.EngineStub(channel)
        req = zpb.LineageRequest(
            event_json=json.dumps(payload, default=str),
            event_type=str(payload.get("eventType") or ""),
        )
        resp = None
        for attempt in range(3):
            try:
                resp = stub.RecordLineage(req, timeout=45.0)
                break
            except grpc.RpcError as e:
                last = e
                if e.code() != grpc.StatusCode.DEADLINE_EXCEEDED:
                    raise
                time.sleep(0.4 * (attempt + 1))
        if resp is None:
            raise last  # type: ignore[misc]
    except grpc.RpcError as e:
        raise RuntimeError(
            f"{GURU_NOLATTICE} Engine/RecordLineage failed at {addr}: "
            f"{e.code().name} {e.details()}\n"
            "  Lineage SoR is Signals Atlas OpenLineage (/api/v1/lineage)."
        ) from e
    finally:
        channel.close()
    if not resp.accepted:
        raise RuntimeError(
            f"#LN.00000001.NOATLAS RecordLineage rejected: {resp.error}\n"
            "  Lineage SoR is Signals Atlas OpenLineage."
        )


class GaiusFlow(FlowSpec):
    """Base flow with Gaius lineage integration.

    All Gaius flows should inherit from this class to get:
    - Automatic lineage tracking via Apache AGE graph
    - KB path generation helpers
    - Archive path generation helpers
    - Metaflow configuration loading

    Example:
        class MyFlow(GaiusFlow):
            @step
            def start(self):
                self.emit_lineage_start("my_flow", inputs=[...])
                self.next(self.process)

            @step
            def process(self):
                # Do work...
                self.next(self.end)

            @step
            def end(self):
                self.emit_lineage_complete(outputs=[...])
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lineage_run_id: UUID | None = None
        self._lineage_inputs: list[Dataset] = []
        self._lineage_job: Job | None = None
        self._yk_workload_id: str = ""
        self._yk_minted: bool = False

    @property
    def kb_root(self) -> Path:
        """Get KB root directory from environment or default."""
        return Path(os.environ.get("GAIUS_KB_ROOT", "build/dev"))

    def zettelkasten_path(self, title: str, prefix: str = "") -> str:
        """Generate zettelkasten path: scratch/{date}/{HHMMSS}_{title}.md"""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H%M%S")
        filename = f"{time_str}_{prefix}_{safe_filename(title)}.md" if prefix else f"{time_str}_{safe_filename(title)}.md"
        return f"scratch/{date_str}/{filename}"

    def archive_path(self, filename: str, extension: str = "") -> str:
        """Generate archive path: current/archive/{quarter}/attachments/{filename}"""
        quarter = get_current_quarter()
        if extension and not filename.endswith(extension):
            filename = f"{filename}{extension}"
        return f"current/archive/{quarter}/attachments/{filename}"

    def _yk_kind(self) -> str:
        env = (os.environ.get("GAIUS_YK_KIND") or "").strip()
        if env:
            return env.replace("_", "-")
        raw = getattr(self, "yk_kind", None) or getattr(
            type(self), "yk_kind", None
        )
        if raw:
            return str(raw).replace("_", "-")
        return "metaflow"

    def _claim_yk(self) -> None:
        """Admit this Metaflow run as a YK Application via Signals sentinels."""
        from gaius.engine.sentinel_claim import apply_and_admit

        kind = self._yk_kind()
        env_wid = (os.environ.get("GAIUS_YK_APPLICATION_ID") or "").strip()
        if env_wid:
            self._yk_workload_id = env_wid
            self._yk_minted = False
            apply_and_admit(env_wid, kind)
            return
        rid = str(self._lineage_run_id or "").replace("-", "")[:12] or "local"
        wid = f"gaius-mf-{kind}-{rid}".lower()
        wid = "".join(c if c.isalnum() or c == "-" else "-" for c in wid)[:63]
        self._yk_workload_id = wid
        self._yk_minted = True
        apply_and_admit(wid, kind)
        os.environ["GAIUS_YK_APPLICATION_ID"] = wid

    def _release_yk(self) -> None:
        if not self._yk_minted or not self._yk_workload_id:
            return
        from gaius.engine.sentinel_claim import delete_flow_sentinel

        delete_flow_sentinel(self._yk_workload_id)
        self._yk_minted = False

    def emit_lineage_start(
        self,
        job_name: str,
        inputs: list[Dataset],
        job_namespace: str = "gaius.flows",
    ) -> None:
        """Emit START lineage event.

        Call this at the beginning of your flow to track inputs.

        Args:
            job_name: Name of the job (e.g., "arxiv_docling")
            inputs: List of input datasets
            job_namespace: Job namespace (default: "gaius.flows")
        """
        try:
            from gaius.hx.lineage.events import Job, Run, RunEvent

            self._lineage_job = Job(namespace=job_namespace, name=job_name)
            self._lineage_inputs = inputs

            run = Run()
            self._lineage_run_id = run.run_id

            event = RunEvent.start(self._lineage_job, inputs, run)
            _record_lineage_ol(event)
            logger.info(f"Lineage START recorded at Signals Atlas (run_id={run.run_id})")

        except Exception as e:
            # FAIL-FAST: Lineage tracking is critical infrastructure
            error_msg = (
                f"Lineage emission failed: {e}\n"
                f"  Guru Meditation: #GF.00000001.LINEAGE\n"
                f"  Fix: just restart-clean\n"
                f"  Or: PGPASSWORD=gaius psql -h localhost -p {os.environ.get('PGPORT', '5444')} -U gaius -d zndx_gaius"
            )
            raise RuntimeError(error_msg) from e
        self._claim_yk()

    def emit_lineage_complete(self, outputs: list[Dataset]) -> None:
        """Emit COMPLETE lineage event.

        Call this at the end of your flow to track outputs.

        Args:
            outputs: List of output datasets
        """
        if self._lineage_run_id is None or self._lineage_job is None:
            logger.warning("Cannot emit COMPLETE: no START event recorded")
            _request_discover_landing_refresh("complete-no-start")
            return

        try:
            from gaius.hx.lineage.events import Run, RunEvent

            run = Run(run_id=self._lineage_run_id)
            event = RunEvent.complete(
                run, self._lineage_job, self._lineage_inputs, outputs
            )
            _record_lineage_ol(event)
            logger.info(
                f"Lineage COMPLETE recorded at Signals Atlas "
                f"(run_id={self._lineage_run_id})"
            )
            self._release_yk()

        except Exception as e:
            # FAIL-FAST: Lineage tracking is critical infrastructure
            error_msg = (
                f"Lineage emission failed: {e}\n"
                f"  Guru Meditation: #GF.00000002.LINEAGE_COMPLETE\n"
                f"  Fix: just restart-clean\n"
                f"  Or: PGPASSWORD=gaius psql -h localhost -p {os.environ.get('PGPORT', '5444')} -U gaius -d zndx_gaius"
            )
            raise RuntimeError(error_msg) from e
        _request_discover_landing_refresh(
            f"complete:{self._lineage_job.name if self._lineage_job else ''}"
        )

    def emit_lineage_fail(self, error_message: str) -> None:
        """Emit FAIL lineage event.

        Call this when your flow encounters an error.

        Args:
            error_message: Description of the error
        """
        if self._lineage_run_id is None or self._lineage_job is None:
            logger.warning("Cannot emit FAIL: no START event recorded")
            _request_discover_landing_refresh("fail-no-start")
            return

        try:
            from gaius.hx.lineage.events import Run, RunEvent

            run = Run(run_id=self._lineage_run_id)
            event = RunEvent.fail(
                run, self._lineage_job, self._lineage_inputs, error_message
            )
            _record_lineage_ol(event)
            logger.info(
                f"Lineage FAIL recorded at Signals Atlas "
                f"(run_id={self._lineage_run_id})"
            )
            self._release_yk()

        except Exception as e:
            # FAIL-FAST: Lineage tracking is critical infrastructure
            error_msg = (
                f"Lineage emission failed: {e}\n"
                f"  Guru Meditation: #GF.00000003.LINEAGE_FAIL\n"
                f"  Fix: just restart-clean\n"
                f"  Or: PGPASSWORD=gaius psql -h localhost -p {os.environ.get('PGPORT', '5444')} -U gaius -d zndx_gaius"
            )
            raise RuntimeError(error_msg) from e
        _request_discover_landing_refresh(
            f"fail:{self._lineage_job.name if self._lineage_job else ''}"
        )
