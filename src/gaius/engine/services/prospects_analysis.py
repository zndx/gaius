"""Prospects analysis via local thinking (Signals lattice Engine/Complete).

Cerebras GLM and XAI Grok are not on this path. Metaflow steps call
``gaius.flows.lattice.complete`` so RKE2 tasks hit host :50051.

The analysis pipeline:
1. Parse SEC filings (10-K, 10-Q, 8-K)
2. Extract key metrics and risk factors via GLM 4.7
3. Synthesize cross-filing insights via Grok
4. Generate conviction score and thesis

Guru Meditation Codes:
- #PA.00000001.CEREBFAIL: Cerebras analysis failed
- #PA.00000002.XAIFAIL: XAI synthesis failed
- #PA.00000003.PARSEFAIL: Filing parse failed
- #PA.00000004.NOPROVIDER: No LLM provider available
- #PA.00000005.TOKENLIMIT: Approaching or hit max_tokens limit
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from gaius.flows.prospects.filing_preprocessor import (
    PreprocessedFiling,
    preprocess_filing,
)
from gaius.flows.prospects.tables import detect_tables, tables_text
from gaius.flows.prospects.windows import admitted_text, scan_windows
from gaius.core.budgets import LONG_FORM_MAX_TOKENS

logger = logging.getLogger(__name__)

# GLM 4.7 token limits
# GLM supports up to 40k tokens, we use 16k for headroom
GLM_MAX_TOKENS = 16384
GLM_TOKEN_WARNING_THRESHOLD = 0.8  # Warn at 80% usage


def _emit_token_usage_event(
    symbol: str,
    filing_type: str,
    output_tokens: int,
    max_tokens: int,
    is_truncated: bool = False,
) -> None:
    """Emit OpenTelemetry event for token usage monitoring.

    Helps detect when we're approaching or hitting the token limit,
    so we can increase GLM_MAX_TOKENS if it becomes a bottleneck.

    Args:
        symbol: Stock symbol.
        filing_type: Filing type (10-K, 10-Q, 8-K).
        output_tokens: Tokens used in response.
        max_tokens: Maximum tokens configured.
        is_truncated: Whether response appears truncated.
    """
    usage_ratio = output_tokens / max_tokens if max_tokens > 0 else 0

    # Log warning if approaching limit
    if usage_ratio >= GLM_TOKEN_WARNING_THRESHOLD or is_truncated:
        logger.warning(
            f"GLM token usage high for {symbol} {filing_type}: "
            f"{output_tokens:,}/{max_tokens:,} ({usage_ratio:.1%})"
            f"{' [TRUNCATED]' if is_truncated else ''}"
        )

    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span.is_recording():
            event_name = (
                "prospects.analysis.token_limit_hit"
                if is_truncated
                else "prospects.analysis.token_usage_high"
                if usage_ratio >= GLM_TOKEN_WARNING_THRESHOLD
                else "prospects.analysis.token_usage"
            )
            span.add_event(
                event_name,
                {
                    "symbol": symbol,
                    "filing_type": filing_type,
                    "output_tokens": output_tokens,
                    "max_tokens": max_tokens,
                    "usage_ratio": round(usage_ratio, 3),
                    "is_truncated": is_truncated,
                    "guru_code": "#PA.00000005.TOKENLIMIT" if is_truncated else "",
                },
            )
    except ImportError:
        pass  # OTel not available
    except Exception as e:
        logger.debug(f"Failed to emit OTel token usage event: {e}")


class AnalysisError(Exception):
    """Analysis error with Guru Meditation code."""

    def __init__(self, message: str, guru_code: str | None = None):
        super().__init__(message)
        self.guru_code = guru_code


@dataclass
class FilingAnalysis:
    """Analysis result for a single SEC filing."""

    symbol: str
    filing_type: str  # 10-K, 10-Q, 8-K
    filing_date: str

    # Extracted metrics
    revenue_yoy_change: float | None = None
    gross_margin: float | None = None
    net_income_yoy_change: float | None = None
    free_cash_flow: float | None = None

    # Extracted insights
    key_highlights: list[str] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
    guidance_changes: list[str] = field(default_factory=list)
    management_commentary: str = ""

    # Model metadata
    model_used: str = ""
    analysis_at: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    # Chain-of-thought reasoning (for distillation training data)
    reasoning: str = ""

    # Preprocessing statistics (from filing_preprocessor)
    preprocess_original_chars: int = 0
    preprocess_buffer_chars: int = 0
    preprocess_table_rows: int = 0
    preprocess_sections: list[str] = field(default_factory=list)

    # Preprocessed content buffer (for synthesis context)
    # This is the compact buffer sent to GLM, preserved for Grok synthesis
    preprocessed_buffer: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "symbol": self.symbol,
            "filing_type": self.filing_type,
            "filing_date": self.filing_date,
            "metrics": {
                "revenue_yoy_change": self.revenue_yoy_change,
                "gross_margin": self.gross_margin,
                "net_income_yoy_change": self.net_income_yoy_change,
                "free_cash_flow": self.free_cash_flow,
            },
            "insights": {
                "key_highlights": self.key_highlights,
                "risk_factors": self.risk_factors,
                "guidance_changes": self.guidance_changes,
                "management_commentary": self.management_commentary,
            },
            "model_metadata": {
                "model_used": self.model_used,
                "analysis_at": self.analysis_at,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cost_usd": self.cost_usd,
            },
            # Chain-of-thought for distillation
            "reasoning": self.reasoning,
            # Preprocessing statistics
            "preprocessing": {
                "original_chars": self.preprocess_original_chars,
                "buffer_chars": self.preprocess_buffer_chars,
                "table_rows": self.preprocess_table_rows,
                "sections": self.preprocess_sections,
            },
        }


@dataclass
class PositionSynthesis:
    """Synthesis result combining multiple filing analyses."""

    symbol: str
    company_name: str

    # Conviction and recommendation
    conviction_score: float = 0.0  # 0-1 scale
    recommendation: str = "hold"  # buy, hold, sell, watch

    # Thesis components
    thesis_summary: str = ""
    bull_case: list[str] = field(default_factory=list)
    bear_case: list[str] = field(default_factory=list)
    key_catalysts: list[str] = field(default_factory=list)

    # Risk assessment
    risk_level: str = "medium"  # low, medium, high
    key_risks: list[str] = field(default_factory=list)

    # Valuation notes
    valuation_notes: str = ""

    # Rubric-bearing fields (prospects_intelligence objective, judge items
    # 'change' and 'allocation' — 0/1 on every verification 2026-09-02/03):
    # what moved since the prior brief, the rebalancing/allocation call
    # under switching costs, and the evidence the synthesis lacked.
    change_since_prior: str = ""
    rebalancing_call: dict[str, Any] = field(default_factory=dict)
    input_gaps: list[str] = field(default_factory=list)

    # Model metadata
    model_used: str = ""
    synthesis_at: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "conviction_score": self.conviction_score,
            "recommendation": self.recommendation,
            "thesis": {
                "summary": self.thesis_summary,
                "bull_case": self.bull_case,
                "bear_case": self.bear_case,
                "key_catalysts": self.key_catalysts,
            },
            "risk": {
                "level": self.risk_level,
                "key_risks": self.key_risks,
            },
            "valuation_notes": self.valuation_notes,
            "model_metadata": {
                "model_used": self.model_used,
                "synthesis_at": self.synthesis_at,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cost_usd": self.cost_usd,
            },
        }


# Cerebras GLM 4.7 pricing (approximate)
CEREBRAS_INPUT_PRICE_PER_1K = 0.00006  # $0.06 per 1M input tokens
CEREBRAS_OUTPUT_PRICE_PER_1K = 0.00024  # $0.24 per 1M output tokens

# XAI Grok pricing (approximate)
# Grok 4.1 Fast pricing (25x cheaper than Grok-3 on input)
XAI_INPUT_PRICE_PER_1K = 0.0002  # $0.20 per 1M input tokens
XAI_OUTPUT_PRICE_PER_1K = 0.0005  # $0.50 per 1M output tokens


def _calculate_cerebras_cost(input_tokens: int, output_tokens: int) -> float:
    """Calculate Cerebras cost in USD."""
    return (
        (input_tokens / 1000) * CEREBRAS_INPUT_PRICE_PER_1K +
        (output_tokens / 1000) * CEREBRAS_OUTPUT_PRICE_PER_1K
    )


def _calculate_xai_cost(input_tokens: int, output_tokens: int) -> float:
    """Calculate XAI cost in USD."""
    return (
        (input_tokens / 1000) * XAI_INPUT_PRICE_PER_1K +
        (output_tokens / 1000) * XAI_OUTPUT_PRICE_PER_1K
    )


# System prompts for analysis
# Note: GLM 4.7 requires explicit language instruction per migration guide
FILING_ANALYSIS_SYSTEM_PROMPT = """You are a financial analyst specializing in SEC filing analysis.
Always respond in English.

