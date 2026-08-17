"""ProspectsUpdateFlow - Full billable SEC filing analysis.

Single-responsibility flow for production use with Metaflow Runner API.

Cost: local thinking via Engine/Complete (no Cerebras / XAI)

Pipeline steps:
1. Load watchlist and fetch FMP data
2. Sync SEC filings to HX Iceberg (idempotent)
3. Extract text with docling (unprocessed only)
4. Analyze with local thinking (Engine/Complete)
5. Synthesize with local thinking
6. Create KB zettelkasten artifacts

Usage:
    # Via CLI (preferred)
    uv run gaius-cli --cmd "/prospects update"
    uv run gaius-cli --cmd "/prospects update --limit 2"  # stepwise testing

    # Direct Metaflow
    uv run python src/gaius/flows/prospects/update_flow.py run --filings_per_symbol 2
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

# Import shared utilities from flow.py
from gaius.flows.prospects.flow import load_watchlist

logger = logging.getLogger(__name__)


def load_synthesis_from_kb(kb_root: Path, symbol: str) -> PositionSynthesis | None:
    """Load an existing synthesis from KB for sitrep generation.

    Args:
        kb_root: Path to KB root (e.g., build/dev)
        symbol: Stock symbol (e.g., MTN)

    Returns:
        PositionSynthesis if found and valid, None otherwise
    """
    import yaml

    safe_symbol = safe_filename(symbol).lower()
    synthesis_path = kb_root / f"current/prospects/{safe_symbol}/synthesis.md"

    if not synthesis_path.exists():
        return None

    try:
        content = synthesis_path.read_text()
        # Parse YAML frontmatter
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1])
                return PositionSynthesis(
                    symbol=frontmatter.get("symbol", symbol),
                    company_name=frontmatter.get("title", symbol).replace(" - Investment Synthesis", ""),
                    recommendation=frontmatter.get("recommendation", "hold"),
                    conviction_score=float(frontmatter.get("conviction_score", 0.5)),
                    risk_level=frontmatter.get("risk_level", "medium"),
                    cost_usd=0.0,  # Already paid
                )
    except Exception as e:
        logger.warning(f"Failed to load synthesis for {symbol}: {e}")

    return None


@register_flow("prospects-update")
class ProspectsUpdateFlow(TracedFlow, GaiusFlow):
    """Full billable analysis with LLM synthesis.

    Cost: local thinking via Engine/Complete (no Cerebras / XAI)

    Steps:
    1. Load watchlist and fetch comprehensive FMP data
    2. Sync SEC filings to HX Iceberg
    3. Extract text with docling
    4. Analyze each filing with local thinking
    5. Synthesize overall position with local thinking
    6. Create KB artifacts (Obsidian .md files)

    Triggered when ProspectsCheckFlow recommends update.
    """

    profile = Parameter(
        "profile",
        help="Profile name (empty = use active profile from database)",
        default="",
    )

    domain = Parameter(
        "domain",
        help="Domain context (empty = use active domain from database)",
        default="",
    )

    symbols = Parameter(
        "symbols",
        help="Comma-separated symbols to update (empty = all watchlist)",
        default="",
    )

    force = Parameter(
        "force",
        help="Force re-analysis and re-synthesis even if cached (use when preprocessing improves)",
        default=False,
        type=bool,
    )

    filings_per_symbol = Parameter(
        "filings_per_symbol",
        help="Maximum filings to fetch per symbol (for stepwise testing)",
        default=20,
        type=int,
    )

    @traced_step
    @step
    def start(self):
        """Initialize update and load watchlist."""
        # Resolve profile/domain from database if not specified
        # Database provides: common profile with 'open' domain (Open World Assumption)
        # Fallbacks only apply if database unavailable
        #
        # Note: Metaflow Parameters are immutable after init, so resolved
        # values are stored as data artifacts (_resolved_profile/_resolved_domain)
        # and accessed via the resolved_profile/resolved_domain properties.
        resolved_profile = self.profile
        resolved_domain = self.domain

        if not resolved_profile or not resolved_domain:
            from gaius.storage.profile_ops import get_default_profile_and_domain_sync
            db_profile, db_domain = get_default_profile_and_domain_sync()

            if not resolved_profile:
                # Use database default (is_default=TRUE), fallback to "common"
                resolved_profile = db_profile or "common"
                print(f"Using database default profile: {resolved_profile}")

            if not resolved_domain:
                # Use database active domain for profile
                # 'open' = explicit Open World Assumption (extensible ontology)
                # NULL would mean absence of constraint (different semantics)
                resolved_domain = db_domain or "open"
                print(f"Using database active domain: {resolved_domain}")

        # Store as data artifacts (mutable, unlike Parameters)
        self._resolved_profile = resolved_profile
        self._resolved_domain = resolved_domain

        self.emit_event("prospects.update.started", {
            "profile": self._resolved_profile,
            "domain": self._resolved_domain,
            "force": self.force,
            "correlation_id": self.get_correlation_id(),
        })

        from gaius.flows.config import apply_metaflow_config
        from gaius.flows.lattice import require_signals_metaflow

        apply_metaflow_config()
        require_signals_metaflow()
        print(f"Prospects update starting for profile={self._resolved_profile}, domain={self._resolved_domain}")
        print(f"Filings per symbol limit: {self.filings_per_symbol}")
        print("LLM: local thinking via zndx.engine.v1.Engine/Complete (Signals Metaflow)")

        # Load watchlist
        self.watchlist = load_watchlist()

        # Filter symbols if specified
        if self.symbols:
            target_symbols = set(s.strip().upper() for s in self.symbols.split(","))
            self.watchlist = [
                entry for entry in self.watchlist
                if entry.get("symbol", "").upper() in target_symbols
            ]

        self.symbol_list: list[str] = [
            entry["symbol"] for entry in self.watchlist
            if entry.get("symbol") is not None
        ]
        print(f"Processing {len(self.symbol_list)} symbols")

        # Emit lineage START
        inputs = [
            Dataset(namespace="gaius.config", name="watchlist.conf"),
            Dataset.from_fmp("sec-filings"),
        ]
        self.emit_lineage_start(job_name="prospects_update", inputs=inputs)

        self.next(self.fetch_comprehensive_data)

    @traced_step
    @step
    def fetch_comprehensive_data(self):
        """Fetch comprehensive FMP data for all symbols using FMPClient."""
        source_context = {"profile": self._resolved_profile, "domain": self._resolved_domain, "flow": "update"}

        self.data_by_symbol: dict[str, dict] = {}
        self.filings_metadata: list[dict] = []  # For sync step

        async def fetch_all():
            async with FMPClient() as fmp:
                for symbol in self.symbol_list:
                    print(f"Fetching data for {symbol}...")

                    # Fetch filings using FMPClient (includes accession_number)
                    filings = await fmp.get_sec_filings(symbol=symbol, limit=self.filings_per_symbol)

                    # Holders and profile may require paid subscription
                    try:
                        holders = await fmp.get_institutional_holders(symbol=symbol)
                    except Exception as e:
                        print(f"  {symbol}: holders unavailable ({e})")
                        holders = []

                    try:
                        profile = await fmp.get_company_profile(symbol=symbol)
                    except Exception as e:
                        print(f"  {symbol}: profile unavailable ({e})")
                        profile = None

                    # Convert to dict format for compatibility
                    filing_dicts = [
                        {
                            "accessionNumber": f.accession_number,
                            "type": f.filing_type,
                            "fillingDate": f.filing_date,
                            "finalLink": f.final_link,
                            "cik": f.cik,
                        }
                        for f in filings
                    ]

                    self.data_by_symbol[symbol] = {
                        "filings": filings,
                        "filing_dicts": filing_dicts,
                        "holders": holders[:20] if holders else [],
                        "profile": profile,
                    }

                    # Collect for sync
                    for f in filings:
                        self.filings_metadata.append({
                            "symbol": symbol,
                            "accession_number": f.accession_number,
                            "filing_type": f.filing_type,
                            "filing_date": f.filing_date,
                            "url": f.final_link,
                            "cik": f.cik,
                        })

                    print(f"  {symbol}: {len(filings)} filings, {len(holders) if holders else 0} holders")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(fetch_all())
        finally:
            loop.close()

        print(f"Total filings to sync: {len(self.filings_metadata)}")
        self.next(self.sync_filings)

    @traced_step
    @step
    def sync_filings(self):
        """Sync SEC filings to HX (idempotent - skips existing).

        Uses EdgarClient with sync semantics:
        - Checks if each filing exists by accession_number
        - Only fetches raw HTML for net-new filings
        - Stores in raw.edgar_filings Iceberg table
        """
        self.sync_result: SyncResult | None = None

        async def do_sync():
            async with EdgarClient() as edgar:
                # Group filings by symbol for batch sync
                by_symbol: dict[str, list[dict]] = {}
                for meta in self.filings_metadata:
                    symbol = meta["symbol"]
                    if symbol not in by_symbol:
                        by_symbol[symbol] = []
                    by_symbol[symbol].append(meta)

                total_result = SyncResult(success=True)

                for symbol, metas in by_symbol.items():
                    print(f"Syncing {len(metas)} filings for {symbol}...")

                    for meta in metas:
                        if not meta.get("accession_number"):
                            print(f"  Skipping filing with no accession number")
                            continue

                        try:
                            filing = await edgar.sync_filing(
                                accession_number=meta["accession_number"],
                                url=meta["url"],
                                symbol=symbol,
                                filing_type=meta["filing_type"],
                                cik=meta.get("cik", ""),
                                filing_date=meta.get("filing_date", ""),
                            )
                            total_result.filings_checked += 1
                            if filing:
                                total_result.filings_fetched += 1
                                print(f"  Synced: {meta['accession_number']} ({meta['filing_type']})")
                            else:
                                total_result.filings_skipped += 1
                        except Exception as e:
                            total_result.errors.append(str(e))
                            print(f"  Error syncing {meta['accession_number']}: {e}")

                total_result.success = len(total_result.errors) == 0
                return total_result

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            self.sync_result = loop.run_until_complete(do_sync())
        finally:
            loop.close()

        print(f"\nSync complete: {self.sync_result}")
        print(f"  Checked: {self.sync_result.filings_checked}")
        print(f"  Fetched: {self.sync_result.filings_fetched} (new)")
        print(f"  Skipped: {self.sync_result.filings_skipped} (already exist)")
        if self.sync_result.errors:
            print(f"  Errors: {len(self.sync_result.errors)}")

        self.emit_event("prospects.sync.completed", {
            "profile": self._resolved_profile,
            "filings_checked": self.sync_result.filings_checked,
            "filings_fetched": self.sync_result.filings_fetched,
            "filings_skipped": self.sync_result.filings_skipped,
        })

        self.next(self.extract_filings)

    @traced_step
    @step
    def extract_filings(self):
        """Extract text from filings that haven't been processed.

        Uses docling to convert raw HTML to clean text. Only processes
        filings where extracted_text is NULL (sync semantics).
        """
        self.extraction_count = 0
        self.extracted_filings: list[dict] = []

        async def do_extraction():
            import tempfile
            from pathlib import Path

            edgar_sync = get_edgar_sync()

            # Get filings needing extraction
            unextracted = await edgar_sync.get_unextracted(limit=50)
            print(f"Found {len(unextracted)} filings needing extraction")

            if not unextracted:
                return 0

            # Import docling
            try:
                from docling.document_converter import DocumentConverter
            except ImportError:
                print("  WARNING: docling not available, skipping extraction")
                return 0

            converter = DocumentConverter()
            extracted = 0

            for filing in unextracted:
                try:
                    print(f"  Extracting: {filing.accession_number} ({filing.symbol} {filing.filing_type})")
                    print(f"    Raw HTML: {filing.raw_html_length} bytes")

                    # Write HTML to temp file (docling needs file path)
                    with tempfile.NamedTemporaryFile(
                        mode='w', suffix='.html', delete=False, encoding='utf-8'
                    ) as f:
                        f.write(filing.raw_html)
                        temp_path = f.name

                    try:
                        # Convert with docling
                        result = converter.convert(temp_path)
                        extracted_text = result.document.export_to_markdown()

                        print(f"    Extracted: {len(extracted_text)} chars")

                        # Store for later use in analysis
                        self.extracted_filings.append({
                            "accession_number": filing.accession_number,
                            "symbol": filing.symbol,
                            "filing_type": filing.filing_type,
                            "extracted_text": extracted_text,
                        })

                        # Update extraction in HX (Iceberg upsert)
                        await edgar_sync.update_extraction(
                            filing.accession_number,
                            extracted_text,
                            "docling-v2"
                        )

                        extracted += 1

                    finally:
                        Path(temp_path).unlink(missing_ok=True)

                except Exception as e:
                    print(f"    ERROR extracting {filing.accession_number}: {e}")

            return extracted

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            self.extraction_count = loop.run_until_complete(do_extraction())
        finally:
            loop.close()

        self.emit_event("prospects.extraction.completed", {
            "profile": self._resolved_profile,
            "filings_extracted": self.extraction_count,
        })

        print(f"Extraction: {self.extraction_count} filings processed")

        self.next(self.analyze_filings)

    @traced_step
    @step
    def analyze_filings(self):
        """Analyze filings with local thinking (lattice Complete).

        Uses ProspectsAnalyzer to extract key metrics, highlights, and risks
        from SEC filings. Only analyzes filings that:
        1. Have extracted text (from docling)
        2. Have NOT been analyzed yet (analyzed_at IS NULL)

        This prevents reprocessing already-analyzed filings through paid APIs.
        """
        self.analyses: dict[str, list[FilingAnalysis]] = {}
        self.analysis_errors: list[str] = []
        self.filings_skipped_already_analyzed = 0

        async def do_analysis():
            import json as json_module

            analyzer = ProspectsAnalyzer()

            # Check if Cerebras is available
            if not analyzer.is_available.get("thinking"):
                print("  thinking capability required; Engine/Complete not usable")
                return

            edgar_sync = get_edgar_sync()

            # For each symbol, get filings needing analysis (extracted but not analyzed)
            for symbol, data in self.data_by_symbol.items():
                self.analyses[symbol] = []
                profile = data.get("profile")
                company_name = profile.company_name if profile else symbol

                # Get all extracted filings for this symbol
                all_filings = await edgar_sync.get_filings_by_symbol(symbol, limit=20)

                # Separate into already analyzed and unanalyzed
                already_analyzed = [
                    f for f in all_filings
                    if f.analyzed_at and f.analysis_json
                ]
                unanalyzed = [
                    f for f in all_filings
                    if f.extracted_text and not f.analyzed_at
                ]

                # With --force, re-analyze all filings (including previously analyzed)
                # This allows leveraging improved preprocessing/buffer content
                if self.force:
                    # Include already_analyzed filings in the list to re-analyze
                    filings_to_analyze = [f for f in all_filings if f.extracted_text]
                    print(f"  {symbol}: FORCED re-analysis of {len(filings_to_analyze)} filings ({len(already_analyzed)} were cached)")
                else:
                    # Normal mode: only analyze new filings, load cached results
                    filings_to_analyze = unanalyzed

                    # Deserialize previously analyzed results
                    for f in already_analyzed:
                        if not f.analysis_json:
                            continue
                        try:
                            analysis_data = json_module.loads(f.analysis_json)
                            # Reconstruct FilingAnalysis from stored JSON
                            analysis = FilingAnalysis(
                                symbol=analysis_data.get("symbol", symbol),
                                filing_type=analysis_data.get("filing_type", f.filing_type),
                                filing_date=analysis_data.get("filing_date", f.filing_date),
                                revenue_yoy_change=analysis_data.get("metrics", {}).get("revenue_yoy_change"),
                                gross_margin=analysis_data.get("metrics", {}).get("gross_margin"),
                                net_income_yoy_change=analysis_data.get("metrics", {}).get("net_income_yoy_change"),
                                free_cash_flow=analysis_data.get("metrics", {}).get("free_cash_flow"),
                                key_highlights=analysis_data.get("insights", {}).get("key_highlights", []),
                                risk_factors=analysis_data.get("insights", {}).get("risk_factors", []),
                                guidance_changes=analysis_data.get("insights", {}).get("guidance_changes", []),
                                management_commentary=analysis_data.get("insights", {}).get("management_commentary", ""),
                                model_used=analysis_data.get("model_metadata", {}).get("model_used", f.analysis_model or ""),
                                analysis_at=analysis_data.get("model_metadata", {}).get("analysis_at", ""),
                                cost_usd=0.0,  # Already paid, don't count again
                            )
                            self.analyses[symbol].append(analysis)
                            self.filings_skipped_already_analyzed += 1
                        except (json_module.JSONDecodeError, KeyError) as e:
                            logger.warning(f"Failed to deserialize analysis for {f.accession_number}: {e}")

                    if not filings_to_analyze:
                        if already_analyzed:
                            print(f"  {symbol}: {len(already_analyzed)} filings already analyzed (skipped)")
                        else:
                            print(f"  {symbol}: No filings available for analysis")
                        continue

                    print(f"  {symbol}: Analyzing {len(filings_to_analyze)} NEW filings ({len(already_analyzed)} already done)...")

                if not filings_to_analyze:
                    continue

                for filing in filings_to_analyze:
                    try:
                        analysis = await analyzer.analyze_filing(
                            symbol=symbol,
                            filing_type=filing.filing_type,
                            filing_date=filing.filing_date,
                            filing_content=filing.extracted_text or "",
                            company_name=company_name,
                        )
                        self.analyses[symbol].append(analysis)

                        # Store analysis result in HX to prevent reprocessing
                        analysis_json = json_module.dumps(analysis.to_dict())
                        await edgar_sync.update_analysis(
                            filing.accession_number,
                            analysis_json,
                            analysis.model_used,
                            analysis_reasoning=analysis.reasoning,
                        )

                        print(
                            f"    {filing.filing_type} {filing.filing_date}: "
                            f"${analysis.cost_usd:.4f} (persisted)"
                        )
                    except AnalysisError as e:
                        error_msg = f"{symbol} {filing.filing_type}: {e}"
                        self.analysis_errors.append(error_msg)
                        print(f"    ERROR: {error_msg}")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(do_analysis())
        finally:
            loop.close()

        total_analyzed = sum(len(a) for a in self.analyses.values())
        new_analyzed = total_analyzed - self.filings_skipped_already_analyzed
        total_cost = sum(
            a.cost_usd for analyses in self.analyses.values() for a in analyses
        )

        self.emit_event("prospects.analysis.completed", {
            "profile": self._resolved_profile,
            "symbols_analyzed": len(self.analyses),
            "total_filings": total_analyzed,
            "new_filings_analyzed": new_analyzed,
            "filings_skipped": self.filings_skipped_already_analyzed,
            "total_cost_usd": total_cost,
            "errors": len(self.analysis_errors),
        })

        print(f"Analysis complete: {new_analyzed} NEW filings analyzed, "
              f"{self.filings_skipped_already_analyzed} skipped (already done)")
        print(f"  Total cost this run: ${total_cost:.4f}")
        if self.analysis_errors:
            print(f"  Errors: {len(self.analysis_errors)}")

        self.next(self.synthesize_position)

    @traced_step
    @step
    def synthesize_position(self):
        """Synthesize overall position with local thinking.

        Uses ProspectsAnalyzer to combine multiple filing analyses into
        an investment thesis with conviction score and recommendations.

        Idempotent sync semantics:
        - Runs synthesis for symbols that have analyses but no KB synthesis.md
        - Skips symbols that already have synthesis.md (unless --force)
        - With --force, re-synthesizes everything regardless of KB state
        """
        self.syntheses: dict[str, PositionSynthesis] = {}
        self.synthesis_errors: list[str] = []
        self.synthesis_skipped_already_exists = 0

        # Check which symbols need synthesis (analyses exist, KB does not)
        symbols_needing_synthesis = []
        symbols_skipped_exists = []

        for symbol in self.analyses.keys():
            safe_symbol = safe_filename(symbol).lower()
            synthesis_path = self.kb_root / f"current/prospects/{safe_symbol}/synthesis.md"

            if synthesis_path.exists() and not self.force:
                symbols_skipped_exists.append(symbol)
                self.synthesis_skipped_already_exists += 1
            else:
                symbols_needing_synthesis.append(symbol)

        # Load existing syntheses for skipped symbols (for sitrep accuracy)
        for symbol in symbols_skipped_exists:
            existing = load_synthesis_from_kb(self.kb_root, symbol)
            if existing:
                self.syntheses[symbol] = existing

        if not symbols_needing_synthesis and not self.force:
            print(f"Synthesis: SKIPPED - KB already has synthesis.md for all {len(symbols_skipped_exists)} symbols")
            print("  Use --force to re-synthesize with existing analyses")
            if symbols_skipped_exists:
                for s in symbols_skipped_exists:
                    print(f"    [OK] {s}")

            self.emit_event("prospects.synthesis.skipped", {
                "profile": self._resolved_profile,
                "reason": "kb_already_exists",
                "symbols_skipped": symbols_skipped_exists,
            })

            self.next(self.create_kb_artifacts)
            return

        if symbols_skipped_exists:
            print(f"Synthesis: Skipping {len(symbols_skipped_exists)} symbols (KB exists)")
            for s in symbols_skipped_exists:
                print(f"    [OK] {s}")

        if symbols_needing_synthesis:
            print(f"Synthesis: Processing {len(symbols_needing_synthesis)} symbols")
            for s in symbols_needing_synthesis:
                print(f"    [..] {s}")

        if self.force:
            print("Synthesis: FORCED - re-synthesizing all symbols")

        # Determine which symbols to process
        symbols_to_process = (
            list(self.analyses.keys()) if self.force
            else symbols_needing_synthesis
        )

        async def do_synthesis():
            analyzer = ProspectsAnalyzer()

            # Check if XAI is available
            if not analyzer.is_available.get("thinking"):
                print("  thinking capability required; Engine/Complete not usable")
                return

            for symbol in symbols_to_process:
                analyses = self.analyses.get(symbol, [])
                if not analyses:
                    print(f"  {symbol}: No analyses to synthesize")
                    continue

                data = self.data_by_symbol.get(symbol, {})
                profile = data.get("profile")
                company_name = profile.company_name if profile else symbol
                holders = data.get("holders", [])

                # Build holders context
                holders_context = ""
                if holders:
                    top_holders = holders[:10]
                    holders_lines = [
                        f"- {h.holder[:40]}: {h.shares:,} shares ({h.change:+,} change)"
                        for h in top_holders
                        if hasattr(h, 'holder')
                    ]
                    if holders_lines:
                        holders_context = f"Top institutional holders:\n" + "\n".join(holders_lines)

                print(f"  {symbol}: Synthesizing {len(analyses)} analyses...")

                try:
                    synthesis = await analyzer.synthesize_position(
                        symbol=symbol,
                        company_name=company_name,
                        filing_analyses=analyses,
                        holders_context=holders_context,
                    )
                    self.syntheses[symbol] = synthesis
                    print(
                        f"    Conviction: {synthesis.conviction_score:.2f}, "
                        f"Rec: {synthesis.recommendation}, "
                        f"${synthesis.cost_usd:.4f}"
                    )
                except AnalysisError as e:
                    error_msg = f"{symbol}: {e}"
                    self.synthesis_errors.append(error_msg)
                    print(f"    ERROR: {error_msg}")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(do_synthesis())
        finally:
            loop.close()

        total_cost = sum(s.cost_usd for s in self.syntheses.values())

        self.emit_event("prospects.synthesis.completed", {
            "profile": self._resolved_profile,
            "symbols_synthesized": len(self.syntheses),
            "total_cost_usd": total_cost,
            "errors": len(self.synthesis_errors),
        })

        print(f"Synthesis complete: {len(self.syntheses)} positions, ${total_cost:.4f} total cost")
        if self.synthesis_errors:
            print(f"  Errors: {len(self.synthesis_errors)}")

        self.next(self.create_kb_artifacts)

    @traced_step
    @step
    def create_kb_artifacts(self):
        """Create curated KB artifacts in current/prospects/<symbol>/.

        Directory structure per prospect:
        - current/prospects/<symbol>/synthesis.md - Investment thesis
        - current/prospects/<symbol>/agenda.md - Action items and next steps
        - current/prospects/<symbol>/filings/<type>_<date>.md - Clean filing markdown

        Also creates a zettelkasten note in scratch/ for the daily log.
        """
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H%M%S")

        self.kb_paths: list[str] = []
        kb_root = self.kb_root

        for symbol, synthesis in self.syntheses.items():
            safe_symbol = safe_filename(symbol).lower()
            prospect_dir = f"current/prospects/{safe_symbol}"

            # Get related data
            data = self.data_by_symbol.get(symbol, {})
            profile = data.get("profile")
            filings = data.get("filings", [])
            holders = data.get("holders", [])
            analyses = self.analyses.get(symbol, [])

            # Extract profile fields safely
            company_name = synthesis.company_name or symbol
            sector = profile.sector if profile and hasattr(profile, 'sector') else "Unknown"
            industry = profile.industry if profile and hasattr(profile, 'industry') else "Unknown"

            # === 1. Create synthesis.md ===
            synthesis_content = self._create_synthesis_content(
                symbol, synthesis, analyses, sector, industry, now
            )
            synthesis_path = f"{prospect_dir}/synthesis.md"
            full_path = kb_root / synthesis_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(synthesis_content)
            self.kb_paths.append(synthesis_path)
            print(f"Created: {synthesis_path}")

            # === 2. Create agenda.md ===
            agenda_content = self._create_agenda_content(
                symbol, company_name, synthesis, analyses, now
            )
            agenda_path = f"{prospect_dir}/agenda.md"
            (kb_root / agenda_path).write_text(agenda_content)
            self.kb_paths.append(agenda_path)
            print(f"Created: {agenda_path}")

            # === 3. Create filings/*.md ===
            filings_dir = kb_root / prospect_dir / "filings"
            filings_dir.mkdir(parents=True, exist_ok=True)

            for analysis in analyses:
                filing_content = self._create_filing_content(
                    symbol, company_name, analysis, now
                )
                # Filename: <type>_<date>.md (e.g., 10-K_2025-12-15.md)
                filing_date = analysis.filing_date.split()[0] if analysis.filing_date else "unknown"
                filing_type = safe_filename(analysis.filing_type)
                filing_filename = f"{filing_type}_{filing_date}.md"
                filing_path = f"{prospect_dir}/filings/{filing_filename}"
                (kb_root / filing_path).write_text(filing_content)
                self.kb_paths.append(filing_path)

            print(f"Created: {prospect_dir}/filings/ ({len(analyses)} filings)")

            # === 4. Create scratch zettelkasten note (daily log) ===
            scratch_content = self._create_scratch_note(
                symbol, company_name, synthesis, prospect_dir, now
            )
            scratch_filename = f"{time_str}_prospect_{safe_symbol}.md"
            scratch_path = f"scratch/{date_str}/{scratch_filename}"
            scratch_full_path = kb_root / scratch_path
            scratch_full_path.parent.mkdir(parents=True, exist_ok=True)
            scratch_full_path.write_text(scratch_content)
            self.kb_paths.append(scratch_path)

        self.next(self.generate_base_files)

    @traced_step
    @step
    def generate_base_files(self):
        """Generate Obsidian .base files for structured prospect views.

        Uses orchestrator-coordinated LLM generation:
        1. Orchestrator-8B (local) decides which tool to call
        2. GLM-4.7 (Cerebras) generates YAML (open weights preferred)
        3. Grok-4.1 fast (XAI) diagnoses validation errors
        4. Fallback template as last resort

        Creates:
        - current/prospects/<symbol>/prospect.base - Per-prospect views
        - current/prospects/prospects.base - Root portfolio view
        """
        from gaius.flows.prospects.base_generator import (
            generate_prospect_base,
            generate_root_prospects_base,
        )
        from gaius.kb.base_validator import validate_base

        self.base_files_generated = 0
        self.base_files_fallback = 0
        self.base_generation_cost_usd = 0.0
        self.base_diagnosis_used = 0
        kb_root = self.kb_root

        async def do_generate():
            for symbol, synthesis in self.syntheses.items():
                safe_symbol = safe_filename(symbol).lower()
                prospect_dir = f"current/prospects/{safe_symbol}"
                analyses = self.analyses.get(symbol, [])

                # Get company name
                data = self.data_by_symbol.get(symbol, {})
                profile = data.get("profile")
                company_name = synthesis.company_name or (
                    profile.company_name if profile else symbol
                )

                print(f"  Generating .base for {symbol}...")

                # Generate using orchestrator-coordinated LLM
                result = await generate_prospect_base(
                    symbol=symbol,
                    company_name=company_name,
                    analyses=analyses,
                    synthesis=synthesis,
                )

                if result.success:
                    # Write the .base file
                    base_path = f"{prospect_dir}/prospect.base"
                    full_path = kb_root / base_path
                    full_path.write_text(result.content)
                    self.kb_paths.append(base_path)
                    self.base_files_generated += 1

                    if result.fallback_used:
                        self.base_files_fallback += 1
                        print(f"    Created: {base_path} (fallback template)")
                    else:
                        print(f"    Created: {base_path} (LLM generated, {result.attempts} attempt(s))")
                else:
                    logger.warning(f"Failed to generate .base for {symbol}: {result.validation.errors}")

            # Generate root prospects.base
            if self.syntheses:
                root_content = generate_root_prospects_base(
                    prospect_symbols=list(self.syntheses.keys()),
                    kb_path="current/prospects/",
                )
                root_validation = validate_base(root_content)
                if root_validation.valid:
                    root_path = "current/prospects/prospects.base"
                    (kb_root / root_path).write_text(root_content)
                    self.kb_paths.append(root_path)
                    print(f"  Created: {root_path} (root portfolio view)")
                else:
                    logger.warning(f"Root prospects.base validation failed: {root_validation.errors}")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(do_generate())
        finally:
            loop.close()

        self.emit_event("prospects.base_generation.completed", {
            "profile": self._resolved_profile,
            "base_files_generated": self.base_files_generated,
            "base_files_fallback": self.base_files_fallback,
            "base_generation_cost_usd": getattr(self, 'base_generation_cost_usd', 0.0),
            "base_diagnosis_used": getattr(self, 'base_diagnosis_used', 0),
        })

        print(f"Base generation: {self.base_files_generated} .base files created")
        if self.base_files_fallback > 0:
            print(f"  ({self.base_files_fallback} used fallback template)")

        self.next(self.create_sitrep)

    @traced_step
    @step
    def create_sitrep(self):
        """Create final sitrep zettelkasten note with lineage and metrics.

        This document summarizes:
        - Files fetched from FMP/EDGAR
        - KB artifacts created
        - OpenLineage data (correlation_id, job, run IDs)
        - Quantitative metrics (costs, token counts, latencies)
        """
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H%M%S")

        # Collect metrics from flow state
        metrics = self._collect_pipeline_metrics()

        # Build sitrep content
        sitrep_content = self._create_sitrep_content(metrics, now)

        # Write to scratch directory
        self.sitrep_filename = f"{time_str}_prospects_sitrep.md"
        self.sitrep_path = f"scratch/{date_str}/{self.sitrep_filename}"
        full_path = self.kb_root / self.sitrep_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(sitrep_content)

        self.kb_paths.append(self.sitrep_path)
        print(f"Created sitrep: {self.sitrep_path}")

        self.next(self.end)

    def _create_synthesis_content(
        self, symbol: str, synthesis: PositionSynthesis,
        analyses: list, sector: str, industry: str, now: datetime
    ) -> str:
        """Create synthesis.md content."""
        # Build analysis highlights
        analysis_highlights = []
        for a in analyses:
            highlights = a.key_highlights[:3] if a.key_highlights else []
            risks = a.risk_factors[:2] if a.risk_factors else []
            if highlights or risks:
                filing_link = f"[[filings/{safe_filename(a.filing_type)}_{a.filing_date.split()[0] if a.filing_date else 'unknown'}.md|{a.filing_type}]]"
                analysis_highlights.append(f"\n### {filing_link} ({a.filing_date})")
                if highlights:
                    analysis_highlights.append("\n**Key Points:**")
                    for h in highlights:
                        analysis_highlights.append(f"- {h}")
                if risks:
                    analysis_highlights.append("\n**Risks Identified:**")
                    for r in risks:
                        analysis_highlights.append(f"- {r}")

        return f"""---
