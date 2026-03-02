"""Base flow class with Gaius lineage integration.

Provides automatic lineage tracking via Apache AGE graph
for all Metaflow steps.
"""

from __future__ import annotations

import asyncio
import logging
import os
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
            from gaius.hx.lineage.emitter import get_emitter
            from gaius.hx.lineage.events import Job, Run, RunEvent

            self._lineage_job = Job(namespace=job_namespace, name=job_name)
            self._lineage_inputs = inputs

            run = Run()
            self._lineage_run_id = run.run_id

            event = RunEvent.start(self._lineage_job, inputs, run)

            # Run async emit in sync context
            asyncio.get_event_loop().run_until_complete(
                get_emitter().emit(event)
            )
            logger.info(f"Lineage START emitted for {job_name} (run_id={run.run_id})")

        except Exception as e:
            # FAIL-FAST: Lineage tracking is critical infrastructure
            error_msg = (
                f"Lineage emission failed: {e}\n"
                f"  Guru Meditation: #GF.00000001.LINEAGE\n"
                f"  Fix: just restart-clean\n"
                f"  Or: PGPASSWORD=gaius psql -h localhost -p {os.environ.get('PGPORT', '5444')} -U gaius -d zndx_gaius"
            )
            raise RuntimeError(error_msg) from e

    def emit_lineage_complete(self, outputs: list[Dataset]) -> None:
        """Emit COMPLETE lineage event.

        Call this at the end of your flow to track outputs.

        Args:
            outputs: List of output datasets
        """
        if self._lineage_run_id is None or self._lineage_job is None:
            logger.warning("Cannot emit COMPLETE: no START event recorded")
            return

        try:
            from gaius.hx.lineage.emitter import get_emitter
            from gaius.hx.lineage.events import Run, RunEvent

            run = Run(run_id=self._lineage_run_id)
            event = RunEvent.complete(
                run, self._lineage_job, self._lineage_inputs, outputs
            )

            asyncio.get_event_loop().run_until_complete(
                get_emitter().emit(event)
            )
            logger.info(
                f"Lineage COMPLETE emitted for {self._lineage_job.name} "
                f"(run_id={self._lineage_run_id})"
            )

        except Exception as e:
            # FAIL-FAST: Lineage tracking is critical infrastructure
            error_msg = (
                f"Lineage emission failed: {e}\n"
                f"  Guru Meditation: #GF.00000002.LINEAGE_COMPLETE\n"
                f"  Fix: just restart-clean\n"
                f"  Or: PGPASSWORD=gaius psql -h localhost -p {os.environ.get('PGPORT', '5444')} -U gaius -d zndx_gaius"
            )
            raise RuntimeError(error_msg) from e

    def emit_lineage_fail(self, error_message: str) -> None:
        """Emit FAIL lineage event.

        Call this when your flow encounters an error.

        Args:
            error_message: Description of the error
        """
        if self._lineage_run_id is None or self._lineage_job is None:
            logger.warning("Cannot emit FAIL: no START event recorded")
            return

        try:
            from gaius.hx.lineage.emitter import get_emitter
            from gaius.hx.lineage.events import Run, RunEvent

            run = Run(run_id=self._lineage_run_id)
            event = RunEvent.fail(
                run, self._lineage_job, self._lineage_inputs, error_message
            )

            asyncio.get_event_loop().run_until_complete(
                get_emitter().emit(event)
            )
            logger.info(
                f"Lineage FAIL emitted for {self._lineage_job.name} "
                f"(run_id={self._lineage_run_id})"
            )

        except Exception as e:
            # FAIL-FAST: Lineage tracking is critical infrastructure
            error_msg = (
                f"Lineage emission failed: {e}\n"
                f"  Guru Meditation: #GF.00000003.LINEAGE_FAIL\n"
                f"  Fix: just restart-clean\n"
                f"  Or: PGPASSWORD=gaius psql -h localhost -p {os.environ.get('PGPORT', '5444')} -U gaius -d zndx_gaius"
            )
            raise RuntimeError(error_msg) from e