Analyze the provided SEC filing and extract key information.

For 10-K (annual) and 10-Q (quarterly) reports, focus on:
1. Revenue and profit trends (year-over-year or quarter-over-quarter)
2. Margin analysis (gross margin, operating margin)
3. Cash flow and liquidity
4. Key risk factors (new or elevated risks)
5. Management guidance and forward-looking statements
6. Any unusual items or one-time charges

For 8-K reports, focus on:
1. Nature of the material event
2. Financial impact if disclosed
3. Market implications
4. Management commentary

Respond with a JSON object containing your analysis."""

FILING_ANALYSIS_USER_TEMPLATE = """Analyze this SEC {filing_type} filing for {symbol}:

Filing Date: {filing_date}
Company: {company_name}

Key sections from the filing:
{filing_content}

Provide your analysis as a JSON object."""

# JSON schema for structured output enforcement
FILING_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "metrics": {
            "type": "object",
            "properties": {
                "revenue_yoy_change": {"type": ["number", "null"]},
                "gross_margin": {"type": ["number", "null"]},
                "net_income_yoy_change": {"type": ["number", "null"]},
                "free_cash_flow": {"type": ["number", "null"]},
            },
            "required": ["revenue_yoy_change", "gross_margin", "net_income_yoy_change", "free_cash_flow"],
            "additionalProperties": False,
        },
        "key_highlights": {
            "type": "array",
            "items": {"type": "string"},
        },
        "risk_factors": {
            "type": "array",
            "items": {"type": "string"},
        },
        "guidance_changes": {
            "type": "array",
            "items": {"type": "string"},
        },
        "management_commentary": {"type": "string"},
    },
    "required": ["metrics", "key_highlights", "risk_factors", "guidance_changes", "management_commentary"],
    "additionalProperties": False,
}

SYNTHESIS_SYSTEM_PROMPT = """You are a senior investment analyst synthesizing multiple SEC filings into an investment thesis.

