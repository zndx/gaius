"""Generate Obsidian .base files using orchestrator-coordinated LLM generation.

This module generates .base YAML files for prospect KB entries using the
NVIDIA ToolOrchestra pattern where a local Orchestrator-8B coordinates
calls to specialist models:

- GLM-4.7 (Cerebras): Primary generator (open weights preference)
- Grok-4.1 fast (XAI): Diagnostic specialist for validation error analysis
- Fallback template: Last resort when LLM generation fails

The orchestrator decides which tool to call based on:
- Current state (attempts, errors, diagnosis)
- User preferences (open weights preferred)
- Multi-objective optimization (cost, accuracy, latency)

This is the agentic approach: let the LLM understand the data and produce
appropriate .base structures, rather than brittle regex extraction.

References:
- https://huggingface.co/nvidia/Orchestrator-8B
- https://developer.nvidia.com/blog/train-small-orchestration-agents-to-solve-big-problems/
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from gaius.engine.backends.external import CerebrasBackend
from gaius.engine.services.prospects_analysis import FilingAnalysis, PositionSynthesis
from gaius.kb.base_validator import validate_base, ValidationResult

logger = logging.getLogger(__name__)


# Maximum retries for LLM generation with validation feedback
MAX_RETRIES = 3


# System prompt for .base generation
BASE_GENERATION_SYSTEM_PROMPT = """You are a YAML generator that produces Obsidian Bases .base files.

Obsidian Bases provide database-like views over markdown files. Output ONLY valid YAML.

.base file structure:
- name: Display name for the base
- description: Brief description
- sources: List of file/folder references
- filters: Property-based filters with operators
- formulas: Computed properties using expressions
- views: Named views with type, columns, sort

Valid operators: equals, not_equals, contains, starts_with, ends_with, before, after, greater_than, less_than, is_empty, is_not_empty
Valid view types: table, cards, gallery, list

Example:
```yaml
name: "Company Filings"
description: "SEC filing analysis views"

sources:
  - type: folder
    path: current/prospects/aapl/
    recursive: true

formulas:
  filing_age_days: 'dateDiff(now(), filing_date, "days")'
  is_recent: "filing_age_days < 90"

views:
  all_filings:
    type: table
    filter: "type == 'sec-filing'"
    columns:
      - property: "file.name"
      - property: "filing_type"
      - property: "filing_date"
    sort: [filing_date desc]

  financials:
    type: table
    filter: "filing_type contains '10-'"
    columns:
      - property: "file.name"
      - property: "revenue_yoy_change"
      - property: "gross_margin"
```

IMPORTANT: Output ONLY the YAML content. No markdown code fences, no explanations."""


# User prompt template for .base generation
BASE_GENERATION_USER_TEMPLATE = """Generate an Obsidian .base file for {symbol} ({company_name}).

Symbol directory: current/prospects/{safe_symbol}/

Filing analyses available:
{filing_summaries}

Synthesis summary:
- Recommendation: {recommendation}
- Conviction: {conviction_score:.0%}
- Risk: {risk_level}

Generate a .base file with:
1. Sources pointing to the prospect directory
2. Views for: all_filings, recent (last 90 days), financials (10-K/10-Q), catalysts
3. Formulas for: filing_age_days, is_recent, has_financials
4. Use the filing properties from frontmatter: type, filing_type, filing_date, symbol

Output ONLY valid YAML, no code fences or explanations."""


# Retry prompt when validation fails
BASE_RETRY_TEMPLATE = """The .base YAML you generated has validation errors:

{errors}

Please fix these errors and regenerate the .base YAML.
Remember:
- Valid operators: equals, not_equals, contains, before, after, greater_than, less_than, is_empty, is_not_empty
- Valid view types: table, cards, gallery, list
- formulas values must be strings (quoted expressions)

Output ONLY the corrected YAML, no code fences or explanations."""


@dataclass
class BaseGenerationResult:
    """Result of .base file generation."""

    success: bool
    content: str
    validation: ValidationResult
    attempts: int
    model_used: str = ""
    fallback_used: bool = False


def _format_filing_summaries(analyses: list[FilingAnalysis]) -> str:
    """Format filing analyses for the prompt."""
    summaries = []
    for a in analyses:
        highlights = a.key_highlights[:3] if a.key_highlights else []
        metrics_parts = []
        if a.revenue_yoy_change is not None:
            metrics_parts.append(f"revenue YoY: {a.revenue_yoy_change:.1%}")
        if a.gross_margin is not None:
            metrics_parts.append(f"margin: {a.gross_margin:.1%}")

        summary = f"- {a.filing_type} ({a.filing_date})"
        if metrics_parts:
            summary += f" | {', '.join(metrics_parts)}"
        if highlights:
            summary += f"\n  Highlights: {'; '.join(highlights[:2])}"
        summaries.append(summary)

    return "\n".join(summaries) if summaries else "No filing analyses available."


def _extract_yaml(response: str) -> str:
    """Extract YAML from LLM response, removing code fences if present."""
    content = response.strip()

    # Remove markdown code fences if present
    if content.startswith("```yaml"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]

    if content.endswith("```"):
        content = content[:-3]

    return content.strip()


def _get_fallback_template(symbol: str, safe_symbol: str) -> str:
    """Return a minimal valid .base template as fallback."""
    return f"""name: "{symbol} Prospects"