title: "{synthesis.company_name} ({symbol}) - Investment Synthesis"
created: {now.isoformat()}
updated: {now.isoformat()}
type: prospect-synthesis
symbol: "{symbol}"
sector: "{sector}"
industry: "{industry}"
conviction_score: {synthesis.conviction_score:.2f}
recommendation: "{synthesis.recommendation}"
risk_level: "{synthesis.risk_level}"
---

# {synthesis.company_name} ({symbol})

> **Recommendation: {synthesis.recommendation.upper()}** | **Conviction: {synthesis.conviction_score:.0%}** | **Risk: {synthesis.risk_level}**

## Investment Thesis

{synthesis.thesis_summary}

## Bull Case

{chr(10).join(f'- {point}' for point in synthesis.bull_case) if synthesis.bull_case else '- No bull case identified'}

## Bear Case

{chr(10).join(f'- {point}' for point in synthesis.bear_case) if synthesis.bear_case else '- No bear case identified'}

## Key Catalysts

{chr(10).join(f'- {catalyst}' for catalyst in synthesis.key_catalysts) if synthesis.key_catalysts else '- No near-term catalysts identified'}

## Key Risks

{chr(10).join(f'- {risk}' for risk in synthesis.key_risks) if synthesis.key_risks else '- Risk assessment pending'}

