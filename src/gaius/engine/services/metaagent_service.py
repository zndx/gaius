"""MetaAgent Service - First-class engine daemon for observability sync and audits.

MetaAgent transforms from ad-hoc execution to a proper engine daemon that:
- Syncs meta.* views to Metabase models/dashboards hourly
- Runs weekly LLM-powered audits with pooled budget
- Tracks quality assessments for textbook-quality detection
- Manages audit recommendations lifecycle (Atropos RL loop)

Architecture:
- Implements BaseDaemon protocol for centralized lifecycle management
- OPTIONAL criticality - engine starts even if Metabase unavailable
- Uses PooledBudgetManager for budget-constrained LLM calls
- Uses MetabaseSyncClient for dashboard sync
- Schedules via pg_cron (fallback: internal scheduler)
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any

import asyncpg

from gaius.engine.generated import (
    AuditFinding,
    AuditRecommendation,
    GetQualitySummaryResponse,
    ListRecommendationsResponse,
    MetaAgentAuditResponse,
    MetaAgentStatusResponse,
    MetabaseSyncResponse,
    PooledBudgetStatus,
    QualityAssessment,
    QualitySourceSummary,
    UpdateRecommendationResponse,
)
from gaius.engine.services.base_daemon import (
    BaseDaemon,
    DaemonCriticality,
    DaemonHealth,
    DaemonStartupError,
)
from gaius.engine.services.metabase_sync import (
    MetabaseSyncClient,
    SyncResult,
    get_metabase_client,
)
from gaius.engine.services.pooled_budget import (
    PooledBudgetManager,
    get_pooled_budget,
)

logger = logging.getLogger(__name__)


class MetaAgentService(BaseDaemon):
    """MetaAgent engine daemon for observability and self-improvement.

    Features:
    - Hourly Metabase sync (via pg_cron or internal scheduler)
    - Weekly LLM audits with budget constraints
    - Quality assessment tracking
    - Recommendation lifecycle management

    Guru Meditation Codes:
    - #MA.00000001.BUDGETEXHAUST - Weekly budget exhausted
    - #MA.00000002.BUDGETLOCK - Failed to acquire budget lock
    - #MA.00000003.BUDGETDB - Database error during budget operation
    - #MA.00000010.MBNOCONFIG - Metabase not configured
    - #MA.00000011.MBCONNFAIL - Metabase connection failed
    - #MA.00000012.MBSYNCFAIL - Sync operation failed
    - #MA.00000020.AUDITFAIL - Audit execution failed
    - #MA.00000021.AUDITTIMEOUT - Audit timed out
    """

    def __init__(
        self,
        budget_manager: PooledBudgetManager | None = None,
        metabase_client: MetabaseSyncClient | None = None,
        sync_interval_hours: int = 1,
        audit_day: int = 0,  # Monday
        audit_hour: int = 5,  # 5 AM UTC
        db_pool: asyncpg.Pool | None = None,
    ):
        """Initialize MetaAgent service.

        Args:
            budget_manager: Budget manager instance (default: singleton)
            metabase_client: Metabase client instance (default: singleton)
            sync_interval_hours: Hours between syncs (default: 1)
            audit_day: Day of week for audits (0=Monday, default: 0)
            audit_hour: Hour of day for audits (default: 5)
            db_pool: Database connection pool for direct DB access
        """
        self._budget_manager = budget_manager
        self._metabase_client = metabase_client
        self._sync_interval_hours = sync_interval_hours
        self._audit_day = audit_day
        self._audit_hour = audit_hour

        self._running = False
        self._sync_task: asyncio.Task | None = None
        self._last_sync_at: datetime | None = None
        self._last_audit_at: datetime | None = None
        self._pool: asyncpg.Pool | None = db_pool

    @property
    def name(self) -> str:
        return "metaagent"

    @property
    def criticality(self) -> DaemonCriticality:
        # OPTIONAL - engine starts even if Metabase unavailable
        return DaemonCriticality.OPTIONAL

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def budget_manager(self) -> PooledBudgetManager:
        if self._budget_manager is None:
            self._budget_manager = get_pooled_budget()
        return self._budget_manager

    @property
    def metabase_client(self) -> MetabaseSyncClient:
        if self._metabase_client is None:
            self._metabase_client = get_metabase_client()
        return self._metabase_client

    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create database connection pool."""
        if self._pool is None:
            database_url = os.environ.get(
                "DATABASE_URL",
                "postgres://gaius:gaius@localhost:5438/zndx_gaius",
            )
            self._pool = await asyncpg.create_pool(
                database_url,
                min_size=1,
                max_size=3,
            )
        return self._pool

    async def start(self) -> None:
        """Start the MetaAgent service."""
        if self._running:
            return

        logger.info("Starting MetaAgent service...")

        # Initialize budget manager
        await self.budget_manager.ensure_initialized()

        # Test Metabase connection (non-blocking - we continue even if unavailable)
        metabase_connected = await self.metabase_client.test_connection()
        if not metabase_connected:
            logger.warning(
                "[#MA.00000010.MBNOCONFIG] Metabase not configured or unavailable. "
                "Sync will be skipped until configured."
            )

        # Start sync scheduler task
        self._sync_task = asyncio.create_task(self._sync_loop())
        self._running = True

        logger.info("MetaAgent service started")

    async def stop(self) -> None:
        """Stop the MetaAgent service gracefully."""
        if not self._running:
            return

        logger.info("Stopping MetaAgent service...")
        self._running = False

        # Cancel sync task
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            self._sync_task = None

        # Close connections
        if self._pool:
            await self._pool.close()
            self._pool = None

        await self.budget_manager.close()
        await self.metabase_client.close()

        logger.info("MetaAgent service stopped")

    async def health_check(self) -> DaemonHealth:
        """Check MetaAgent service health."""
        if not self._running:
            return DaemonHealth(
                healthy=False,
                message="MetaAgent service not running",
                guru_code="#MA.00000030.NOTRUNNING",
            )

        # Get budget status
        budget_status = await self.budget_manager.get_status()

        # Check Metabase connection
        metabase_ok = self.metabase_client._connected

        # Determine overall health
        # We're healthy as long as we're running - Metabase is optional
        return DaemonHealth(
            healthy=True,
            message="MetaAgent service running",
            details={
                "metabase_connected": metabase_ok,
                "last_sync_at": self._last_sync_at.isoformat() if self._last_sync_at else None,
                "last_audit_at": self._last_audit_at.isoformat() if self._last_audit_at else None,
                "budget_health": budget_status.budget_health,
                "budget_remaining": budget_status.weekly_remaining,
            },
        )

    async def _sync_loop(self) -> None:
        """Background loop for periodic sync and audit checks."""
        while self._running:
            try:
                # Check if sync is due
                now = datetime.utcnow()

                # Hourly sync
                if self._should_sync(now):
                    await self.trigger_sync()

                # Weekly audit check (Monday 5 AM)
                if self._should_audit(now):
                    await self.trigger_audit()

                # Sleep until next check (every 5 minutes)
                await asyncio.sleep(300)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in MetaAgent sync loop: {e}")
                await asyncio.sleep(60)  # Back off on error

    def _should_sync(self, now: datetime) -> bool:
        """Check if sync is due."""
        if self._last_sync_at is None:
            return True
        return now - self._last_sync_at > timedelta(hours=self._sync_interval_hours)

    def _should_audit(self, now: datetime) -> bool:
        """Check if audit is due (weekly)."""
        # Check if it's the right day and hour
        if now.weekday() != self._audit_day:
            return False
        if now.hour != self._audit_hour:
            return False

        # Check if we already ran today
        if self._last_audit_at and self._last_audit_at.date() == now.date():
            return False

        return True

    async def get_status(self) -> MetaAgentStatusResponse:
        """Get current service status."""
        budget = await self.budget_manager.get_status()

        # Calculate next audit time
        now = datetime.utcnow()
        days_until_audit = (self._audit_day - now.weekday()) % 7
        if days_until_audit == 0 and now.hour >= self._audit_hour:
            days_until_audit = 7
        next_audit = (now + timedelta(days=days_until_audit)).replace(
            hour=self._audit_hour, minute=0, second=0, microsecond=0
        )

        return MetaAgentStatusResponse(
            running=self._running,
            metabase_connected=self.metabase_client._connected,
            last_sync_at=self._last_sync_at.isoformat() if self._last_sync_at else "",
            last_audit_at=self._last_audit_at.isoformat() if self._last_audit_at else "",
            next_audit_at=next_audit.isoformat(),
            budget=budget,
            models_synced=0,  # TODO: track from DB
            dashboards_synced=0,
            error="",
        )

    async def trigger_sync(self, full_refresh: bool = False) -> MetabaseSyncResponse:
        """Trigger Metabase sync.

        Args:
            full_refresh: If True, recreate all models

        Returns:
            MetabaseSyncResponse with results
        """
        start_time = datetime.utcnow()
        run_id = await self._record_sync_start(full_refresh)

        try:
            result = await self.metabase_client.sync_all_models(full_refresh=full_refresh)

            self._last_sync_at = datetime.utcnow()
            await self._record_sync_complete(run_id, result)

            return MetabaseSyncResponse(
                success=result.success,
                models_synced=result.models_synced,
                models_failed=result.models_failed,
                dashboards_synced=result.dashboards_synced,
                dashboards_failed=result.dashboards_failed,
                duration_ms=result.duration_ms,
                error=result.error or "",
            )

        except Exception as e:
            error_msg = f"[#MA.00000012.MBSYNCFAIL] Sync failed: {e}"
            logger.error(error_msg)
            await self._record_sync_failed(run_id, str(e))
            return MetabaseSyncResponse(
                success=False,
                error=error_msg,
            )

    async def trigger_audit(
        self,
        scope: str = "full",
        use_remote_llm: bool = True,
    ) -> MetaAgentAuditResponse:
        """Trigger a MetaAgent audit.

        Args:
            scope: Audit scope (full, lineage, operations, topology)
            use_remote_llm: If True, use remote LLM (budget permitting)

        Returns:
            MetaAgentAuditResponse with results
        """
        audit_id = str(uuid.uuid4())
        start_time = datetime.utcnow()

        # Record audit start
        await self._record_audit_start(audit_id, scope)

        try:
            # Check budget if using remote LLM
            provider = "cerebras" if use_remote_llm else "local"
            if use_remote_llm:
                acquisition = await self.budget_manager.acquire(provider)
                if not acquisition.success:
                    error_msg = f"[#MA.00000001.BUDGETEXHAUST] {acquisition.error}"
                    await self._record_audit_failed(audit_id, error_msg)
                    return MetaAgentAuditResponse(
                        success=False,
                        audit_id=audit_id,
                        error=error_msg,
                    )

            # Run audit analysis
            findings, recommendations = await self._run_audit_analysis(scope, provider)

            # Record completion
            self._last_audit_at = datetime.utcnow()
            duration_ms = int((self._last_audit_at - start_time).total_seconds() * 1000)

            await self._record_audit_complete(
                audit_id, findings, recommendations, provider, duration_ms
            )

            return MetaAgentAuditResponse(
                success=True,
                audit_id=audit_id,
                findings=[
                    AuditFinding(
                        category=f.get("category", ""),
                        severity=f.get("severity", ""),
                        title=f.get("title", ""),
                        description=f.get("description", ""),
                        affected_component=f.get("affected_component", ""),
                    )
                    for f in findings
                ],
                recommendations=[
                    AuditRecommendation(
                        id=str(r.get("id", "")),
                        category=r.get("category", ""),
                        severity=r.get("severity", ""),
                        title=r.get("title", ""),
                        description=r.get("description", ""),
                        suggested_implementation=r.get("suggested_implementation", ""),
                        status=r.get("status", "pending"),
                    )
                    for r in recommendations
                ],
                duration_ms=duration_ms,
                tokens_used=0,
                provider=provider,
                error="",
            )

        except Exception as e:
            error_msg = f"[#MA.00000020.AUDITFAIL] Audit failed: {e}"
            logger.error(error_msg)
            await self._record_audit_failed(audit_id, str(e))
            return MetaAgentAuditResponse(
                success=False,
                audit_id=audit_id,
                error=error_msg,
            )

    async def _run_audit_analysis(
        self,
        scope: str,
        provider: str,
    ) -> tuple[list[dict], list[dict]]:
        """Run Multi-Agent Debate audit analysis.

        Implements the 5-phase debate flow (SOTA LLM agent architecture):
        1. Data Gathering (SQL queries - no LLM)
        2. Initial Analysis (Cerebras GLM 4.7)
        3. Skeptic Critique (XAI Grok)
        4. Actionability Validation (Cerebras)
        5. Judge Synthesis (XAI Grok)

        This architecture overcomes "Degeneration-of-Thought" where single-agent
        systems become overconfident. The debate between Analyst, Skeptic, and
        Judge produces robust findings that survive adversarial scrutiny.

        Args:
            scope: Audit scope (full, health, performance, etc.)
            provider: LLM provider hint (ignored - debate uses Quality-First strategy)

        Returns:
            Tuple of (findings, recommendations)
        """
        from gaius.engine.services.metaagent_debate import get_debate_coordinator
        from gaius.engine.services.llm_exchange_context import link_kb_artifact

        # Create coordinator with parent run ID for lineage
        pool = await self._get_pool()
        parent_run_id = str(uuid.uuid4())
        coordinator = get_debate_coordinator(
            pool=pool,
            parent_run_id=parent_run_id,
        )

        # Execute the 5-phase debate
        result = await coordinator.run_debate(scope)

        # Store debate transcript to KB if successful
        if result.succeeded and result.transcript.exchange_ids:
            try:
                kb_path = f"scratch/{datetime.now().strftime('%Y-%m-%d')}/audit_{scope}_{parent_run_id[:8]}.md"
                await self._write_kb_artifact(kb_path, result.transcript.to_markdown())

                # Link KB artifact to exchanges for HX lineage
                for exchange_id in result.transcript.exchange_ids:
                    await link_kb_artifact(kb_path, exchange_id)

                logger.info(f"Debate transcript saved to KB: {kb_path}")
            except Exception as e:
                logger.warning(f"Failed to save debate transcript: {e}")

        # Convert to legacy format for gRPC response compatibility
        findings = [
            {
                "category": "audit",
                "severity": "high" if f.final_confidence > 0.7 else "medium",
                "title": f.title,
                "description": f.description,
                "confidence": f.final_confidence,
                "status": f.status,
                "affected_component": "",
            }
            for f in result.findings
        ]

        recommendations = [
            {
                "id": str(i),
                "category": "audit",
                "severity": "high" if r.priority <= 2 else "medium",
                "title": r.title,
                "description": r.description,
                "suggested_implementation": ", ".join(r.commands) if r.commands else "",
                "status": "pending",
            }
            for i, r in enumerate(result.recommendations, 1)
        ]

        # If debate failed, include error as a finding
        if result.error:
            findings.append({
                "category": "audit",
                "severity": "high",
                "title": "Audit Analysis Error",
                "description": result.error,
                "affected_component": "metaagent_debate",
            })

        logger.info(
            f"Audit complete: {len(findings)} findings, {len(recommendations)} recommendations, "
            f"{result.total_llm_calls} LLM calls, {result.total_tokens} tokens"
        )

        return findings, recommendations

    async def _write_kb_artifact(self, kb_path: str, content: str) -> None:
        """Write content to KB as a scratch artifact.

        Args:
            kb_path: Relative KB path (e.g., "scratch/2026-01-19/audit.md")
            content: Markdown content to write
        """
        import os
        from pathlib import Path

        # Get KB root from environment or default
        kb_root = os.environ.get("GAIUS_KB_ROOT", "build/dev")
        full_path = Path(kb_root) / kb_path

        # Ensure parent directory exists
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Write content
        full_path.write_text(content)
        logger.debug(f"Wrote KB artifact: {full_path}")

    async def _record_sync_start(self, full_refresh: bool) -> int:
        """Record sync start in database."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(
                """
                INSERT INTO meta.metabase_sync_runs (full_refresh)
                VALUES ($1)
                RETURNING id
                """,
                full_refresh,
            )

    async def _record_sync_complete(self, run_id: int, result: SyncResult) -> None:
        """Record sync completion."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE meta.metabase_sync_runs
                SET completed_at = NOW(),
                    status = $2,
                    models_synced = $3,
                    models_failed = $4,
                    dashboards_synced = $5,
                    dashboards_failed = $6
                WHERE id = $1
                """,
                run_id,
                "completed" if result.success else "failed",
                result.models_synced,
                result.models_failed,
                result.dashboards_synced,
                result.dashboards_failed,
            )

    async def _record_sync_failed(self, run_id: int, error: str) -> None:
        """Record sync failure."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE meta.metabase_sync_runs
                SET completed_at = NOW(),
                    status = 'failed',
                    error_message = $2
                WHERE id = $1
                """,
                run_id,
                error,
            )

    async def _record_audit_start(self, audit_id: str, scope: str) -> None:
        """Record audit start in database."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO meta.metaagent_audits (audit_id, scope)
                VALUES ($1, $2)
                """,
                uuid.UUID(audit_id),
                scope,
            )

    async def _record_audit_complete(
        self,
        audit_id: str,
        findings: list[dict],
        recommendations: list[dict],
        provider: str,
        duration_ms: int,
    ) -> None:
        """Record audit completion."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Update audit record (serialize findings to JSON for JSONB column)
            await conn.execute(
                """
                UPDATE meta.metaagent_audits
                SET completed_at = NOW(),
                    status = 'completed',
                    findings = $2::jsonb,
                    provider = $3
                WHERE audit_id = $1
                """,
                uuid.UUID(audit_id),
                json.dumps(findings),
                provider,
            )

            # Insert recommendations
            for rec in recommendations:
                await conn.execute(
                    """
                    INSERT INTO meta.audit_recommendations
                    (audit_id, category, severity, title, description, suggested_implementation, affected_component)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    uuid.UUID(audit_id),
                    rec.get("category", ""),
                    rec.get("severity", "medium"),
                    rec.get("title", ""),
                    rec.get("description", ""),
                    rec.get("suggested_implementation", ""),
                    rec.get("affected_component", ""),
                )

    async def _record_audit_failed(self, audit_id: str, error: str) -> None:
        """Record audit failure."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE meta.metaagent_audits
                SET completed_at = NOW(),
                    status = 'failed',
                    metadata = metadata || jsonb_build_object('error', $2)
                WHERE audit_id = $1
                """,
                uuid.UUID(audit_id),
                error,
            )

    async def get_quality_summary(
        self,
        source_type: str | None = None,
    ) -> GetQualitySummaryResponse:
        """Get quality assessment summary by source type.

        Args:
            source_type: Filter by source type (kb, hx, exchange, reasoning_trace)

        Returns:
            GetQualitySummaryResponse with assessments
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if source_type:
                rows = await conn.fetch(
                    """
                    SELECT
                        source_type,
                        COUNT(*) as total_assessments,
                        COUNT(*) FILTER (WHERE is_textbook_quality) as textbook_count,
                        AVG(coherence_score) as avg_coherence,
                        AVG(coverage_score) as avg_coverage,
                        AVG(novelty_score) as avg_novelty,
                        AVG(weighted_reward) as avg_reward
                    FROM meta.quality_assessments
                    WHERE source_type = $1
                    GROUP BY source_type
                    """,
                    source_type,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT
                        source_type,
                        COUNT(*) as total_assessments,
                        COUNT(*) FILTER (WHERE is_textbook_quality) as textbook_count,
                        AVG(coherence_score) as avg_coherence,
                        AVG(coverage_score) as avg_coverage,
                        AVG(novelty_score) as avg_novelty,
                        AVG(weighted_reward) as avg_reward
                    FROM meta.quality_assessments
                    GROUP BY source_type
                    """
                )

        assessments = []
        for row in rows:
            assessments.append(
                QualitySourceSummary(
                    source_type=row["source_type"],
                    total_assessments=row["total_assessments"],
                    textbook_quality_count=row["textbook_count"],
                    avg_coherence=float(row["avg_coherence"]) if row["avg_coherence"] else 0.0,
                    avg_coverage=float(row["avg_coverage"]) if row["avg_coverage"] else 0.0,
                    avg_novelty=float(row["avg_novelty"]) if row["avg_novelty"] else 0.0,
                    avg_weighted_reward=float(row["avg_reward"]) if row["avg_reward"] else 0.0,
                )
            )

        return GetQualitySummaryResponse(
            assessments=assessments,
            error="",
        )

    async def list_recommendations(
        self,
        status_filter: str | None = None,
        severity_filter: str | None = None,
        limit: int = 20,
    ) -> ListRecommendationsResponse:
        """List audit recommendations with optional filters.

        Args:
            status_filter: Filter by status (pending, accepted, rejected, implemented, verified)
            severity_filter: Filter by severity (critical, high, medium, low)
            limit: Maximum number of results

        Returns:
            ListRecommendationsResponse with recommendations
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Build query with optional filters
            query = """
                SELECT
                    id,
                    audit_id,
                    category,
                    severity,
                    title,
                    description,
                    suggested_implementation,
                    affected_component,
                    status,
                    created_at,
                    accepted_at,
                    implemented_at,
                    verified_at
                FROM meta.audit_recommendations
                WHERE 1=1
            """
            params = []
            param_idx = 1

            if status_filter:
                query += f" AND status = ${param_idx}"
                params.append(status_filter)
                param_idx += 1

            if severity_filter:
                query += f" AND severity = ${param_idx}"
                params.append(severity_filter)
                param_idx += 1

            query += f" ORDER BY created_at DESC LIMIT ${param_idx}"
            params.append(limit)

            rows = await conn.fetch(query, *params)

        recommendations = []
        for row in rows:
            recommendations.append(
                AuditRecommendation(
                    id=str(row["id"]),
                    category=row["category"],
                    severity=row["severity"],
                    title=row["title"],
                    description=row["description"] or "",
                    suggested_implementation=row["suggested_implementation"] or "",
                    status=row["status"],
                )
            )

        return ListRecommendationsResponse(
            recommendations=recommendations,
            total_count=len(recommendations),
            error="",
        )

    async def update_recommendation(
        self,
        recommendation_id: int,
        new_status: str,
    ) -> UpdateRecommendationResponse:
        """Update a recommendation status.

        Args:
            recommendation_id: ID of the recommendation to update
            new_status: New status (accepted, rejected, implemented, verified)

        Returns:
            UpdateRecommendationResponse with result
        """
        valid_statuses = {"pending", "accepted", "rejected", "implemented", "verified"}
        if new_status not in valid_statuses:
            return UpdateRecommendationResponse(
                success=False,
                error=f"Invalid status: {new_status}. Must be one of: {valid_statuses}",
            )

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Update based on status transition
            timestamp_field = None
            if new_status == "accepted":
                timestamp_field = "accepted_at"
            elif new_status == "implemented":
                timestamp_field = "implemented_at"
            elif new_status == "verified":
                timestamp_field = "verified_at"

            if timestamp_field:
                result = await conn.execute(
                    f"""
                    UPDATE meta.audit_recommendations
                    SET status = $2, {timestamp_field} = NOW()
                    WHERE id = $1
                    """,
                    recommendation_id,
                    new_status,
                )
            else:
                result = await conn.execute(
                    """
                    UPDATE meta.audit_recommendations
                    SET status = $2
                    WHERE id = $1
                    """,
                    recommendation_id,
                    new_status,
                )

            if result == "UPDATE 0":
                return UpdateRecommendationResponse(
                    success=False,
                    error=f"Recommendation {recommendation_id} not found",
                )

        return UpdateRecommendationResponse(
            success=True,
            recommendation_id=str(recommendation_id),
            new_status=new_status,
            error="",
        )


# Module-level singleton
_metaagent_service: MetaAgentService | None = None


def get_metaagent_service() -> MetaAgentService:
    """Get or create MetaAgent service singleton."""
    global _metaagent_service
    if _metaagent_service is None:
        _metaagent_service = MetaAgentService()
    return _metaagent_service


async def reset_metaagent_service() -> None:
    """Reset MetaAgent service singleton (for testing)."""
    global _metaagent_service
    if _metaagent_service:
        await _metaagent_service.stop()
    _metaagent_service = None
