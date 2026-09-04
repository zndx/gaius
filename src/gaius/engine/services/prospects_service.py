"""Prospects/Stewardship service for the Gaius engine.

Manages prospect intelligence via FMP API and LLM analysis:
- Status queries (cached data, no cost)
- Daily SEC filing checks (local LLM, ~$0)
- Full analysis updates (Cerebras + Grok, ~$0.60/prospect)

Integrates with:
- FMP API for SEC filings and institutional holdings
- Metaflow ProspectsFlow for orchestrated analysis
- Iceberg HX for raw exchange capture
- PostgreSQL for candidate/strategy state

Guru Meditation Codes:
- #PS.00000001.NOCONFIG: Watchlist config not found
- #PS.00000002.NOAPIKEY: FMP_API_KEY not configured
- #PS.00000003.FMPFAIL: FMP API request failed
- #PS.00000004.FLOWFAIL: Metaflow execution failed
- #PS.00000005.DBFAIL: Database operation failed
- #PS.00000008.NOATTACH: Ambient cycle ran without Prospects attached
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import asyncpg

from gaius.hx.fmp import FMPEndpoint, FMPExchangeRecord, get_fmp_capture
from .fmp_client import FMPClient, FMPClientConfig, SECFiling, InstitutionalHolder

logger = logging.getLogger(__name__)


# (2026-09-04) FIFO prose formatting lives in gaius.flows.prospects.market_feed
# (format_market_row) with the fmp_roll flow that owns the pull.


class ProspectsError(Exception):
    """Prospects service error with Guru Meditation code."""

    def __init__(self, message: str, guru_code: str | None = None):
        super().__init__(message)
        self.guru_code = guru_code

    def __str__(self) -> str:
        if self.guru_code:
            return f"{super().__str__()}\n  Guru Meditation: {self.guru_code}"
        return super().__str__()


@dataclass
class CandidateInfo:
    """A prospect candidate with current state."""

    symbol: str
    company_name: str
    exchange: str
    cik: str = ""
    sector: str = ""
    industry: str = ""
    last_filing_date: str = ""
    last_filing_type: str = ""
    pending_filings: int = 0
    priority: int = 2
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "exchange": self.exchange,
            "cik": self.cik,
            "sector": self.sector,
            "industry": self.industry,
            "last_filing_date": self.last_filing_date,
            "last_filing_type": self.last_filing_type,
            "pending_filings": self.pending_filings,
            "priority": self.priority,
            "notes": self.notes,
        }


@dataclass
class StrategyInfo:
    """Investment strategy/position for a candidate."""

    symbol: str
    category: str = "watch"  # watch, research, position, exit
    allocation_weight: float = 0.0
    target_weight: float = 0.0
    conviction: float = 0.0  # 0-1 scale
    last_analysis_at: str = ""
    needs_update: bool = False
    thesis: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "symbol": self.symbol,
            "category": self.category,
            "allocation_weight": self.allocation_weight,
            "target_weight": self.target_weight,
            "conviction": self.conviction,
            "last_analysis_at": self.last_analysis_at,
            "needs_update": self.needs_update,
            "thesis": self.thesis,
        }


@dataclass
class ProspectsConfig:
    """Configuration for Prospects service.

    Profile/domain defaults are resolved from the database at runtime when
    empty strings are provided. This allows the application-level profile/domain
    state to drive flow execution.
    """

    # KB root path for artifacts
    kb_root: str = "build/dev"

    # Default profile/domain context (empty = resolve from database)
    default_profile: str = ""
    default_domain: str = ""

    # Watchlist config path
    watchlist_path: Path = field(
        default_factory=lambda: Path("config/prospects/watchlist.conf")
    )

    # Check settings
    check_interval_hours: int = 24
    filing_lookback_days: int = 30
    form_types: list[str] = field(default_factory=lambda: ["10-K", "10-Q", "8-K"])

    # Update settings
    max_concurrent_analyses: int = 3
    analysis_timeout_s: int = 120
    synthesis_timeout_s: int = 60


class ProspectsService:
    """Prospects/Stewardship service managing FMP-based intelligence.

    Provides three tiers of operations:
    1. Status - Cached state lookup (~0ms, $0)
    2. Check - Daily FMP poll + local decision (~5s, $0)
    3. Update - Full LLM analysis (~2min, ~$0.60/prospect)

    Usage:
        service = ProspectsService(pool)
        await service.start()

        # Lightweight status
        status = await service.get_status(profile="zndx", domain="prospecting")

        # Daily check (can be pg_cron triggered)
        result = await service.run_check(profile="zndx", domain="prospecting")

        # Full update with streaming progress
        async for event in service.run_update(profile="zndx", domain="prospecting"):
            print(f"Progress: {event['progress']:.0%} - {event['message']}")
    """

    def __init__(
        self,
        pool: asyncpg.Pool | None = None,
        config: ProspectsConfig | None = None,
    ):
        self._pool = pool
        self._config = config or ProspectsConfig()
        self._running = False
        self._last_check_at: datetime | None = None
        self._cached_candidates: dict[str, CandidateInfo] = {}
        self._cached_strategies: dict[str, StrategyInfo] = {}

        # FMP client (created on start)
        self._fmp_client: FMPClient | None = None
        # (2026-09-04) The prospects FIFO is durable (buffer_entries) and
        # written by the fmp_roll flow on pg_cron; this instance is the
        # engine's read-through view (Discover token counts, synthesis
        # slices). pool=None (tests) keeps the RAM behaviour.
        from gaius.engine.services.buffer_store import DurableBuffer

        self._buffer = DurableBuffer(pool, "prospects", 256 * 1024)

    async def start(self) -> None:
        """Start the prospects service (watchlist sync + state load + buffer view)."""
        if self._running:
            return

        logger.info("Starting ProspectsService")

        # Load watchlist config first (config is the driver)
        config_symbols = await self._load_watchlist()

        # Sync config to database (activate/archive as needed)
        if self._pool and config_symbols:
            await self._sync_config_to_db(config_symbols)

        # Load state from database (now reflects synced config)
        if self._pool:
            await self._load_state_from_db()

        self._running = True
        self._buffer.start_refresh()
        logger.info(
            f"ProspectsService started with {len(self._cached_candidates)} candidates"
        )

    async def stop(self) -> None:
        """Stop the prospects service (the buffer view's refresh task)."""
        if not self._running:
            return

        logger.info("Stopping ProspectsService")
        self._running = False
        await self._buffer.stop_refresh()

    # (2026-09-04) _roll_fmp_buffer / ingest_market_buffer / compact_buffer moved
    # to gaius.flows.prospects.market_buffer_flow (FmpMarketBufferFlow on
    # pg_cron 'fmp-roll'); the market feed itself is
    # gaius.flows.prospects.market_feed.fetch_market_entries.

    async def _load_watchlist(self) -> list[str]:
        """Load prospect watchlist from HOCON config.

        Returns:
            List of symbols from config (used for DB sync).
        """
        config_path = self._config.watchlist_path

        if not config_path.exists():
            # Try relative to project root
            alt_path = Path(__file__).parent.parent.parent.parent.parent / config_path
            if alt_path.exists():
                config_path = alt_path
            else:
                logger.warning(
                    f"Watchlist config not found: {config_path}\n"
                    f"  Guru Meditation: #PS.00000001.NOCONFIG\n"
                    f"  Create from watchlist.conf.example"
                )
                return []

        try:
            from pyhocon import ConfigFactory
        except ImportError:
            logger.warning("pyhocon not installed, skipping watchlist load")
            return []

        config_symbols: list[str] = []
        try:
            config = ConfigFactory.parse_file(str(config_path))
            watchlist = config.get("prospects.watchlist", [])

            for entry in watchlist:
                symbol = entry.get("symbol")
                if not symbol:
                    continue

                config_symbols.append(symbol)

                # Pre-populate cache with config data (DB will override if exists)
                if symbol not in self._cached_candidates:
                    self._cached_candidates[symbol] = CandidateInfo(
                        symbol=symbol,
                        company_name=entry.get("company", symbol),
                        exchange=entry.get("exchange", ""),
                        priority=entry.get("priority", 2),
                        notes=entry.get("notes", ""),
                    )

            logger.info(f"Loaded {len(config_symbols)} symbols from watchlist config")
            return config_symbols

        except Exception as e:
            logger.error(f"Failed to load watchlist: {e}")
            return []

    async def _sync_config_to_db(self, config_symbols: list[str]) -> None:
        """Sync watchlist config to database using soft archive.

        Config is the authoritative source. This method:
        1. Inserts new symbols from config that don't exist in DB
        2. Activates symbols in config that were previously archived
        3. Archives symbols not in config (soft delete for referential integrity)

        Args:
            config_symbols: List of symbols from the watchlist config.
        """
        if not self._pool or not config_symbols:
            return

        try:
            # Check if tables/columns exist
            has_active = await self._pool.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'meta'
                    AND table_name = 'prospect_candidates'
                    AND column_name = 'active'
                )
            """)

            if not has_active:
                logger.debug("Soft archive columns not present, skipping sync")
                return

            # Insert new symbols from config that don't exist in DB
            for symbol in config_symbols:
                candidate = self._cached_candidates.get(symbol)
                if candidate:
                    await self._pool.execute("""
                        INSERT INTO meta.prospect_candidates
                            (symbol, company_name, exchange, priority, notes, active)
                        VALUES ($1, $2, $3, $4, $5, TRUE)
                        ON CONFLICT (symbol) DO NOTHING
                    """,
                        symbol,
                        candidate.company_name,
                        candidate.exchange,
                        candidate.priority,
                        candidate.notes,
                    )

            # Use the sync function to activate/archive as needed
            result = await self._pool.fetchrow("""
                SELECT * FROM meta.sync_prospect_watchlist($1)
            """, config_symbols)

            if result:
                activated = result["activated"]
                archived = result["archived"]
                unchanged = result["unchanged"]
                logger.info(
                    f"Config sync: {activated} activated, {archived} archived, "
                    f"{unchanged} unchanged"
                )

        except Exception as e:
            logger.warning(f"Failed to sync config to database: {e}")

    async def _load_state_from_db(self) -> None:
        """Load cached state from PostgreSQL (active candidates only)."""
        if not self._pool:
            return

        try:
            # Check if tables exist
            exists = await self._pool.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'meta'
                    AND table_name = 'prospect_candidates'
                )
            """)

            if not exists:
                logger.debug("Prospects tables not yet created, skipping DB load")
                return

            # Check if active column exists (for migration compatibility)
            has_active = await self._pool.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'meta'
                    AND table_name = 'prospect_candidates'
                    AND column_name = 'active'
                )
            """)

            # Load candidates (filter by active if column exists)
            if has_active:
                rows = await self._pool.fetch("""
                    SELECT symbol, company_name, exchange, cik, sector, industry,
                           last_filing_date, last_filing_type, pending_filings, priority, notes
                    FROM meta.prospect_candidates
                    WHERE active = TRUE
                """)
            else:
                rows = await self._pool.fetch("""
                    SELECT symbol, company_name, exchange, cik, sector, industry,
                           last_filing_date, last_filing_type, pending_filings, priority, notes
                    FROM meta.prospect_candidates
                """)

            for row in rows:
                self._cached_candidates[row["symbol"]] = CandidateInfo(
                    symbol=row["symbol"],
                    company_name=row["company_name"] or "",
                    exchange=row["exchange"] or "",
                    cik=row["cik"] or "",
                    sector=row["sector"] or "",
                    industry=row["industry"] or "",
                    last_filing_date=row["last_filing_date"] or "",
                    last_filing_type=row["last_filing_type"] or "",
                    pending_filings=row["pending_filings"] or 0,
                    priority=row["priority"] or 2,
                    notes=row["notes"] or "",
                )

            # Load strategies (only for active candidates)
            if has_active:
                rows = await self._pool.fetch("""
                    SELECT s.symbol, s.category, s.allocation_weight, s.target_weight,
                           s.conviction, s.last_analysis_at, s.needs_update, s.thesis
                    FROM meta.prospect_strategies s
                    JOIN meta.prospect_candidates c ON c.symbol = s.symbol
                    WHERE c.active = TRUE
                """)
            else:
                rows = await self._pool.fetch("""
                    SELECT symbol, category, allocation_weight, target_weight,
                           conviction, last_analysis_at, needs_update, thesis
                    FROM meta.prospect_strategies
                """)

            for row in rows:
                self._cached_strategies[row["symbol"]] = StrategyInfo(
                    symbol=row["symbol"],
                    category=row["category"] or "watch",
                    allocation_weight=row["allocation_weight"] or 0.0,
                    target_weight=row["target_weight"] or 0.0,
                    conviction=row["conviction"] or 0.0,
                    last_analysis_at=row["last_analysis_at"] or "",
                    needs_update=row["needs_update"] or False,
                    thesis=row["thesis"] or "",
                )

            logger.info(
                f"Loaded {len(self._cached_candidates)} candidates and "
                f"{len(self._cached_strategies)} strategies from database"
            )

        except Exception as e:
            logger.warning(f"Failed to load state from database: {e}")

    async def get_status(
        self,
        profile: str = "zndx",
        domain: str = "prospecting",
        symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get current prospects status from cache.

        Cost: $0 (cached data only)

        Args:
            profile: Profile name.
            domain: Domain context.
            symbols: Filter to specific symbols (None = all).

        Returns:
            Dict with candidates, strategies, and update recommendation.
        """
        # Filter candidates
        if symbols:
            candidates = [
                c.to_dict() for s, c in self._cached_candidates.items()
                if s in symbols
            ]
            strategies = [
                s.to_dict() for sym, s in self._cached_strategies.items()
                if sym in symbols
            ]
        else:
            candidates = [c.to_dict() for c in self._cached_candidates.values()]
            strategies = [s.to_dict() for s in self._cached_strategies.values()]

        # Calculate pending filings
        pending_filings = sum(c.get("pending_filings", 0) for c in candidates)

        # Determine if update is recommended
        update_recommended = False
        update_reason = ""

        if pending_filings > 0:
            update_recommended = True
            update_reason = f"{pending_filings} new filings detected"
        elif any(s.get("needs_update") for s in strategies):
            update_recommended = True
            update_reason = "Strategy updates needed"
        elif self._last_check_at:
            hours_since_check = (
                datetime.now(timezone.utc) - self._last_check_at
            ).total_seconds() / 3600
            if hours_since_check > self._config.check_interval_hours:
                update_recommended = True
                update_reason = f"Last check was {hours_since_check:.0f} hours ago"

        buf = self._buffer.get_stats()
        return {
            "profile": profile,
            "domain": domain,
            "candidates": candidates,
            "strategies": strategies,
            "pending_filings": pending_filings,
            "last_fmp_sync_at": (
                self._last_check_at.isoformat() if self._last_check_at else ""
            ),
            "update_recommended": update_recommended,
            "update_reason": update_reason,
            "buffer": buf,
        }

    async def run_check(
        self,
        profile: str = "zndx",
        domain: str = "prospecting",
        force: bool = False,
    ) -> dict[str, Any]:
        """Run daily check for new SEC filings.

        Cost: ~$0 (FMP API + local logic, no LLM calls). Occupies
        ``root.external.rate-metered`` for the duration, then releases
        so the YK row comes and goes.

        This method can be triggered by pg_cron for automated daily checks.
        """
        from gaius.engine.sentinel_claim import (
            YkAdmitError,
            delete_flow_sentinel,
            ephemeral_claim,
        )

        wid = ""
        try:
            wid = ephemeral_claim(
                "prospects-check", f"gaius-fmp-{int(time.time())}"
            )
        except YkAdmitError as e:
            raise ProspectsError(str(e), guru_code=e.code) from e
        try:
            return await self._run_check_body(profile, domain, force)
        finally:
            if wid:
                await asyncio.to_thread(delete_flow_sentinel, wid)

    async def _run_check_body(
        self,
        profile: str,
        domain: str,
        force: bool,
    ) -> dict[str, Any]:
        # Check if FMP check is throttled (but always query HX for pending work)
        fmp_throttled = False
        if not force and self._last_check_at:
            hours_since = (
                datetime.now(timezone.utc) - self._last_check_at
            ).total_seconds() / 3600
            if hours_since < self._config.check_interval_hours:
                fmp_throttled = True

        # Always query HX for pending analysis/synthesis (cheap, local queries)
        pending_analysis = await self._count_pending_analysis()
        pending_synthesis = await self._count_pending_synthesis()
        pending_analysis_count = sum(pending_analysis.values())
        pending_synthesis_count = len(pending_synthesis)

        # If FMP is throttled but there's pending HX work, still report it
        if fmp_throttled:
            has_pending = pending_analysis_count > 0 or pending_synthesis_count > 0

            reasons = []
            if pending_analysis_count > 0:
                reasons.append(f"{pending_analysis_count} pending analysis")
            if pending_synthesis_count > 0:
                reasons.append(f"{pending_synthesis_count} pending synthesis")

            if has_pending:
                reason = ", ".join(reasons)
            else:
                reason = "System converged - no pending work"

            return {
                "update_recommended": has_pending,
                "reason": reason,
                "new_filings_count": 0,
                "symbols_with_new_filings": [],
                "pending_analysis_count": pending_analysis_count,
                "pending_analysis_by_symbol": pending_analysis,
                "pending_synthesis_count": pending_synthesis_count,
                "pending_synthesis_symbols": list(pending_synthesis.keys()),
                "fmp_throttled": True,
            }

        # Get FMP API key
        api_key = os.environ.get("FMP_API_KEY")
        if not api_key:
            raise ProspectsError(
                "FMP_API_KEY not configured",
                guru_code="#PS.00000002.NOAPIKEY",
            )

        # Fetch recent filings for all candidates
        symbols_with_new = []
        new_filings_count = 0
        cutoff_date = datetime.now(timezone.utc) - timedelta(
            days=self._config.filing_lookback_days
        )

        for symbol, candidate in self._cached_candidates.items():
            try:
                filings = await self._fetch_sec_filings(symbol, api_key, profile, domain)

                # Count new filings
                new_for_symbol = 0
                for filing in filings:
                    filing_date_str = filing.get("fillingDate") or filing.get("acceptedDate")
                    if filing_date_str:
                        try:
                            filing_date = datetime.strptime(filing_date_str[:10], "%Y-%m-%d")
                            filing_date = filing_date.replace(tzinfo=timezone.utc)
                            if filing_date > cutoff_date:
                                new_for_symbol += 1
                        except ValueError:
                            pass

                if new_for_symbol > 0:
                    symbols_with_new.append(symbol)
                    new_filings_count += new_for_symbol
                    candidate.pending_filings = new_for_symbol

            except Exception as e:
                logger.warning(f"Failed to check filings for {symbol}: {e}")

        self._last_check_at = datetime.now(timezone.utc)

        # HX state was queried at top of function - reuse those values
        # Update is recommended if there's any work to do
        has_new_filings = new_filings_count > 0
        has_pending_analysis = pending_analysis_count > 0
        has_pending_synthesis = pending_synthesis_count > 0

        update_recommended = has_new_filings or has_pending_analysis or has_pending_synthesis

        # Build reason with all pending work
        reasons = []
        if has_new_filings:
            reasons.append(f"{new_filings_count} new FMP filings")
        if has_pending_analysis:
            reasons.append(f"{pending_analysis_count} pending analysis")
        if has_pending_synthesis:
            reasons.append(f"{pending_synthesis_count} pending synthesis")

        reason = ", ".join(reasons) if reasons else "System converged - no pending work"

        # (2026-09-04) The check no longer rolls the market FIFO itself — the
        # fmp_roll flow owns ingest + compaction. Report the durable buffer's
        # live state so the check output keeps its shape honestly.
        market: dict[str, Any] = {"ingested": 0, "errors": [], "owner": "flow:FmpMarketBufferFlow"}
        if self._pool is not None:
            from gaius.engine.services.buffer_store import live_stats

            stats = await live_stats(self._pool, "prospects")
            market["buffer_bytes"] = stats["bytes"]
            market["buffer_entries"] = stats["count"]
        compact = {"skipped": True, "reason": "compaction owned by the fmp_roll flow"}

        return {
            "update_recommended": update_recommended,
            "reason": reason,
            "new_filings_count": new_filings_count,
            "symbols_with_new_filings": symbols_with_new,
            "pending_analysis_count": pending_analysis_count,
            "pending_analysis_by_symbol": pending_analysis,
            "pending_synthesis_count": pending_synthesis_count,
            "pending_synthesis_symbols": list(pending_synthesis.keys()),
            "market_buffer": market,
            "buffer_compact": compact,
        }

    async def run_update(
        self,
        profile: str = "zndx",
        domain: str = "prospecting",
        symbols: list[str] | None = None,
        force: bool = False,
        filings_per_symbol: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run full analysis update by triggering Metaflow ProspectsUpdateFlow.

        Uses Metaflow Runner API for programmatic flow execution with log streaming.
        Delegates to Metaflow for the actual work:
        - SEC filing sync to HX Iceberg
        - Docling extraction
        - Cerebras GLM 4.7 analysis
        - XAI Grok synthesis
        - KB artifact creation

        Cost: ~$0.06/filing (Cerebras) + ~$0.50/synthesis (Grok)

        Args:
            profile: Profile name.
            domain: Domain context.
            symbols: Specific symbols to update (None = all).
            force: Force update even if no new filings.
            filings_per_symbol: Max filings per symbol (None = default 20).

        Yields:
            Progress event dicts with type, progress, message.
        """
        from metaflow import Runner

        # Determine which symbols to process
        target_symbols = symbols or list(self._cached_candidates.keys())

        if not target_symbols:
            yield {
                "type": 10,  # FAILED
                "progress": 0.0,
                "message": "No symbols to process",
            }
            return

        symbols_arg = ",".join(target_symbols)

        yield {
            "type": 0,  # QUEUED
            "progress": 0.0,
            "message": f"Starting ProspectsUpdateFlow for {len(target_symbols)} symbols",
        }

        # Get project root and flow file path
        project_root = Path(__file__).parent.parent.parent.parent.parent
        flow_file = project_root / "src" / "gaius" / "flows" / "prospects" / "update_flow.py"

        from gaius.flows.config import metaflow_child_env
        from gaius.engine.sentinel_claim import (
            YkAdmitError,
            apply_and_admit,
            bind_workload_id,
            delete_flow_sentinel,
        )

        env = metaflow_child_env()
        env["GAIUS_KB_ROOT"] = self._config.kb_root
        proposed = f"prospects-update-{int(time.time())}"
        try:
            wid = bind_workload_id("prospects-update", proposed)
            await asyncio.to_thread(apply_and_admit, wid, "prospects-update")  # off-loop
        except YkAdmitError as e:
            yield {
                "type": 10,
                "progress": 0.0,
                "message": str(e),
            }
            return
        minted = True
        env["GAIUS_YK_APPLICATION_ID"] = wid

        try:
            # Use Metaflow Runner API for programmatic execution
            with Runner(
                str(flow_file),
                show_output=False,  # We'll stream logs ourselves
                env=env,
                cwd=str(project_root),
            ) as runner:
                # Build flow parameters
                flow_params: dict[str, Any] = {
                    "profile": profile,
                    "domain": domain,
                    "symbols": symbols_arg,
                    "force": force,  # Boolean - Metaflow handles type conversion
                }
                if filings_per_symbol is not None:
                    flow_params["filings_per_symbol"] = filings_per_symbol

                # Launch flow asynchronously
                executing = await runner.async_run(**flow_params)

                yield {
                    "type": 1,  # FMP_SYNC_STARTED
                    "progress": 0.05,
                    "message": f"Metaflow ProspectsUpdateFlow started (run_id={executing.run.id})",
                }

                # Stream logs and parse progress
                progress = 0.05
                sitrep_path: str | None = None
                async for _, line in executing.stream_log("stdout"):
                    line = line.strip()
                    if not line:
                        continue

                    # Parse Metaflow output for progress indicators
                    event = self._parse_flow_output(line, progress)
                    if event:
                        progress = event.get("progress", progress)
                        # Capture sitrep_path if present in event
                        if "sitrep_path" in event:
                            sitrep_path = event["sitrep_path"]
                        yield event

                # Wait for completion
                await executing.wait()

                if executing.status == "successful":
                    # Reload state from HX after flow completion
                    await self._reload_state_from_hx(target_symbols)

                    yield {
                        "type": 9,  # COMPLETED
                        "progress": 1.0,
                        "message": "Update completed",
                        "sitrep_path": sitrep_path or "",
                    }
                else:
                    yield {
                        "type": 10,  # FAILED
                        "progress": progress,
                        "message": f"ProspectsUpdateFlow {executing.status}",
                    }

        except ImportError:
            yield {
                "type": 10,  # FAILED
                "progress": 0.0,
                "message": "Metaflow not found. Install with: uv add metaflow",
            }
        except Exception as e:
            logger.error(f"ProspectsUpdateFlow failed: {e}")
            yield {
                "type": 10,  # FAILED
                "progress": 0.0,
                "message": f"Flow execution failed: {e}",
            }
        finally:
            # STZ: this host process's sentinel, never a borrowed claim.
            if minted:
                await asyncio.to_thread(delete_flow_sentinel, wid)

    def _parse_flow_output(self, line: str, current_progress: float) -> dict[str, Any] | None:
        """Parse Metaflow output line and return progress event if recognized.

        Args:
            line: Output line from flow.
            current_progress: Current progress value.

        Returns:
            Progress event dict or None if line not recognized.
        """
        if "Fetching data for" in line:
            symbol = line.split("Fetching data for")[-1].strip().rstrip("...")
            return {
                "type": 1,
                "progress": min(current_progress + 0.02, 0.20),
                "message": f"FMP sync: {symbol}",
                "symbol": symbol,
            }
        elif "Sync complete" in line or "Total filings to sync" in line:
            return {
                "type": 2,  # FMP_SYNC_COMPLETED
                "progress": 0.20,
                "message": line,
            }
        elif "Extracting:" in line:
            return {
                "type": 3,
                "progress": min(current_progress + 0.05, 0.40),
                "message": f"Extraction: {line.split('Extracting:')[-1].strip()}",
            }
        elif "Analyzing" in line and "NEW filings" in line:
            return {
                "type": 3,  # ANALYSIS_STARTED
                "progress": 0.45,
                "message": line,
            }
        elif "persisted)" in line:
            return {
                "type": 4,  # FILING_ANALYZED
                "progress": min(current_progress + 0.05, 0.65),
                "message": line,
            }
        elif "Analysis complete" in line:
            return {
                "type": 4,
                "progress": 0.65,
                "message": line,
            }
        elif "Synthesizing" in line:
            return {
                "type": 5,  # SYNTHESIS_STARTED
                "progress": 0.70,
                "message": line,
            }
        elif "Conviction:" in line:
            return {
                "type": 6,  # SYNTHESIS_COMPLETED
                "progress": min(current_progress + 0.05, 0.85),
                "message": line,
            }
        elif "Created KB artifact" in line:
            return {
                "type": 8,  # KB_WRITE_COMPLETED
                "progress": 0.95,
                "message": line,
            }
        elif "Created sitrep:" in line:
            # Parse sitrep path: "Created sitrep: scratch/2026-01-09/164500_prospects_sitrep.md"
            sitrep_path = line.split("Created sitrep:")[-1].strip()
            return {
                "type": 8,  # KB_WRITE_COMPLETED
                "progress": 0.98,
                "message": f"Sitrep created: {sitrep_path}",
                "sitrep_path": sitrep_path,
            }
        elif "Prospects Update Complete" in line:
            return {
                "type": 9,  # COMPLETED
                "progress": 1.0,
                "message": "Update complete",
            }
        elif line and not line.startswith("["):
            logger.debug(f"Flow output: {line}")
        return None

    async def _reload_state_from_hx(self, symbols: list[str]) -> None:
        """Reload strategy state from HX after Metaflow completes.

        Reads analysis results from HX Iceberg and updates cached strategies.

        Args:
            symbols: Symbols to reload.
        """
        from gaius.hx.edgar import get_edgar_sync
        import json as json_module

        try:
            edgar_sync = get_edgar_sync()

            for symbol in symbols:
                filings = await edgar_sync.get_filings_by_symbol(symbol, limit=5)

                # Find most recent analyzed filing
                for filing in filings:
                    if filing.analyzed_at and filing.analysis_json:
                        try:
                            analysis_data = json_module.loads(filing.analysis_json)

                            # Update cached strategy
                            if symbol not in self._cached_strategies:
                                self._cached_strategies[symbol] = StrategyInfo(symbol=symbol)

                            strategy = self._cached_strategies[symbol]
                            strategy.last_analysis_at = filing.analyzed_at.isoformat()
                            strategy.needs_update = False

                            logger.debug(f"Reloaded strategy for {symbol} from HX")
                            break
                        except Exception as e:
                            logger.warning(f"Failed to parse analysis for {symbol}: {e}")

        except Exception as e:
            logger.warning(f"Failed to reload state from HX: {e}")

    async def _count_pending_analysis(self) -> dict[str, int]:
        """Count filings in HX without analysis (analyzed_at IS NULL).

        Queries the Iceberg table to find filings that have been fetched
        and extracted but not yet analyzed by Cerebras GLM.

        Returns:
            Dict mapping symbol -> count of filings pending analysis.
        """
        try:
            from gaius.hx.edgar import get_edgar_sync

            edgar_sync = get_edgar_sync()
            if not edgar_sync._enabled:
                return {}

            # Get watchlist symbols
            symbols = list(self._cached_candidates.keys())
            if not symbols:
                return {}

            counts: dict[str, int] = {}
            for symbol in symbols:
                # get_unanalyzed returns filings with extracted_text but no analyzed_at
                unanalyzed = await edgar_sync.get_unanalyzed(symbol=symbol, limit=100)
                if unanalyzed:
                    counts[symbol] = len(unanalyzed)

            return counts

        except Exception as e:
            logger.warning(f"Failed to count pending analysis from HX: {e}")
            return {}

    async def _count_pending_synthesis(self, kb_root: str = "build/dev") -> dict[str, bool]:
        """Check which symbols have analyses but no KB synthesis.

        Compares HX analysis state against KB current/prospects/<symbol>/synthesis.md.

        Args:
            kb_root: KB root directory.

        Returns:
            Dict mapping symbol -> True if synthesis is pending (has analysis, no KB).
        """
        try:
            from gaius.hx.edgar import get_edgar_sync

            edgar_sync = get_edgar_sync()
            kb_path = Path(kb_root)

            pending: dict[str, bool] = {}

            for symbol in self._cached_candidates.keys():
                # Check if symbol has any analyzed filings in HX
                filings = await edgar_sync.get_filings_by_symbol(symbol, limit=1)
                has_analysis = any(f.analyzed_at is not None for f in filings)

                # Check if synthesis.md exists in KB
                synthesis_path = kb_path / "current" / "prospects" / symbol.lower() / "synthesis.md"
                has_synthesis = synthesis_path.exists()

                # Pending if has analysis but no synthesis
                if has_analysis and not has_synthesis:
                    pending[symbol] = True

            return pending

        except Exception as e:
            logger.warning(f"Failed to check pending synthesis: {e}")
            return {}

    async def _fetch_sec_filings(
        self,
        symbol: str,
        api_key: str,
        profile: str,
        domain: str,
    ) -> list[dict]:
        """Fetch SEC filings from FMP using the new stable API.

        Uses FMPClient which handles rate limiting and exchange capture.
        The free tier returns latest filings across all companies, filtered client-side.
        """
        config = FMPClientConfig(
            api_key=api_key,
            capture_enabled=True,
        )

        async with FMPClient(config) as client:
            try:
                filings = await client.get_sec_filings(
                    symbol=symbol,
                    source_context={"profile": profile, "domain": domain, "operation": "check"},
                )
                # Convert to dict format for compatibility
                return [
                    {
                        "symbol": f.symbol,
                        "type": f.filing_type,
                        "formType": f.filing_type,
                        "filingDate": f.filing_date,
                        "fillingDate": f.filing_date,  # Legacy field name
                        "acceptedDate": f.accepted_date,
                        "cik": f.cik,
                        "accessionNumber": f.accession_number,
                        "finalLink": f.final_link,
                    }
                    for f in filings
                ]
            except Exception as e:
                raise ProspectsError(
                    f"FMP API error: {e}",
                    guru_code="#PS.00000003.FMPFAIL",
                ) from e

    async def _fetch_institutional_holders(
        self,
        symbol: str,
        api_key: str,
        profile: str,
        domain: str,
    ) -> list[dict]:
        """Fetch institutional holders from FMP using the new stable API.

        Uses FMPClient which handles rate limiting and exchange capture.
        Note: This endpoint requires premium subscription. Raises error if unavailable.
        """
        config = FMPClientConfig(
            api_key=api_key,
            capture_enabled=True,
        )

        async with FMPClient(config) as client:
            try:
                holders = await client.get_institutional_holders(
                    symbol=symbol,
                    source_context={"profile": profile, "domain": domain, "operation": "update"},
                )
                # Convert to dict format for compatibility
                return [
                    {
                        "holder": h.holder_name,
                        "shares": h.shares,
                        "change": h.shares_change,
                        "changePercentage": h.shares_change_pct,
                        "value": h.value_usd,
                        "dateReported": h.filing_date,
                    }
                    for h in holders
                ]
            except Exception as e:
                raise ProspectsError(
                    f"FMP institutional holders API error: {e}",
                    guru_code="#PS.00000003.FMPFAIL",
                ) from e