## Valuation

{synthesis.valuation_notes if synthesis.valuation_notes else 'Valuation analysis not available.'}

## Filing Analysis Summary
{chr(10).join(analysis_highlights) if analysis_highlights else 'No filing analyses available.'}

---

**Related:**
- [[agenda|Action Items]]
- [[filings/|SEC Filings]]

**Metadata:**
- Filings analyzed: {len(analyses)}
- Analysis model: Cerebras GLM 4.7
- Synthesis model: XAI Grok
- Last updated: {now.strftime('%Y-%m-%d %H:%M:%S')}
"""

    def _create_agenda_content(
        self, symbol: str, company_name: str, synthesis: PositionSynthesis,
        analyses: list, now: datetime
    ) -> str:
        """Create agenda.md with action items."""
        # Generate action items based on synthesis
        action_items = []

        # Based on recommendation
        if synthesis.recommendation == "buy":
            action_items.append("- [ ] Review position sizing and entry strategy")
            action_items.append("- [ ] Set price alerts for entry points")
        elif synthesis.recommendation == "sell":
            action_items.append("- [ ] Review exit strategy and timing")
            action_items.append("- [ ] Assess tax implications")
        elif synthesis.recommendation == "hold":
            action_items.append("- [ ] Monitor upcoming earnings/filings")
        else:  # watch
            action_items.append("- [ ] Add to watchlist with price alerts")
            action_items.append("- [ ] Research competitors for comparison")

        # Based on catalysts
        if synthesis.key_catalysts:
            action_items.append(f"- [ ] Set calendar reminders for: {synthesis.key_catalysts[0][:50]}...")

        # Standard items
        action_items.append("- [ ] Review next quarterly filing when available")
        action_items.append("- [ ] Check for insider trading activity")

        return f"""---