description: "Filing analysis for {symbol}"

sources:
  - type: folder
    path: current/prospects/{safe_symbol}/
    recursive: true

formulas:
  filing_age_days: 'dateDiff(now(), filing_date, "days")'
  is_recent: "filing_age_days < 90"

views:
  all_filings:
    type: table
    filter: "type == 'sec-filing'"
    columns:
      - property: "file.name"
      - property: "filing_type"
      - property: "filing_date"
    sort: [filing_date desc]

  overview:
    type: cards
    filter: "type == 'prospect-synthesis'"
    columns:
      - property: "file.name"
      - property: "conviction_score"
      - property: "recommendation"
"""


async def generate_prospect_base(
    symbol: str,
    company_name: str,
    analyses: list[FilingAnalysis],
    synthesis: PositionSynthesis | None = None,
    cerebras_backend: CerebrasBackend | None = None,
) -> BaseGenerationResult:
    """Generate .base file using orchestrator-coordinated LLM generation.

    Uses the NVIDIA ToolOrchestra pattern:
    1. Orchestrator-8B (local) decides which tool to call
    2. GLM-4.7 (Cerebras) generates YAML (open weights preferred)
    3. Grok-4.1 fast (XAI) diagnoses validation errors
    4. Fallback template as last resort

    Args:
        symbol: Stock symbol (e.g., "AAPL")
        company_name: Company name for context
        analyses: List of FilingAnalysis objects from Cerebras
        synthesis: Optional PositionSynthesis from XAI Grok
        cerebras_backend: Ignored (for backward compatibility)

    Returns:
        BaseGenerationResult with content and validation info
    """
    from .base_orchestrator import orchestrated_generate_base, OrchestratedResult

    # Delegate to orchestrated generation
    result: OrchestratedResult = await orchestrated_generate_base(
        symbol=symbol,
        company_name=company_name,
        analyses=analyses,
        synthesis=synthesis,
    )

    # Convert OrchestratedResult to BaseGenerationResult for backward compatibility
    return BaseGenerationResult(
        success=result.success,
        content=result.content,
        validation=result.validation,
        attempts=result.attempts,
        model_used=result.model_used,
        fallback_used=result.fallback_used,
    )


def generate_root_prospects_base(
    prospect_symbols: list[str],
    kb_path: str = "current/prospects/",
) -> str:
    """Generate the root prospects.base file.

    This provides portfolio-level views across all prospects.
    Since this is a structural file (not data-dependent), we generate
    it directly rather than using LLM.

    Args:
        prospect_symbols: List of symbols with prospects
        kb_path: Base KB path for prospects

    Returns:
        Valid .base YAML content
    """
    return f"""name: "Investment Prospects"
description: "Portfolio overview and prospect tracking"

sources:
  - type: folder
    path: {kb_path}
    recursive: true

formulas:
  risk_color: 'if(risk_level == "high", "#ff6b6b", if(risk_level == "medium", "#ffd93d", "#6bcb77"))'
  conviction_bar: 'repeat("█", floor(conviction_score * 10))'
  recommendation_emoji: 'if(recommendation == "buy", "🟢", if(recommendation == "sell", "🔴", if(recommendation == "hold", "🟡", "⚪")))'

views:
  portfolio:
    type: table
    filter: "type == 'prospect-synthesis'"
    columns:
      - property: "symbol"
      - property: "conviction_score"
      - property: "recommendation"
      - property: "risk_level"
    sort: [conviction_score desc]

  watchlist:
    type: table
    filter: 'type == "prospect-synthesis" and recommendation == "watch"'
    columns:
      - property: "symbol"
      - property: "file.name"

  high_conviction:
    type: cards
    filter: "type == 'prospect-synthesis' and conviction_score >= 0.7"
    columns:
      - property: "symbol"
      - property: "conviction_score"
      - property: "recommendation"

  recent_filings:
    type: table
    filter: "type == 'sec-filing'"
    columns:
      - property: "symbol"
      - property: "filing_type"
      - property: "filing_date"
    sort: [filing_date desc]
    limit: 20
"""