You will receive:
1. GLM-extracted analyses with key metrics and highlights from each filing
2. Original preprocessed filing content (MD&A sections, financial tables, risk factors)

Use BOTH sources to produce a comprehensive investment thesis:
- The GLM analyses provide structured insights and metrics
- The original filing content allows you to find additional details, verify claims, and extract specific numbers

Include:
1. Overall conviction score (0.0 to 1.0, where 1.0 = highest conviction)
2. Buy/Hold/Sell/Watch recommendation
3. Bull and bear cases with SPECIFIC metrics (percentages, dollar amounts, growth rates)
4. Key catalysts to watch
5. Risk assessment
6. Valuation perspective
7. WHAT CHANGED since the prior thesis (you are given the brief the reader last
   saw): name the concrete deltas — new filings, metrics that moved, catalysts
   that fired or lapsed. "No material change since <date>" is a first-class,
   supported answer; never restate the old thesis as if it were news.
   Distinguish a change IN THE COMPANY (results, guidance, deals, capital
   actions, management, regulatory) from a change in OUR EVIDENCE (a filing
   we now hold): only the former counts as change; label the latter as
   evidence, never as news. A brief whose only delta is "we now have data" says
   so in one line and moves on.
8. THE REBALANCING CALL. The reader manages a portfolio under switching costs
   (transaction costs, taxes, attention). State an explicit allocation decision:
   action (hold-in-band | add | trim | exit | watch), the band or no-trade
   region that decision sits in, the review cadence (when to look again and
   what event would justify looking earlier), WHOSE cadence this belongs to —
   daily, weekly, quarterly, or explicitly nobody's (an attention allocation,
   not just a date), and the switching-cost-aware rationale. "No action
   warranted; stay inside the band" is a fully supported conclusion — silence
   is not.