title: "{company_name} ({symbol}) - Agenda"
created: {now.isoformat()}
updated: {now.isoformat()}
type: prospect-agenda
symbol: "{symbol}"
---

# {symbol} Action Items

**Current Recommendation:** {synthesis.recommendation.upper()} (Conviction: {synthesis.conviction_score:.0%})

## Immediate Actions

{chr(10).join(action_items)}

## Monitoring Checklist

- [ ] Weekly: Check for 8-K filings
- [ ] Monthly: Review institutional holder changes
- [ ] Quarterly: Analyze 10-Q/10-K when released

## Key Dates to Watch

{chr(10).join(f'- {catalyst}' for catalyst in synthesis.key_catalysts[:3]) if synthesis.key_catalysts else '- No specific dates identified'}

## Notes

_Add research notes and observations here._

---

**Related:**
- [[synthesis|Investment Thesis]]
- [[filings/|SEC Filings]]

**Metadata:**
- Derived from: XAI Grok synthesis
- Last updated: {now.strftime("%Y-%m-%d %H:%M:%S")}
"""

    def _create_filing_content(
        self, symbol: str, company_name: str, analysis: FilingAnalysis, now: datetime
    ) -> str:
        """Create clean markdown for a filing analysis."""
        return f"""---
title: "{symbol} {analysis.filing_type} - {analysis.filing_date}"
created: {now.isoformat()}
type: sec-filing
symbol: "{symbol}"
filing_type: "{analysis.filing_type}"
filing_date: "{analysis.filing_date}"
---

