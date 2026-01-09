"""ProspectsFlow - FMP API Integration for SEC Filing Analysis.

Two-tier flow architecture:
1. ProspectsCheckFlow: Lightweight daily check ($0)
   - Fetches SEC filing metadata from FMP
   - Compares against last known filings
   - Returns recommendation (update needed or not)
   - Triggered by pg_cron or CLI

2. ProspectsUpdateFlow: Full billable analysis with sync semantics
   - Syncs SEC filings to HX (idempotent - skips existing)
   - Extracts text with docling (only unprocessed filings)
   - Analyzes with Cerebras GLM 4.7 (~$0.06/filing)
   - Synthesizes with XAI Grok (~$0.50/synthesis)
   - Creates KB artifacts (Obsidian .base files)
   - Full lineage tracking via Apache AGE

Sync Semantics:
- Filing sync is idempotent: re-running produces no duplicates
- Deduplication by accession_number (SEC's unique filing ID)
- Extraction phase processes only filings without extracted_text
- Content hash verification for integrity

All FMP API exchanges are captured to Iceberg (raw.fmp_exchange) for:
- Audit trail (financial data provenance)
- Replay (rebuild analysis without API costs)
- Training (GLM 4.7 FMP tool use examples)

Usage:
    # Daily check (via pg_cron or CLI)
    uv run python -m gaius.flows.prospects.flow check --profile zndx --domain prospecting

    # Full update when new filings detected
    uv run python -m gaius.flows.prospects.update_flow run --profile zndx --domain prospecting

    # Via CLI
    uv run gaius-cli --cmd "/prospects check"
    uv run gaius-cli --cmd "/prospects update"
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from metaflow import FlowSpec, Parameter, card, current, step

from gaius.agents.metaagent.telemetry import TracedFlow, traced_step
from gaius.flows import register_flow
from gaius.flows.base import GaiusFlow, safe_filename
from gaius.flows.config import apply_metaflow_config
from gaius.hx.fmp import FMPEndpoint, FMPExchangeRecord, get_fmp_capture
from gaius.hx.lineage.events import Dataset, Job
from gaius.engine.services.edgar_client import EdgarClient
from gaius.engine.services.fmp_client import FMPClient
from gaius.engine.services.prospects_analysis import (
    ProspectsAnalyzer,
    FilingAnalysis,
    PositionSynthesis,
    AnalysisError,
)
from gaius.hx.edgar import EdgarFiling, SyncResult, get_edgar_sync

logger = logging.getLogger(__name__)

# FMP API configuration
FMP_BASE_URL = "https://financialmodelingprep.com/api"


def get_fmp_api_key() -> str:
    """Get FMP API key from environment."""
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        raise RuntimeError(
            "FMP_API_KEY not set.\n"
            "  Guru Meditation: #FMP.00000001.NO_API_KEY\n"
            "  Set FMP_API_KEY environment variable or add to .env"
        )
    return api_key


def load_watchlist(config_path: Path | None = None) -> list[dict]:
    """Load prospect watchlist from HOCON config.

    Args:
        config_path: Path to watchlist.conf (default: config/prospects/watchlist.conf)

    Returns:
        List of watchlist entries with symbol, exchange, company, priority.
    """
    if config_path is None:
        # Path: flow.py → prospects → flows → gaius → src → gaius (project root)
        config_path = Path(__file__).parent.parent.parent.parent.parent / "config" / "prospects" / "watchlist.conf"

    if not config_path.exists():
        raise RuntimeError(
            f"Watchlist config not found: {config_path}\n"
            "  Guru Meditation: #FMP.00000002.NO_WATCHLIST\n"
            "  Create config/prospects/watchlist.conf from watchlist.conf.example"
        )

    try:
        from pyhocon import ConfigFactory
    except ImportError:
        raise RuntimeError(
            "pyhocon not installed.\n"
            "  Guru Meditation: #FMP.00000003.NO_PYHOCON\n"
            "  Install with: uv add pyhocon"
        )

    config = ConfigFactory.parse_file(str(config_path))
    watchlist = config.get("prospects.watchlist", [])

    if not watchlist:
        raise RuntimeError(
            f"No entries in watchlist: {config_path}\n"
            "  Guru Meditation: #FMP.00000004.EMPTY_WATCHLIST\n"
            "  Add entries to prospects.watchlist"
        )

    return list(watchlist)


async def fetch_with_capture(
    url: str,
    endpoint: str,
    symbol: str | None = None,
    params: dict | None = None,
    source_context: dict | None = None,
) -> dict | list | None:
    """Fetch from FMP API with exchange capture.

    All requests/responses are captured to Iceberg for provenance.

    Args:
        url: Full FMP API URL.
        endpoint: FMP endpoint type for categorization.
        symbol: Stock symbol if applicable.
        params: Query parameters.
        source_context: Additional context (profile, domain, etc.).

    Returns:
        JSON response data.
    """
    import httpx

    params = params or {}
    source_context = source_context or {}

    start_time = time.time()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            latency_ms = int((time.time() - start_time) * 1000)

            # Capture exchange regardless of status
            record = FMPExchangeRecord(
                endpoint=endpoint,
                url=str(response.url),
                symbol=symbol,
                params=params,
                response_data=response.json() if response.status_code == 200 else {"error": response.text},
                status_code=response.status_code,
                latency_ms=latency_ms,
                source_context=source_context,
            )
            await get_fmp_capture().capture_fmp(record)

            if response.status_code != 200:
                logger.warning(f"FMP API error {response.status_code} for {endpoint}: {response.text[:200]}")
                return None

            return response.json()

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        logger.error(f"FMP API request failed: {e}")

        # Still capture failed exchange
        record = FMPExchangeRecord(
            endpoint=endpoint,
            url=url,
            symbol=symbol,
            params=params,
            response_data={"error": str(e)},
            status_code=0,
            latency_ms=latency_ms,
            source_context=source_context,
        )
        await get_fmp_capture().capture_fmp(record)

        return None


async def fetch_sec_filings(
    symbol: str,
    api_key: str,
    form_types: list[str] | None = None,
    limit: int = 20,
    source_context: dict | None = None,
) -> list[dict]:
    """Fetch SEC filings for a symbol.

    Args:
        symbol: Stock symbol.
        api_key: FMP API key.
        form_types: Filter by form types (default: 10-K, 10-Q, 8-K).
        limit: Maximum filings to return.
        source_context: Additional context for lineage.

    Returns:
        List of SEC filing records.
    """
    form_types = form_types or ["10-K", "10-Q", "8-K"]

    url = f"{FMP_BASE_URL}/v3/sec_filings/{symbol}"
    params = {
        "apikey": api_key,
        "type": ",".join(form_types),
        "limit": str(limit),
    }

    result = await fetch_with_capture(
        url,
        FMPEndpoint.SEC_FILINGS,
        symbol=symbol,
        params=params,
        source_context=source_context,
    )

    return result if isinstance(result, list) else []


async def fetch_institutional_holders(
    symbol: str,
    api_key: str,
    source_context: dict | None = None,
) -> list[dict]:
    """Fetch institutional holders for a symbol.

    Args:
        symbol: Stock symbol.
        api_key: FMP API key.
        source_context: Additional context for lineage.

    Returns:
        List of institutional holder records.
    """
    url = f"{FMP_BASE_URL}/v3/institutional-holder/{symbol}"
    params = {"apikey": api_key}

    result = await fetch_with_capture(
        url,
        FMPEndpoint.INSTITUTIONAL_HOLDER,
        symbol=symbol,
        params=params,
        source_context=source_context,
    )

    return result if isinstance(result, list) else []


async def fetch_company_profile(
    symbol: str,
    api_key: str,
    source_context: dict | None = None,
) -> dict | None:
    """Fetch company profile for a symbol.

    Args:
        symbol: Stock symbol.
        api_key: FMP API key.
        source_context: Additional context for lineage.

    Returns:
        Company profile record.
    """
    url = f"{FMP_BASE_URL}/v3/profile/{symbol}"
    params = {"apikey": api_key}

    result = await fetch_with_capture(
        url,
        FMPEndpoint.PROFILE,
        symbol=symbol,
        params=params,
        source_context=source_context,
    )

    if isinstance(result, list) and result:
        return result[0]
    return None


@register_flow("prospects-check")
class ProspectsCheckFlow(TracedFlow, GaiusFlow):
    """Lightweight daily check for new SEC filings.

    Cost: ~$0 (no LLM calls, just FMP API + local logic)

    Steps:
    1. Load watchlist from config
    2. Fetch recent SEC filings for each symbol
    3. Compare against last known filings (from DB)
    4. Return recommendation: update needed or not

    Can be triggered by pg_cron for automated daily checks.
    """

    profile = Parameter(
        "profile",
        help="Profile name (e.g., zndx)",
        default="zndx",
    )

    domain = Parameter(
        "domain",
        help="Domain context (e.g., prospecting)",
        default="prospecting",
    )

    @traced_step
    @step
    def start(self):
        """Initialize check and load watchlist."""
        self.emit_event("prospects.check.started", {
            "profile": self.profile,
            "domain": self.domain,
            "correlation_id": self.get_correlation_id(),
        })

        print(f"Prospects check starting for profile={self.profile}, domain={self.domain}")

        # Load watchlist
        self.watchlist = load_watchlist()
        self.symbols: list[str] = [
            entry["symbol"] for entry in self.watchlist
            if entry.get("symbol") is not None
        ]

        print(f"Loaded {len(self.symbols)} symbols from watchlist")

        # Emit lineage START
        self.emit_lineage_start(
            job_name="prospects_check",
            inputs=[Dataset(namespace="gaius.config", name="watchlist.conf")],
        )

        self.next(self.fetch_filings)

    @traced_step
    @step
    def fetch_filings(self):
        """Fetch SEC filings for all watchlist symbols."""
        api_key = get_fmp_api_key()
        source_context = {"profile": self.profile, "domain": self.domain, "flow": "check"}

        self.filings_by_symbol: dict[str, list[dict]] = {}
        self.new_filings: list[dict] = []

        async def fetch_all():
            for symbol in self.symbols:
                filings = await fetch_sec_filings(
                    symbol,
                    api_key,
                    limit=5,  # Just recent filings for check
                    source_context=source_context,
                )
                self.filings_by_symbol[symbol] = filings
                print(f"  {symbol}: {len(filings)} recent filings")

        # Run async in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(fetch_all())
        finally:
            loop.close()

        self.next(self.compare_filings)

    @traced_step
    @step
    def compare_filings(self):
        """Compare filings against last known state."""
        # TODO: Query database for last known filing dates per symbol
        # For now, we'll mark any filings from the last 30 days as potentially new

        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        self.symbols_with_new = []

        for symbol, filings in self.filings_by_symbol.items():
            for filing in filings:
                filing_date_str = filing.get("fillingDate") or filing.get("acceptedDate")
                if filing_date_str:
                    try:
                        # Parse date (FMP uses YYYY-MM-DD format)
                        filing_date = datetime.strptime(filing_date_str[:10], "%Y-%m-%d")
                        filing_date = filing_date.replace(tzinfo=timezone.utc)

                        if filing_date > cutoff:
                            self.new_filings.append({
                                "symbol": symbol,
                                "type": filing.get("type"),
                                "filing_date": filing_date_str,
                                "link": filing.get("finalLink"),
                            })
                            if symbol not in self.symbols_with_new:
                                self.symbols_with_new.append(symbol)
                    except ValueError:
                        pass

        print(f"Found {len(self.new_filings)} filings in last 30 days")
        print(f"Symbols with new filings: {self.symbols_with_new}")

        self.next(self.end)

    @traced_step
    @card(type="blank")  # type: ignore[unknown-argument]
    @step
    def end(self):
        """Emit recommendation and lineage."""
        from metaflow.cards import Markdown, Table

        self.update_recommended = len(self.new_filings) > 0
        self.update_reason = (
            f"{len(self.new_filings)} new filings for {len(self.symbols_with_new)} symbols"
            if self.update_recommended
            else "No new filings detected"
        )

        self.emit_event("prospects.check.completed", {
            "profile": self.profile,
            "domain": self.domain,
            "update_recommended": self.update_recommended,
            "new_filings_count": len(self.new_filings),
            "correlation_id": self.get_correlation_id(),
        })

        # Emit lineage COMPLETE
        outputs = [
            Dataset(namespace="gaius.prospects", name=f"check:{self.profile}:{datetime.now().strftime('%Y%m%d')}"),
        ]
        self.emit_lineage_complete(outputs)

        # Build summary card
        current.card.append(Markdown("# Prospects Check Summary"))
        current.card.append(Markdown(f"**Profile:** {self.profile}"))
        current.card.append(Markdown(f"**Domain:** {self.domain}"))
        current.card.append(Markdown(f"**Update Recommended:** {'Yes' if self.update_recommended else 'No'}"))

        if self.new_filings:
            current.card.append(Markdown("## New Filings"))
            rows = [
                [f["symbol"], f["type"], f["filing_date"]]
                for f in self.new_filings[:10]
            ]
            current.card.append(Table(rows, headers=["Symbol", "Type", "Date"]))

        print("")
        print("=" * 60)
        print("  Prospects Check Complete")
        print("=" * 60)
        print(f"  Profile:            {self.profile}")
        print(f"  Symbols checked:    {len(self.symbols)}")
        print(f"  New filings:        {len(self.new_filings)}")
        print(f"  Update recommended: {self.update_recommended}")
        print(f"  Reason:             {self.update_reason}")
        print("=" * 60)


# NOTE: ProspectsUpdateFlow has been moved to update_flow.py for clean single-flow-per-file
# design. This is required by the Metaflow Runner API which expects one FlowSpec per file.


if __name__ == "__main__":
    import sys

    apply_metaflow_config("local")

    # Simple CLI dispatch - only check flow is in this file
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "check":
            ProspectsCheckFlow()
        elif command == "update":
            print("ProspectsUpdateFlow has been moved to update_flow.py")
            print("Run: uv run python -m gaius.flows.prospects.update_flow run")
            sys.exit(1)
        else:
            print(f"Unknown command: {command}")
            print("Usage: python -m gaius.flows.prospects.flow check")
            sys.exit(1)
    else:
        print("Usage: python -m gaius.flows.prospects.flow check")
        print("For update flow: uv run python -m gaius.flows.prospects.update_flow run")
        sys.exit(1)