9. INPUT GAPS. If the evidence is thin (no recent filings, no holders data,
   stale news), say so explicitly and keep the call proportionate; never fill a
   gap with generic prose.

Be specific and actionable. Support conclusions with evidence from the filings."""

SYNTHESIS_USER_TEMPLATE = """Synthesize these filing analyses for {symbol} ({company_name}):

## GLM Filing Analyses (structured insights):
{analyses_json}

## Original Filing Content (preprocessed MD&A, financial tables, risk factors):
{filing_content}

## Institutional Holders Context:
{holders_context}

## Prior Thesis (the brief the reader last saw — compute deltas against THIS):
{prior_thesis}

Use both the GLM analyses AND the original filing content to produce a comprehensive synthesis.
The original content has specific numbers and details that may not be in the GLM summaries.

Produce a synthesis as JSON with this structure:
{{
    "conviction_score": <0.0 to 1.0>,
    "recommendation": "<buy|hold|sell|watch>",
    "thesis_summary": "<2-3 sentence investment thesis>",
    "bull_case": ["point 1 with specific metrics", "point 2", ...],
    "bear_case": ["point 1 with specific metrics", "point 2", ...],
    "key_catalysts": ["catalyst 1", ...],
    "risk_level": "<low|medium|high>",
    "key_risks": ["risk 1", "risk 2", ...],
    "valuation_notes": "<brief valuation perspective with specific multiples if available>",
    "change_since_prior": "<concrete deltas vs the prior thesis, or 'No material change since <date>: ...'>",
    "rebalancing_call": {{
        "action": "<hold-in-band|add|trim|exit|watch>",
        "band": "<target weight range or no-trade region, e.g. 'hold 2-3% of book; no trade inside'>",
        "review_cadence": "<when to re-evaluate and which event justifies looking earlier>",
        "owner_cadence": "<daily | weekly | quarterly | nobody — whose attention cadence this belongs to, and why>",
        "rationale": "<switching-cost-aware reasoning in 1-2 sentences>"
    }},
    "input_gaps": ["<evidence that was missing or stale>", ...]
}}"""


def _as_str_list_local(v: object) -> list[str]:
    """Coerce a model-emitted list-ish value to list[str] (never raise)."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, dict):
        return [f"{k}: {val}" for k, val in v.items()]
    try:
        return [str(x) for x in v if str(x).strip()]  # type: ignore[union-attr]
    except TypeError:
        return [str(v)]


def _parse_json_object(raw: str) -> dict[str, Any]:
    content = (raw or "").strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    start = content.find("{")
    end = content.rfind("}") + 1
    if start < 0 or end <= start:
        raise AnalysisError(
            f"thinking returned no JSON object: {content[:300]}",
            guru_code="#PA.00000003.PARSEFAIL",
        )
    try:
        data = json.loads(content[start:end])
    except json.JSONDecodeError as e:
        raise AnalysisError(
            f"Failed to parse thinking JSON: {e}\nResponse: {content[:500]}",
            guru_code="#PA.00000003.PARSEFAIL",
        ) from e
    if not isinstance(data, dict):
        raise AnalysisError(
            f"thinking JSON was {type(data).__name__}, not object",
            guru_code="#PA.00000003.PARSEFAIL",
        )
    return data


def _thinking_complete(
    prompt: str,
    *,
    system_prompt: str,
    json_schema: dict[str, Any] | None,
    max_tokens: int,
) -> Any:
    from gaius.flows.lattice import complete

    return complete(
        prompt,
        capability="thinking",
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=0.3,
        json_schema=json_schema,
        # Generous outer net (progress-over-timeouts): a synthesis
        # across 20 filing analyses legitimately reasons past 10 min
        # on thinking (2026-09-02: CHTR synthesis DEADLINE_EXCEEDED at
        # exactly 600s after a clean 3h analysis pass). Real engine
        # death is caught by vLLM stall supervision, not this deadline.
        timeout_s=1800.0,
    )