# {symbol} {analysis.filing_type}

**Filing Date:** {analysis.filing_date}
**Company:** {company_name}

## Key Highlights

{chr(10).join(f'- {h}' for h in analysis.key_highlights) if analysis.key_highlights else '- No highlights extracted'}

## Risk Factors

{chr(10).join(f'- {r}' for r in analysis.risk_factors) if analysis.risk_factors else '- No specific risks noted'}

## Guidance Changes

{chr(10).join(f'- {g}' for g in analysis.guidance_changes) if analysis.guidance_changes else '- No guidance changes noted'}

## Management Commentary

{analysis.management_commentary if analysis.management_commentary else '_No significant management commentary extracted._'}

## Financial Metrics

| Metric | Value |
|--------|-------|
| Revenue YoY Change | {f'{analysis.revenue_yoy_change:.1%}' if analysis.revenue_yoy_change else 'N/A'} |
| Gross Margin | {f'{analysis.gross_margin:.1%}' if analysis.gross_margin else 'N/A'} |
| Net Income YoY | {f'{analysis.net_income_yoy_change:.1%}' if analysis.net_income_yoy_change else 'N/A'} |
| Free Cash Flow | {f'${analysis.free_cash_flow:,.0f}' if analysis.free_cash_flow else 'N/A'} |

