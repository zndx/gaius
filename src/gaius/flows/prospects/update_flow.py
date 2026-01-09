"""ProspectsUpdateFlow - Full billable SEC filing analysis.

Single-responsibility flow for production use with Metaflow Runner API.

Cost: ~$0.06/filing (Cerebras GLM 4.7) + ~$0.50/synthesis (XAI Grok)

Pipeline steps:
1. Load watchlist and fetch FMP data
2. Sync SEC filings to HX Iceberg (idempotent)
3. Extract text with docling (unprocessed only)
4. Analyze with Cerebras GLM 4.7 (unanalyzed only)
5. Synthesize with XAI Grok
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


@register_flow("prospects-update")
class ProspectsUpdateFlow(TracedFlow, GaiusFlow):
    """Full billable analysis with LLM synthesis.

    Cost: ~$0.06/filing (Cerebras) + ~$0.50/synthesis (Grok)

    Steps:
    1. Load watchlist and fetch comprehensive FMP data
    2. Sync SEC filings to HX Iceberg
    3. Extract text with docling
    4. Analyze each filing with Cerebras GLM 4.7
    5. Synthesize overall position with XAI Grok
    6. Create KB artifacts (Obsidian .md files)

    Triggered when ProspectsCheckFlow recommends update.
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

    symbols = Parameter(
        "symbols",
        help="Comma-separated symbols to update (empty = all watchlist)",
        default="",
    )

    force = Parameter(
        "force",
        help="Force update even if no new filings",
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
        self.emit_event("prospects.update.started", {
            "profile": self.profile,
            "domain": self.domain,
            "force": self.force,
            "correlation_id": self.get_correlation_id(),
        })

        print(f"Prospects update starting for profile={self.profile}, domain={self.domain}")
        print(f"Filings per symbol limit: {self.filings_per_symbol}")

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
        source_context = {"profile": self.profile, "domain": self.domain, "flow": "update"}

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
            "profile": self.profile,
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
            "profile": self.profile,
            "filings_extracted": self.extraction_count,
        })

        print(f"Extraction: {self.extraction_count} filings processed")

        self.next(self.analyze_filings)

    @traced_step
    @step
    def analyze_filings(self):
        """Analyze filings with Cerebras GLM 4.7.

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
            availability = analyzer.is_available
            if not availability.get("cerebras"):
                print("  WARNING: Cerebras not available, skipping analysis")
                print("  Set CEREBRAS_API_KEY to enable filing analysis")
                return

            edgar_sync = get_edgar_sync()

            # For each symbol, get filings needing analysis (extracted but not analyzed)
            for symbol, data in self.data_by_symbol.items():
                self.analyses[symbol] = []
                profile = data.get("profile")
                company_name = profile.company_name if profile else symbol

                # Query HX for unanalyzed filings for this symbol
                unanalyzed = await edgar_sync.get_unanalyzed(symbol=symbol, limit=5)

                # Also load any previously analyzed filings to include in analyses
                all_filings = await edgar_sync.get_filings_by_symbol(symbol, limit=20)
                already_analyzed = [
                    f for f in all_filings
                    if f.analyzed_at and f.analysis_json
                ]

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

                if not unanalyzed:
                    if already_analyzed:
                        print(f"  {symbol}: {len(already_analyzed)} filings already analyzed (skipped)")
                    else:
                        print(f"  {symbol}: No filings available for analysis")
                    continue

                print(f"  {symbol}: Analyzing {len(unanalyzed)} NEW filings ({len(already_analyzed)} already done)...")

                for filing in unanalyzed:
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
            "profile": self.profile,
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
        """Synthesize overall position with XAI Grok.

        Uses ProspectsAnalyzer to combine multiple filing analyses into
        an investment thesis with conviction score and recommendations.

        Guard against reprocessing:
        - Only runs synthesis if at least one new filing was analyzed this run
        - If all filings were already analyzed (loaded from cache), synthesis is skipped
        - This prevents duplicate XAI Grok calls when re-running the flow
        """
        self.syntheses: dict[str, PositionSynthesis] = {}
        self.synthesis_errors: list[str] = []
        self.synthesis_skipped_no_new_analyses = 0

        # Check if we have any new analyses to synthesize
        new_filings_analyzed = sum(len(a) for a in self.analyses.values()) - self.filings_skipped_already_analyzed

        if new_filings_analyzed == 0 and self.filings_skipped_already_analyzed > 0 and not self.force:
            print("Synthesis: SKIPPED - all filings were already analyzed (no new data)")
            print("  Use --force to re-synthesize with existing analyses")

            self.emit_event("prospects.synthesis.skipped", {
                "profile": self.profile,
                "reason": "no_new_analyses",
                "filings_cached": self.filings_skipped_already_analyzed,
            })

            self.next(self.create_kb_artifacts)
            return

        if self.force and new_filings_analyzed == 0:
            print("Synthesis: FORCED - re-synthesizing with cached analyses")

        async def do_synthesis():
            analyzer = ProspectsAnalyzer()

            # Check if XAI is available
            availability = analyzer.is_available
            if not availability.get("xai"):
                print("  WARNING: XAI not available, skipping synthesis")
                print("  Set XAI_API_KEY to enable position synthesis")
                return

            for symbol, analyses in self.analyses.items():
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
            "profile": self.profile,
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

    @traced_step
    @card(type="blank")  # type: ignore[unknown-argument]
    @step
    def end(self):
        """Emit lineage and report results."""
        from metaflow.cards import Markdown, Table

        self.emit_event("prospects.update.completed", {
            "profile": self.profile,
            "domain": self.domain,
            "symbols_processed": len(self.symbol_list),
            "kb_artifacts": len(self.kb_paths),
            "correlation_id": self.get_correlation_id(),
        })

        # Emit lineage COMPLETE
        outputs = [Dataset.from_kb(path) for path in self.kb_paths]
        self.emit_lineage_complete(outputs)

        # Build summary card
        current.card.append(Markdown("# Prospects Update Summary"))
        current.card.append(Markdown(f"**Profile:** {self.profile}"))
        current.card.append(Markdown(f"**Domain:** {self.domain}"))
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
            ["Analysis (Cerebras)", f"${total_analysis_cost:.4f}"],
            ["Synthesis (Grok)", f"${total_synthesis_cost:.4f}"],
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
        print(f"  Profile:            {self.profile}")
        print(f"  Domain:             {self.domain}")
        print(f"  Symbols processed:  {len(self.symbol_list)}")
        print(f"  Filings analyzed:   {total_filings_analyzed}")
        print(f"  Positions synth'd:  {len(self.syntheses)}")
        print(f"  KB artifacts:       {len(self.kb_paths)}")
        print(f"  Analysis cost:      ${total_analysis_cost:.4f}")
        print(f"  Synthesis cost:     ${total_synthesis_cost:.4f}")
        print(f"  Total cost:         ${total_cost:.4f}")
        print("=" * 60)


if __name__ == "__main__":
    apply_metaflow_config("local")
    ProspectsUpdateFlow()