class ProspectsAnalyzer:
    """Filing analysis and position synthesis on local thinking."""

    def __init__(self, **_: object):
        # No remote backends. Extra kwargs ignored for call-site compatibility.
        return

    @property
    def is_available(self) -> dict[str, bool]:
        return {"thinking": True, "cerebras": False, "xai": False}

    async def analyze_filing(
        self,
        symbol: str,
        filing_type: str,
        filing_date: str,
        filing_content: str,
        company_name: str = "",
        use_preprocessing: bool = True,
    ) -> FilingAnalysis:
        """Analyze a single SEC filing using Cerebras GLM 4.7.

        Args:
            symbol: Stock symbol.
            filing_type: Filing type (10-K, 10-Q, 8-K).
            filing_date: Filing date string.
            filing_content: Extracted filing text content.
            company_name: Company name for context.
            use_preprocessing: If True, use sliding window preprocessing for
                large filings to extract salient content. Default True.

        Returns:
            FilingAnalysis with extracted insights.

        Raises:
            AnalysisError: If analysis fails.
        """
        # Aegir-grain windows + table detect, then local thinking.
        # 30k-char keyword compact is no longer the analysis input.
        encode_offsets = None
        if use_preprocessing:
            from gaius.flows.prospects.windows import colbert_offsets

            encode_offsets = colbert_offsets

        scan = scan_windows(filing_content, encode_offsets=encode_offsets)
        tables = detect_tables(filing_content)
        window_blob = admitted_text(scan)
        table_blob = tables_text(tables)
        analysis_text = "\n\n".join(p for p in (window_blob, table_blob) if p)
        if not analysis_text:
            analysis_text = filing_content[:200_000]
        preprocessed = PreprocessedFiling(
            compact_buffer=analysis_text,
            original_length=len(filing_content),
            buffer_length=len(analysis_text),
            sections_detected=["windows", "tables"] if tables or scan.windows else [],
            table_rows_in_buffer=sum(t.rows for t in tables),
            windows_selected=sum(1 for w in scan.windows if w.admitted),
        )
        logger.info(
            "Prospects compact input %s %s: %s chars (%s windows, %s tables)",
            symbol,
            filing_type,
            f"{len(analysis_text):,}",
            preprocessed.windows_selected,
            len(tables),
        )

        # Prepare messages
        user_content = FILING_ANALYSIS_USER_TEMPLATE.format(
            filing_type=filing_type,
            symbol=symbol,
            filing_date=filing_date,
            company_name=company_name or symbol,
            filing_content=analysis_text,
        )

        response = _thinking_complete(
            user_content,
            system_prompt=FILING_ANALYSIS_SYSTEM_PROMPT,
            json_schema=FILING_ANALYSIS_SCHEMA,
            max_tokens=GLM_MAX_TOKENS,
        )

        data = _parse_json_object(response.text)
        metrics: dict[str, Any] = data.get("metrics", {})

        analysis = FilingAnalysis(
            symbol=symbol,
            filing_type=filing_type,
            filing_date=filing_date,
            revenue_yoy_change=metrics.get("revenue_yoy_change"),
            gross_margin=metrics.get("gross_margin"),
            net_income_yoy_change=metrics.get("net_income_yoy_change"),
            free_cash_flow=metrics.get("free_cash_flow"),
            key_highlights=data.get("key_highlights", []),
            risk_factors=data.get("risk_factors", []),
            guidance_changes=data.get("guidance_changes", []),
            management_commentary=data.get("management_commentary", ""),
            model_used=response.model or "thinking",
            analysis_at=datetime.now(timezone.utc).isoformat(),
            input_tokens=response.prompt_tokens,
            output_tokens=response.completion_tokens,
            cost_usd=0.0,
            reasoning=response.reasoning_content or "",
            preprocess_original_chars=preprocessed.original_length,
            preprocess_buffer_chars=preprocessed.buffer_length,
            preprocess_table_rows=preprocessed.table_rows_in_buffer,
            preprocess_sections=preprocessed.sections_detected,
            preprocessed_buffer=analysis_text,
        )

        logger.info(
            f"Analyzed {filing_type} for {symbol}: "
            f"{len(analysis.key_highlights)} highlights, "
            f"{len(analysis.risk_factors)} risks"
        )

        is_truncated = response.finish_reason == "length"
        _emit_token_usage_event(
            symbol=symbol,
            filing_type=filing_type,
            output_tokens=response.completion_tokens,
            max_tokens=GLM_MAX_TOKENS,
            is_truncated=is_truncated,
        )

        return analysis

    async def synthesize_position(
        self,
        symbol: str,
        company_name: str,
        filing_analyses: list[FilingAnalysis],
        holders_context: str = "",
        prior_thesis: str = "",
    ) -> PositionSynthesis:
        """Synthesize filing analyses into a position thesis (thinking lane).

        ``prior_thesis`` is the brief the reader last saw; the synthesis
        computes its "what changed" against it and makes an explicit
        rebalancing call under switching costs (rubric items 'change' and
        'allocation').

        Args:
            symbol: Stock symbol.
            company_name: Company name.
            filing_analyses: List of filing analyses to synthesize.
            holders_context: Optional institutional holders context.

        Returns:
            PositionSynthesis with investment thesis.

        Raises:
            AnalysisError: If synthesis fails.
        """
        if not filing_analyses:
            raise AnalysisError(
                "No filing analyses to synthesize",
                guru_code="#PA.00000003.PARSEFAIL",
            )

        # Prepare analyses JSON (without the large buffer content)
        analyses_json = json.dumps(
            [a.to_dict() for a in filing_analyses],
            indent=2,
        )

        # Collect preprocessed filing content for Grok's context
        # Grok 4.1 Fast has 2M token context - we can be very generous
        # Budget: ~500K tokens for filing content (~2M chars), leaving room for analyses + output
        filing_content_parts: list[str] = []
        total_content_chars = 0
        max_content_chars = 800_000  # thinking 262k ≈ unique-text budget, not 2M Grok

        for analysis in filing_analyses:
            if analysis.preprocessed_buffer and total_content_chars < max_content_chars:
                header = f"\n### {analysis.filing_type} ({analysis.filing_date})\n"
                remaining = max_content_chars - total_content_chars - len(header)
                if remaining > 1000:  # Only include if we have meaningful space
                    # Include the full preprocessed buffer - no truncation needed with 2M context
                    buffer_portion = analysis.preprocessed_buffer[:remaining]
                    filing_content_parts.append(header + buffer_portion)
                    total_content_chars += len(header) + len(buffer_portion)

        filing_content = "".join(filing_content_parts) if filing_content_parts else "No preprocessed content available."

        user_content = SYNTHESIS_USER_TEMPLATE.format(
            symbol=symbol,
            company_name=company_name,
            analyses_json=analyses_json,
            filing_content=filing_content,
            holders_context=holders_context or "No institutional holder data available.",
            prior_thesis=prior_thesis or "No prior brief on record — this is the first thesis; say so.",
        )

        logger.info(
            f"Synthesis context for {symbol}: "
            f"filing_content={len(filing_content):,} chars, "
            f"analyses={len(analyses_json):,} chars"
        )

        response = _thinking_complete(
            user_content,
            system_prompt=SYNTHESIS_SYSTEM_PROMPT,
            json_schema=None,
            max_tokens=LONG_FORM_MAX_TOKENS,
        )
        data = _parse_json_object(response.text)
        synthesis = PositionSynthesis(
            symbol=symbol,
            company_name=company_name,
            conviction_score=float(data.get("conviction_score", 0.5)),
            recommendation=data.get("recommendation", "hold"),
            thesis_summary=data.get("thesis_summary", ""),
            bull_case=data.get("bull_case", []),
            bear_case=data.get("bear_case", []),
            key_catalysts=data.get("key_catalysts", []),
            risk_level=data.get("risk_level", "medium"),
            key_risks=data.get("key_risks", []),
            valuation_notes=data.get("valuation_notes", ""),
            change_since_prior=str(data.get("change_since_prior") or ""),
            rebalancing_call=(
                dict(data["rebalancing_call"])
                if isinstance(data.get("rebalancing_call"), dict) else {}
            ),
            input_gaps=_as_str_list_local(data.get("input_gaps")),
            model_used=response.model or "thinking",
            synthesis_at=datetime.now(timezone.utc).isoformat(),
            input_tokens=response.prompt_tokens,
            output_tokens=response.completion_tokens,
            cost_usd=0.0,
        )
        logger.info(
            f"Synthesized position for {symbol}: "
            f"conviction={synthesis.conviction_score:.2f}, "
            f"recommendation={synthesis.recommendation}"
        )
        return synthesis