---

**Analysis Metadata:**
- Model: {analysis.model_used}
- Analyzed: {analysis.analysis_at}
- Cost: ${analysis.cost_usd:.4f}

**Related:**
- [[../synthesis|Investment Thesis]]
- [[../agenda|Action Items]]
"""

    def _create_scratch_note(
        self, symbol: str, company_name: str, synthesis: PositionSynthesis,
        prospect_dir: str, now: datetime
    ) -> str:
        """Create zettelkasten scratch note linking to curated content."""
        return f"""---
title: "Prospect Update: {symbol}"
created: {now.isoformat()}
type: prospect-update
symbol: "{symbol}"
---

# Prospect Update: {company_name} ({symbol})

**Recommendation:** {synthesis.recommendation.upper()}
**Conviction:** {synthesis.conviction_score:.0%}
**Risk:** {synthesis.risk_level}

## Summary

{synthesis.thesis_summary}

## Curated Content

- [[{prospect_dir}/synthesis|Investment Thesis]]
- [[{prospect_dir}/agenda|Action Items]]
- [[{prospect_dir}/filings/|SEC Filings]]

---

_This is a daily log entry. See the curated content above for the full analysis._
"""

    def _collect_pipeline_metrics(self) -> dict:
        """Collect all metrics from flow execution."""
        # Calculate costs
        total_analysis_cost = sum(
            sum(a.cost_usd for a in analyses)
            for analyses in self.analyses.values()
        )
        total_synthesis_cost = sum(
            s.cost_usd for s in self.syntheses.values()
        )

        # Count various artifacts
        filings_analyzed = sum(len(a) for a in self.analyses.values())

        # Calculate skipped vs completed breakdown
        analysis_skipped = self.filings_skipped_already_analyzed
        analysis_completed = filings_analyzed - analysis_skipped
        synthesis_skipped = getattr(self, 'synthesis_skipped_already_exists', 0)
        synthesis_completed = len(self.syntheses)

        # Collect preprocessing statistics from analyses
        total_original_chars = 0
        total_buffer_chars = 0
        total_table_rows = 0
        filings_preprocessed = 0
        for analyses in self.analyses.values():
            for a in analyses:
                if a.preprocess_original_chars > 0:
                    total_original_chars += a.preprocess_original_chars
                    total_buffer_chars += a.preprocess_buffer_chars
                    total_table_rows += a.preprocess_table_rows
                    filings_preprocessed += 1

        return {
            "correlation_id": self.get_correlation_id(),
            "run_id": str(current.run_id) if current.run_id else "unknown",
            "profile": self._resolved_profile,
            "domain": self._resolved_domain,
            "symbols_processed": len(self.syntheses),
            "symbols_total": len(self.analyses),
            "filings_analyzed": filings_analyzed,
            "filings_skipped": analysis_skipped,
            "analysis_completed": analysis_completed,
            "analysis_skipped": analysis_skipped,
            "synthesis_completed": synthesis_completed,
            "synthesis_skipped": synthesis_skipped,
            "kb_artifacts_created": len(self.kb_paths),
            "analysis_cost_usd": total_analysis_cost,
            "synthesis_cost_usd": total_synthesis_cost,
            "total_cost_usd": total_analysis_cost + total_synthesis_cost,
            "fmp_filings_fetched": len(self.filings_metadata),
            "edgar_filings_synced": self.sync_result.filings_fetched if self.sync_result else 0,
            "extraction_count": self.extraction_count,
            "analysis_errors": len(self.analysis_errors),
            "synthesis_errors": len(self.synthesis_errors),
            # Preprocessing statistics
            "preprocess_filings": filings_preprocessed,
            "preprocess_original_chars": total_original_chars,
            "preprocess_buffer_chars": total_buffer_chars,
            "preprocess_table_rows": total_table_rows,
            "preprocess_compression_ratio": (
                total_buffer_chars / total_original_chars
                if total_original_chars > 0 else 0
            ),
            # .base generation statistics
            "base_files_generated": getattr(self, 'base_files_generated', 0),
            "base_files_fallback": getattr(self, 'base_files_fallback', 0),
        }

    def _create_sitrep_content(self, metrics: dict, now: datetime) -> str:
        """Create comprehensive sitrep markdown document."""
        # Build symbol summary table
        symbol_rows = []
        for symbol, synthesis in self.syntheses.items():
            analyses = self.analyses.get(symbol, [])
            symbol_rows.append(
                f"| {symbol} | {synthesis.recommendation.upper()} | "
                f"{synthesis.conviction_score:.0%} | {synthesis.risk_level} | "
                f"{len(analyses)} |"
            )
        symbol_table = "\n".join(symbol_rows) if symbol_rows else "| (none) | - | - | - | - |"

        # Build KB artifacts list (excluding sitrep itself)
        kb_links = []
        for path in self.kb_paths:
            if not path.endswith("_prospects_sitrep.md"):
                kb_links.append(f"- [[{path}]]")
        kb_links_text = "\n".join(kb_links) if kb_links else "- (none)"

        # Build error summary
        errors_text = ""
        if self.analysis_errors or self.synthesis_errors:
            errors_text = "\n## Errors\n\n"
            if self.analysis_errors:
                errors_text += "**Analysis Errors:**\n"
                for err in self.analysis_errors[:5]:
                    errors_text += f"- {err}\n"
            if self.synthesis_errors:
                errors_text += "\n**Synthesis Errors:**\n"
                for err in self.synthesis_errors[:5]:
                    errors_text += f"- {err}\n"

        return f"""---
