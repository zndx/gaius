"""ThetaAgent service for engine daemon mode.

Wraps the ThetaAgent with Engine-First gRPC integration following
the BaseDaemon protocol. ThetaAgent provides neuromorphic situational
awareness grounded in Attention Schema Theory (AST).

Phase 1 Services (gRPC):
- sitrep(): Generate situational awareness report
- run_consolidation(): NVAR-mediated temporal consolidation
- get_consolidation_stats(): Consolidation statistics

Architecture:
    MCP Tool → gRPC Servicer → ThetaService → ThetaAgent
                     ↓
              GaiusEngine._theta_service

The ThetaAgent is lazily initialized to avoid startup overhead when
theta operations aren't used. NORMAL criticality - engine continues
if this daemon fails (unlike CRITICAL daemons like CognitionService).

Guru Meditation Codes:
- #THETA.00000001.DEEPONTO - DeepOnto/owlready2 not available
- #THETA.00000002.STARTFAIL - ThetaService failed to start
- #THETA.00000003.INITFAIL - ThetaAgent initialization failed
- #THETA.00000004.SITREPFAIL - SITREP generation failed
- #THETA.00000005.ONTOLOGY_INVALID - OWL failed validation
- #THETA.00000012.THINCABI - thinc/numpy ABI mismatch
- #THETA.00000013.CONSFAIL - Consolidation cycle failed
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .base_daemon import (
    BaseDaemon,
    DaemonCriticality,
    DaemonHealth,
    DaemonStartupError,
)

logger = logging.getLogger(__name__)


@dataclass
class ThetaConfig:
    """Configuration for ThetaAgent service.

    Controls KB root, research mode, and consolidation parameters.
    """

    # Knowledge base root directory
    kb_root: str = "build/dev"

    # Research mode bypasses KG cost threshold (for theory development)
    research_mode: bool = True

    # Consolidation parameters
    default_max_candidates: int = 10

    # Profile for multi-tenant scenarios
    profile: str = "default"


class ThetaService(BaseDaemon):
    """ThetaAgent service for engine daemon mode.

    Wraps existing ThetaAgent with proper gRPC integration following
    the Engine-First architecture. Lazy initialization avoids startup
    overhead when theta operations aren't used.

    Lifecycle:
    1. Service created with config during engine startup
    2. ThetaAgent initialized lazily on first use
    3. gRPC methods delegate to ThetaAgent methods
    4. Service stopped during engine shutdown

    Guru Meditation Codes:
    - #THETA.00000001.DEEPONTO - DeepOnto not available for BERTSubs
    - #THETA.00000002.STARTFAIL - Service failed to start
    - #THETA.00000003.INITFAIL - ThetaAgent failed to initialize
    """

    # =========================================================================
    # BaseDaemon Protocol Implementation
    # =========================================================================

    @property
    def name(self) -> str:
        """Unique daemon name."""
        return "theta"

    @property
    def criticality(self) -> DaemonCriticality:
        """NORMAL - engine continues if this fails."""
        return DaemonCriticality.NORMAL

    @property
    def is_running(self) -> bool:
        """Whether the service is currently running."""
        return self._running

    def __init__(
        self,
        config: ThetaConfig,
        db_pool: Optional[Any] = None,
    ):
        """Initialize ThetaService.

        Args:
            config: Service configuration
            db_pool: Optional database connection pool (asyncpg)
        """
        self.config = config
        self._db_pool = db_pool

        # Daemon state
        self._running = False
        self._started_at: Optional[datetime] = None

        # ThetaAgent is lazily initialized (sitrep). Consolidation runs in
        # theta_worker (light-leaf GPU + JVM), not on the engine event loop.
        self._agent: Optional[Any] = None  # Type: ThetaAgent
        self._worker: subprocess.Popen | None = None

        # Statistics
        self._sitrep_count = 0
        self._consolidation_count = 0
        self._last_sitrep_at: Optional[datetime] = None
        self._last_consolidation_at: Optional[datetime] = None

        logger.info(f"ThetaService initialized (kb_root={config.kb_root})")

    def _get_agent(self) -> Any:
        """Lazy-initialize ThetaAgent.

        Returns:
            ThetaAgent instance

        Raises:
            DaemonStartupError: If ThetaAgent fails to initialize
        """
        if self._agent is None:
            try:
                from gaius.agents.theta import ThetaAgent

                self._agent = ThetaAgent(
                    profile=self.config.profile,
                    kb_root=self.config.kb_root,
                    research_mode=self.config.research_mode,
                )
                logger.info("ThetaAgent lazily initialized")
            except Exception as e:
                logger.error(f"[#THETA.00000003.INITFAIL] ThetaAgent init failed: {e}")
                raise DaemonStartupError(
                    daemon_name="theta",
                    message=f"ThetaAgent initialization failed: {e}",
                    guru_code="#THETA.00000003.INITFAIL",
                )
        return self._agent

    async def start(self) -> None:
        """Start the ThetaService.

        Unlike CognitionService, ThetaService doesn't run a background loop.
        It's a passive service that responds to gRPC requests.
        """
        if self._running:
            logger.warning("ThetaService already running")
            return

        self._running = True
        self._started_at = datetime.now()

        logger.info("ThetaService started")

    async def stop(self) -> None:
        """Stop the ThetaService."""
        if not self._running:
            return

        self._running = False

        # Clear agent to free resources
        self._agent = None

        logger.info("ThetaService stopped")

    async def health_check(self) -> DaemonHealth:
        """Check ThetaService health.

        Returns:
            DaemonHealth with status
        """
        if not self._running:
            return DaemonHealth(
                healthy=False,
                message="ThetaService not running",
                guru_code="#THETA.00000002.STARTFAIL",
            )

        # Check if KB root exists
        kb_path = Path(self.config.kb_root)
        if not kb_path.exists():
            return DaemonHealth(
                healthy=False,
                message=f"KB root not found: {self.config.kb_root}",
                guru_code="#THETA.00000003.INITFAIL",
                details={"kb_root": self.config.kb_root},
            )

        # Try to access ThetaAgent (lazy init check)
        try:
            agent = self._get_agent()
            has_agent = agent is not None
        except Exception as e:
            return DaemonHealth(
                healthy=False,
                message=f"ThetaAgent unavailable: {e}",
                guru_code="#THETA.00000003.INITFAIL",
            )

        return DaemonHealth(
            healthy=True,
            message="ThetaService operational",
            details={
                "kb_root": self.config.kb_root,
                "research_mode": self.config.research_mode,
                "sitrep_count": self._sitrep_count,
                "consolidation_count": self._consolidation_count,
                "last_sitrep": self._last_sitrep_at.isoformat() if self._last_sitrep_at else None,
                "last_consolidation": self._last_consolidation_at.isoformat() if self._last_consolidation_at else None,
                "uptime_seconds": (datetime.now() - self._started_at).total_seconds() if self._started_at else 0,
            },
        )

    # =========================================================================
    # ThetaAgent Operations (gRPC-facing)
    # =========================================================================

    async def sitrep(self, horizon: str = "day") -> dict[str, Any]:
        """Generate situational awareness report.

        Args:
            horizon: Temporal horizon (day, week, quarter, open)

        Returns:
            SITREP data dict with report contents

        Raises:
            Exception: If SITREP generation fails
        """
        agent = self._get_agent()

        try:
            report = await agent.sitrep(horizon=horizon)
            report_dict = report.to_dict()

            self._sitrep_count += 1
            self._last_sitrep_at = datetime.now()

            return {
                "success": True,
                "horizon": horizon,
                "generated_at": report.generated_at.isoformat(),
                "report": report_dict,
                "ascii_format": report.to_ascii(),
            }
        except Exception as e:
            logger.exception(f"[#THETA.00000004.SITREPFAIL] SITREP failed: {e}")
            return {
                "success": False,
                "horizon": horizon,
                "error": str(e),
                "guru_code": "#THETA.00000004.SITREPFAIL",
            }

    async def run_consolidation(
        self,
        temporal_slice: Optional[str] = None,
        max_candidates: int = 10,
    ) -> dict[str, Any]:
        """Run NVAR-mediated consolidation cycle.

        Args:
            temporal_slice: Slice ID (e.g., "2025-W52"). None = current week.
            max_candidates: Maximum candidates to evaluate per cycle.

        Returns:
            Consolidation result dict

        Raises:
            Exception: If consolidation fails
        """
        from gaius.agents.theta.consolidation import get_week_slice_id
        from gaius.engine.services.theta_cycle import NOTHOUGHTS, NOENCODE

        slice_id = temporal_slice or get_week_slice_id()

        try:
            thoughts = await self._thoughts_for_slice(slice_id)
            if not thoughts:
                return {
                    "success": False,
                    "slice_id": slice_id,
                    "error": f"{NOTHOUGHTS} no cognition_thoughts in {slice_id}",
                    "guru_code": NOTHOUGHTS,
                }
            payload = {
                "method": "consolidate",
                "params": {
                    "slice_id": slice_id,
                    "thoughts": thoughts,
                    "max_candidates": max_candidates or self.config.default_max_candidates,
                },
            }
            raw = await asyncio.to_thread(self._worker_rpc, payload)
            if raw.get("error"):
                err = raw["error"]
                msg = err.get("message") if isinstance(err, dict) else str(err)
                raise RuntimeError(msg)
            result = raw.get("result") or {}
            self._consolidation_count += 1
            self._last_consolidation_at = datetime.now()
            if result.get("error") and str(result["error"]).startswith("#THETA.00000010"):
                result["guru_code"] = NOENCODE
            return result
        except Exception as e:
            error_msg = str(e)
            guru_code = "#THETA.00000013.CONSFAIL"
            if "THINCABI" in error_msg or type(e).__name__ == "ThincAbiError":
                guru_code = "#THETA.00000012.THINCABI"
            elif "DEEPONTO_UNAVAILABLE" in error_msg or "DeepOntoNotAvailableError" in type(e).__name__:
                guru_code = "#THETA.00000001.DEEPONTO"
            elif "ONTOLOGY_INVALID" in error_msg:
                guru_code = "#THETA.00000005.ONTOLOGY_INVALID"

            logger.exception(f"[{guru_code}] Consolidation failed: {e}")
            return {
                "success": False,
                "slice_id": slice_id,
                "error": error_msg,
                "guru_code": guru_code,
            }

    async def _thoughts_for_slice(self, slice_id: str) -> list[dict[str, Any]]:
        """ISO-week thoughts from Postgres — the live consolidation input."""
        if self._db_pool is None:
            return []
        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id::text AS id, title, content, domains, kb_paths
                  FROM cognition_thoughts
                 WHERE to_char(created_at AT TIME ZONE 'UTC', 'IYYY')
                       || '-W' || to_char(created_at AT TIME ZONE 'UTC', 'IW')
                       = $1
                """,
                slice_id,
            )
        return [dict(r) for r in rows]

    def _ensure_worker(self) -> None:
        if self._worker is not None and self._worker.poll() is None:
            return
        env = os.environ.copy()
        env.setdefault("CUDA_VISIBLE_DEVICES", "4")
        env.setdefault("HF_HOME", os.environ.get("HF_HOME", "/raid/cache/huggingface"))
        env.pop("HF_HUB_CACHE", None)
        self._worker = subprocess.Popen(
            [sys.executable, "-m", "gaius.engine.services.theta_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,
        )
        logger.info("theta_worker pid=%s gpu=%s", self._worker.pid, env.get("CUDA_VISIBLE_DEVICES"))

    def _worker_rpc(self, cmd: dict[str, Any], timeout: float = 1800.0) -> dict[str, Any]:
        self._ensure_worker()
        assert self._worker is not None
        assert self._worker.stdin is not None
        assert self._worker.stdout is not None
        self._worker.stdin.write(json.dumps(cmd, default=str) + "\n")
        self._worker.stdin.flush()
        import select

        r, _, _ = select.select([self._worker.stdout], [], [], timeout)
        if not r:
            raise TimeoutError("theta_worker RPC timed out")
        line = self._worker.stdout.readline()
        if not line:
            err = (self._worker.stderr.read() if self._worker.stderr else "") or "worker died"
            raise RuntimeError(err[:2000])
        return json.loads(line)

    async def _encode_centroid(self, thoughts: list[dict[str, Any]]) -> Any:
        """Mean embedding of thought title+content. Fail closed (no zero vector)."""
        import numpy as np
        from gaius.models.embeddings import embed_text

        vecs = []
        for t in thoughts:
            text = f"{t.get('title') or ''}\n{t.get('content') or ''}".strip()
            if not text:
                continue
            vec = await embed_text(text)
            if vec is None or getattr(vec, "size", 0) == 0:
                raise RuntimeError("empty embedding")
            vecs.append(np.asarray(vec, dtype=float))
        if not vecs:
            raise RuntimeError("no thought text to encode")
        return np.mean(np.stack(vecs), axis=0)

    def agenda(self, action: str = "list", horizon: str = "day") -> dict[str, Any]:
        """List or init the KB day agenda.

        Args:
            action: ``list`` or ``init``
            horizon: day | week | quarter | open
        """
        from gaius.agents.theta.horizons import Horizon
        from gaius.agents.theta.agenda import AgendaAggregator, AgendaTask

        action = (action or "list").strip().lower()
        if action not in ("list", "init"):
            return {
                "success": False,
                "action": action,
                "horizon": horizon,
                "error": f"Unknown agenda action: {action} (list|init)",
            }

        try:
            hz = Horizon(horizon.lower()) if horizon else Horizon.DAY
        except ValueError:
            return {
                "success": False,
                "action": action,
                "horizon": horizon,
                "error": f"Unknown horizon: {horizon}",
            }

        agent = self._get_agent()
        agg: AgendaAggregator = agent.agenda
        created: bool | None = None
        if action == "init":
            result = agg.init_day_agenda(hz)
            created = bool(result["created"])
            tasks: list[AgendaTask] = result["items"]
            path = result["path"]
        else:
            tasks = agg.aggregate(hz)
            day = agg.day_agenda_path()
            path = "current/agenda.md" if day.is_file() else ""

        def _item(t: AgendaTask) -> dict[str, Any]:
            return {
                "description": t.description,
                "priority": t.priority,
                "project": t.project,
                "due_date": t.due_date.isoformat() if t.due_date else "",
                "completed": t.completed,
                "source_path": t.source_path,
            }

        return {
            "success": True,
            "action": action,
            "horizon": hz.value,
            "path": path,
            "created": bool(created) if created is not None else False,
            "items": [_item(t) for t in tasks],
            "ascii_format": agg.format_ascii(
                tasks, horizon=hz, path=path or "current/agenda.md", created=created
            ),
        }

    def get_consolidation_stats(self) -> dict[str, Any]:
        """Get consolidation statistics.

        Returns:
            Statistics dict from ThetaAgent
        """
        try:
            agent = self._get_agent()
            stats = agent.get_consolidation_stats()

            # Add service-level stats
            stats["service"] = {
                "running": self._running,
                "sitrep_count": self._sitrep_count,
                "consolidation_count": self._consolidation_count,
                "last_sitrep": self._last_sitrep_at.isoformat() if self._last_sitrep_at else None,
                "last_consolidation": self._last_consolidation_at.isoformat() if self._last_consolidation_at else None,
            }

            return stats
        except Exception as e:
            logger.error(f"Failed to get consolidation stats: {e}")
            return {
                "error": str(e),
                "service": {
                    "running": self._running,
                    "sitrep_count": self._sitrep_count,
                    "consolidation_count": self._consolidation_count,
                },
            }


# Module-level singleton for direct imports
_theta_service: Optional[ThetaService] = None


def get_theta_service(config: Optional[ThetaConfig] = None) -> ThetaService:
    """Get or create ThetaService singleton.

    Args:
        config: Optional config (only used on first call)

    Returns:
        ThetaService instance
    """
    global _theta_service
    if _theta_service is None:
        _theta_service = ThetaService(config or ThetaConfig())
    return _theta_service


async def reset_theta_service() -> None:
    """Reset ThetaService singleton (for testing)."""
    global _theta_service
    if _theta_service:
        await _theta_service.stop()
    _theta_service = None
