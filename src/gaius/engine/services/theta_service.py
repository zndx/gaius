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
- #THETA.00000005.CONSFAIL - Consolidation cycle failed
"""

import asyncio
import logging
import os
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

        # ThetaAgent is lazily initialized
        self._agent: Optional[Any] = None  # Type: ThetaAgent

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
        agent = self._get_agent()

        try:
            result = await agent.run_consolidation(
                temporal_slice=temporal_slice,
                max_candidates=max_candidates or self.config.default_max_candidates,
            )

            self._consolidation_count += 1
            self._last_consolidation_at = datetime.now()

            return {
                "success": result.error is None,
                "slice_id": result.slice_id,
                "signal": result.signal.to_dict() if result.signal else None,
                "candidates_evaluated": result.candidates_evaluated,
                "candidates_selected": result.candidates_selected,
                "documents_augmented": result.documents_augmented,
                "effectiveness": result.effectiveness,
                "error": result.error,
            }
        except Exception as e:
            error_msg = str(e)
            guru_code = "#THETA.00000005.CONSFAIL"

            # Check for specific DeepOnto error
            if "DEEPONTO_UNAVAILABLE" in error_msg or "DeepOntoNotAvailableError" in type(e).__name__:
                guru_code = "#THETA.00000001.DEEPONTO"

            logger.exception(f"[{guru_code}] Consolidation failed: {e}")
            return {
                "success": False,
                "slice_id": temporal_slice or "current",
                "error": error_msg,
                "guru_code": guru_code,
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