title: "Prospects Update Sitrep"
created: {now.isoformat()}
type: prospects-sitrep
profile: "{metrics['profile']}"
domain: "{metrics['domain']}"
correlation_id: "{metrics['correlation_id']}"
run_id: "{metrics['run_id']}"
---

# Prospects Update Sitrep

*Generated: {now.strftime("%Y-%m-%d %H:%M:%S")}*
*Correlation ID: `{metrics['correlation_id']}`*

## Summary

| Metric | Value |
|--------|-------|
| Symbols (total) | {metrics['symbols_total']} |
| Symbols Synthesized | {metrics['symbols_processed']} |
| KB Artifacts Created | {metrics['kb_artifacts_created']} |
| Analysis Errors | {metrics['analysis_errors']} |
| Synthesis Errors | {metrics['synthesis_errors']} |

## Work Breakdown

| Step | Completed | Skipped |
|------|-----------|---------|
| Analysis (Cerebras) | {metrics['analysis_completed']} filings | {metrics['analysis_skipped']} cached |
| Synthesis (XAI) | {metrics['synthesis_completed']} symbols | {metrics['synthesis_skipped']} KB exists |
| Extraction (docling) | {metrics['extraction_count']} filings | - |

## Cost Breakdown

| Component | Cost |
|-----------|------|
| Cerebras GLM 4.7 (Analysis) | ${metrics['analysis_cost_usd']:.4f} |
| XAI Grok (Synthesis) | ${metrics['synthesis_cost_usd']:.4f} |
| **Total** | **${metrics['total_cost_usd']:.4f}** |

## Data Sources

| Source | Count |
|--------|-------|
| FMP SEC Filings | {metrics['fmp_filings_fetched']} |
| EDGAR Documents Synced | {metrics['edgar_filings_synced']} |

## Preprocessing (Content Extraction)

| Metric | Value |
|--------|-------|
| Filings Preprocessed | {metrics['preprocess_filings']} |
| Original Content | {metrics['preprocess_original_chars']:,} chars |
| Extracted Buffer | {metrics['preprocess_buffer_chars']:,} chars |
| Compression Ratio | {metrics['preprocess_compression_ratio']:.1%} |
| Table Rows Preserved | {metrics['preprocess_table_rows']} |

## Obsidian .base Generation

| Metric | Value |
|--------|-------|
| .base Files Generated | {metrics['base_files_generated']} |
| Fallback Templates Used | {metrics['base_files_fallback']} |

## Symbols Analyzed

| Symbol | Recommendation | Conviction | Risk | Filings |
|--------|----------------|------------|------|---------|
{symbol_table}

## Lineage

- **Job:** `prospects_update`
- **Run ID:** `{metrics['run_id']}`
- **Correlation ID:** `{metrics['correlation_id']}`

## KB Artifacts Created

{kb_links_text}
{errors_text}
---

**Related:**
- [[current/prospects/|All Prospects]]
"""

    @traced_step
    # type: ignore[unknown-argument] - Metaflow @card decorator accepts type= kwarg
    # but stubs don't declare it; runtime behavior is correct per Metaflow docs
    @card(type="blank")
    @step
    def end(self):
        """Emit lineage and report results."""
        from metaflow.cards import Markdown, Table

        self.emit_event("prospects.update.completed", {
            "profile": self._resolved_profile,
            "domain": self._resolved_domain,
            "symbols_processed": len(self.symbol_list),
            "kb_artifacts": len(self.kb_paths),
            "correlation_id": self.get_correlation_id(),
        })

        # Emit lineage COMPLETE
        outputs = [Dataset.from_kb(path) for path in self.kb_paths]
        self.emit_lineage_complete(outputs)

        from gaius.flows.prospects.publish import publish_from_flow

        published = publish_from_flow(self)
        self.product_tx = published
        if published.get("skipped"):
            print("Signals History: skipped (warehouse not required on this lattice)")
        else:
            print(
                "Signals History: "
                f"{published.get('product_id')} tx={published.get('tx_id')} "
                f"kind={published.get('kind')}"
            )

        # Build summary card
        current.card.append(Markdown("# Prospects Update Summary"))
        current.card.append(Markdown(f"**Profile:** {self._resolved_profile}"))
        current.card.append(Markdown(f"**Domain:** {self._resolved_domain}"))
        current.card.append(Markdown(f"**Symbols Processed:** {len(self.symbol_list)}"))

        if self.kb_paths:
            current.card.append(Markdown("## KB Artifacts Created"))
            rows = [[path] for path in self.kb_paths]
            current.card.append(Table(rows, headers=["Path"]))

        # Cost summary - analyses and syntheses are now proper objects
        total_analysis_cost = sum(
            sum(a.cost_usd for a in analyses)
            for analyses in self.analyses.values()
        )
        total_synthesis_cost = sum(
            s.cost_usd for s in self.syntheses.values()
        )
        total_cost = total_analysis_cost + total_synthesis_cost

        # Count analyzed filings
        total_filings_analyzed = sum(len(a) for a in self.analyses.values())

        current.card.append(Markdown("## Cost Summary"))
        current.card.append(Table([
            ["Analysis (thinking)", f"${total_analysis_cost:.4f}"],
            ["Synthesis (thinking)", f"${total_synthesis_cost:.4f}"],
            ["**Total**", f"**${total_cost:.4f}**"],
        ], headers=["Component", "Cost"]))

        # Add synthesis results to card
        if self.syntheses:
            current.card.append(Markdown("## Position Summaries"))
            synth_rows = [
                [
                    symbol,
                    f"{s.conviction_score:.0%}",
                    s.recommendation.upper(),
                    s.risk_level,
                ]
                for symbol, s in self.syntheses.items()
            ]
            current.card.append(Table(
                synth_rows,
                headers=["Symbol", "Conviction", "Recommendation", "Risk"]
            ))

        print("")
        print("=" * 60)
        print("  Prospects Update Complete")
        print("=" * 60)
        print(f"  Profile:            {self._resolved_profile}")
        print(f"  Domain:             {self._resolved_domain}")
        print(f"  Symbols processed:  {len(self.symbol_list)}")
        print(f"  Filings analyzed:   {total_filings_analyzed}")
        print(f"  Positions synth'd:  {len(self.syntheses)}")
        print(f"  KB artifacts:       {len(self.kb_paths)}")
        print(f"  Analysis cost:      ${total_analysis_cost:.4f}")
        print(f"  Synthesis cost:     ${total_synthesis_cost:.4f}")
        print(f"  Total cost:         ${total_cost:.4f}")
        print("=" * 60)


if __name__ == "__main__":
    apply_metaflow_config()
    ProspectsUpdateFlow()
