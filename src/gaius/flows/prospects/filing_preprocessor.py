"""Filing preprocessor with section detection and sliding window extraction.

SEC 10-Q/10-K filings have valuable content (MD&A, Risk Factors) buried deep
in the document (~350K chars) after XBRL metadata junk (~25K chars) and
repetitive tables (~75K chars).

This module provides:
1. Section detection using regex patterns for SEC filing structure
2. Priority-weighted budget allocation (MD&A 40%, Risk Factors 25%, etc.)
3. Keyword-based salience scoring for window selection
4. Compact buffer assembly for downstream LLM analysis

The preprocessing is zero-cost (no LLM calls) and produces a high-quality
~30K char buffer from 500K+ char filings.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# SEC filing section patterns (case-insensitive)
# Format: section_name -> (regex_pattern, priority_weight)
#
# IMPORTANT: Patterns REQUIRE the ITEM prefix to avoid matching inline references
# like 'see "Risk Factors" in our Form 10-K'. Only match actual section headers.
SEC_SECTION_PATTERNS: dict[str, tuple[str, float]] = {
    "mda": (
        # ITEM 2 is MD&A in 10-Q filings
        r"ITEM\s*2\.?\s*MANAGEMENT['']?S?\s+DISCUSSION\s+AND\s+ANALYSIS",
        0.40,
    ),
    "risk_factors": (
        # ITEM 1A is Risk Factors - require ITEM prefix to avoid inline refs
        r"ITEM\s*1A\.?\s*RISK\s+FACTORS",
        0.25,
    ),
    "financial_statements": (
        # ITEM 1 is Financial Statements in 10-Q
        r"ITEM\s*1\.?\s*FINANCIAL\s+STATEMENTS",
        0.20,
    ),
    "quantitative": (
        # ITEM 3 is Quantitative and Qualitative disclosures
        r"ITEM\s*3\.?\s*QUANTITATIVE\s+AND\s+QUALITATIVE",
        0.10,
    ),
    "controls": (
        # ITEM 4 is Controls and Procedures
        r"ITEM\s*4\.?\s*CONTROLS\s+AND\s+PROCEDURES",
        0.05,
    ),
}

# Skip patterns (XBRL junk, boilerplate)
SKIP_PATTERNS: list[str] = [
    r"<xbrli?:",  # XBRL tags
    r"xmlns:",  # XML namespaces
    r"us-gaap:",  # GAAP taxonomy
    r"dei:",  # Document Entity Information
    r"srt:",  # SEC Reporting Taxonomy
    r"country:",  # Country taxonomy
]

# Financial keywords for salience scoring
# Format: keyword -> weight (higher = more relevant)
SALIENCE_KEYWORDS: dict[str, float] = {
    # Guidance and outlook (highest value)
    "guidance": 2.0,
    "outlook": 2.0,
    "forecast": 2.0,
    "expect": 1.5,
    "anticipate": 1.5,
    "project": 1.5,
    "estimate": 1.0,
    # Changes and trends (high value for detecting material changes)
    "increased": 1.5,
    "decreased": 1.5,
    "growth": 1.5,
    "decline": 1.5,
    "improvement": 1.5,
    "deterioration": 1.5,
    "year-over-year": 1.5,
    "compared to": 1.2,
    "prior year": 1.2,
    "prior period": 1.2,
    # Key metrics
    "revenue": 1.0,
    "margin": 1.0,
    "earnings": 1.0,
    "ebitda": 1.0,
    "cash flow": 1.5,
    "free cash flow": 2.0,
    "operating income": 1.0,
    "net income": 1.0,
    "gross profit": 1.0,
    # Risk indicators
    "material": 1.5,
    "significant": 1.0,
    "adverse": 1.5,
    "risk": 1.0,
    "uncertainty": 1.2,
    "impairment": 1.5,
    # Specific mentions that indicate substance
    "million": 0.5,
    "billion": 0.5,
    "percent": 0.5,
    "%": 0.3,
    # Table-specific indicators (financial tables are valuable)
    "total": 0.8,
    "balance": 0.8,
    "assets": 0.8,
    "liabilities": 0.8,
    "stockholders": 0.7,
    "consolidated": 0.7,
    "three months": 1.0,  # Quarterly comparison
    "nine months": 1.0,  # YTD comparison
    "fiscal year": 1.0,
}


@dataclass
class Section:
    """A detected section within an SEC filing."""

    name: str
    start: int
    end: int
    priority: float
    content: str = ""


@dataclass
class ScoredWindow:
    """A text window with relevance score."""

    start: int
    end: int
    text: str
    score: float
    section: str


@dataclass
class PreprocessedFiling:
    """Result of preprocessing with section analysis."""

    sections: list[Section] = field(default_factory=list)
    compact_buffer: str = ""
    original_length: int = 0
    buffer_length: int = 0
    sections_detected: list[str] = field(default_factory=list)
    skipped_chars: int = 0
    # Table statistics (valuable for financial analysis)
    table_rows_in_buffer: int = 0
    windows_selected: int = 0


def contains_xbrl_junk(text: str, threshold: float = 0.1) -> bool:
    """Check if text contains significant XBRL/XML noise.

    Args:
        text: Text to check
        threshold: Fraction of matches that indicates junk (0.0-1.0)

    Returns:
        True if the text appears to be mostly XBRL/XML metadata
    """
    if not text:
        return False
    junk_matches = sum(len(re.findall(p, text)) for p in SKIP_PATTERNS)
    return junk_matches / max(len(text), 1) > threshold


def _is_toc_reference(text: str, match_start: int, match_end: int) -> bool:
    """Check if a section match is a table-of-contents reference.

    TOC entries typically have:
    - Bracket links like [Section Name](#anchor)
    - Pipe characters from markdown tables nearby
    - Very short content before the next section
    """
    # Check chars before and after the match
    before = text[max(0, match_start - 100) : match_start]
    after = text[match_end : min(len(text), match_end + 200)]

    # TOC indicators
    toc_indicators = [
        "|" in before,  # Markdown table pipe before
        "](#" in after,  # Anchor link following the text
        "[" in text[max(0, match_start - 10) : match_start],  # Bracketed reference
    ]

    return sum(toc_indicators) >= 2


def _find_best_section_match(
    text: str, pattern: str, min_content_length: int = 1000
) -> re.Match | None:
    """Find the best match for a section header, preferring actual content over TOC.

    SEC filings often have table-of-contents entries that match our section patterns.
    This function finds the match most likely to be actual content by:
    1. Skipping matches that appear to be TOC entries
    2. Preferring matches with substantial content following them
    3. Falling back to the last match (actual content is usually later)

    Args:
        text: Full document text
        pattern: Regex pattern for section header
        min_content_length: Minimum chars of content to consider a real section

    Returns:
        Best match or None if no good match found
    """
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    if not matches:
        return None

    # If only one match, use it
    if len(matches) == 1:
        return matches[0]

    # Find best match: prefer one that's NOT in a TOC and has substantial content
    for match in matches:
        if not _is_toc_reference(text, match.start(), match.end()):
            # Check content length until next section or 50K chars
            content_preview = text[match.end() : match.end() + 50000]
            # Look for next ITEM header to estimate content length
            next_item = re.search(r"\bITEM\s*\d", content_preview, re.IGNORECASE)
            content_len = next_item.start() if next_item else len(content_preview)
            if content_len >= min_content_length:
                return match

    # Fallback: use last match (actual content is typically later in document)
    return matches[-1]


def detect_sections(text: str) -> list[Section]:
    """Detect SEC filing sections using regex patterns.

    Identifies major sections (MD&A, Risk Factors, etc.) by matching
    SEC-standard headers. Each section is assigned a priority weight
    for budget allocation.

    The detection is smart about distinguishing table-of-contents entries
    from actual section content - it prefers matches that have substantial
    content following them.

    Args:
        text: Raw extracted text from SEC filing

    Returns:
        List of sections sorted by position in document
    """
    sections: list[Section] = []
    text_len = len(text)

    for name, (pattern, priority) in SEC_SECTION_PATTERNS.items():
        match = _find_best_section_match(text, pattern)
        if match:
            start = match.start()

            # Find section end (next section header or end of document)
            search_start = start + len(match.group())
            end = text_len

            # Look for other section headers to find where this section ends
            for other_name, (other_pattern, _) in SEC_SECTION_PATTERNS.items():
                if other_name != name:
                    other_match = _find_best_section_match(
                        text[search_start:], other_pattern, min_content_length=500
                    )
                    if other_match:
                        potential_end = search_start + other_match.start()
                        if potential_end < end and potential_end > start:
                            end = potential_end

            # Only include section if it has meaningful content
            content = text[start:end]
            if len(content) >= 500:  # Skip tiny sections
                sections.append(
                    Section(
                        name=name,
                        start=start,
                        end=end,
                        priority=priority,
                        content=content,
                    )
                )

    return sorted(sections, key=lambda s: s.start)


def _count_table_rows(text: str) -> int:
    """Count markdown table rows in text.

    Tables in SEC filings (converted via docling) appear as markdown tables
    with pipe (|) delimiters. Each row has multiple pipes.

    Args:
        text: Text to analyze

    Returns:
        Estimated number of table rows (lines with 2+ pipes)
    """
    table_rows = 0
    for line in text.split("\n"):
        # Markdown table rows have at least 2 pipe characters (columns)
        if line.count("|") >= 2:
            table_rows += 1
    return table_rows


def score_window(text: str, section: str) -> float:
    """Score a text window for investment relevance.

    Uses keyword matching with weights to identify windows containing
    substantive financial content (guidance, metrics, material changes).
    Applies bonus for financial tables which contain structured data.

    Args:
        text: Window text to score
        section: Section name for context bonus

    Returns:
        Relevance score (higher = more relevant)
    """
    if not text:
        return 0.0

    score = 0.0
    text_lower = text.lower()

    # Keyword scoring
    for keyword, weight in SALIENCE_KEYWORDS.items():
        count = text_lower.count(keyword)
        score += count * weight

    # Heavy penalty for XBRL junk
    if contains_xbrl_junk(text):
        score *= 0.1

    # Bonus for tables with financial data
    # Tables are extremely valuable for financial analysis
    table_rows = _count_table_rows(text)
    if table_rows >= 3:  # At least header + separator + 1 data row
        # Scale bonus by table size: more rows = more data
        table_bonus = min(table_rows * 0.15, 3.0)  # Cap at 3x
        score *= (1.0 + table_bonus)
        logger.debug(f"Table bonus {table_bonus:.2f}x for {table_rows} rows")

    # Section-based bonus (MD&A is most valuable)
    section_bonus = {
        "mda": 1.2,
        "risk_factors": 1.1,
        "financial_statements": 1.5,  # Increased: tables are here
        "quantitative": 0.9,
        "controls": 0.8,
    }
    score *= section_bonus.get(section, 1.0)

    # Normalize by length (prefer dense content over verbose)
    words = len(text.split())
    if words > 0:
        # Sublinear normalization: sqrt prevents over-penalizing longer windows
        score = score / (words**0.5)

    return score


def extract_windows(
    section: Section,
    window_size: int = 8000,
    overlap: int = 1000,
    budget_chars: int = 12000,
) -> list[ScoredWindow]:
    """Extract and score windows from a section.

    Slides through section content, scores each window for relevance,
    and selects top-scoring windows within budget.

    Args:
        section: Section to extract from
        window_size: Size of each sliding window in chars
        overlap: Overlap between consecutive windows
        budget_chars: Maximum total chars to select

    Returns:
        Selected windows sorted by position (for coherent reading)
    """
    text = section.content
    windows: list[ScoredWindow] = []

    if not text:
        return windows

    # Slide through section
    pos = 0
    while pos < len(text):
        end = min(pos + window_size, len(text))
        window_text = text[pos:end]

        # Skip windows that are mostly XBRL/XML junk
        if not contains_xbrl_junk(window_text, threshold=0.2):
            score = score_window(window_text, section.name)
            if score > 0:  # Only keep windows with some relevance
                windows.append(
                    ScoredWindow(
                        start=section.start + pos,
                        end=section.start + end,
                        text=window_text,
                        score=score,
                        section=section.name,
                    )
                )

        pos += window_size - overlap

    # Sort by score (descending) and select within budget
    windows.sort(key=lambda w: w.score, reverse=True)

    selected: list[ScoredWindow] = []
    total_chars = 0
    for window in windows:
        if total_chars + len(window.text) <= budget_chars:
            selected.append(window)
            total_chars += len(window.text)

    # Re-sort by position for coherent output
    return sorted(selected, key=lambda w: w.start)


def preprocess_filing(
    extracted_text: str,
    target_buffer_size: int = 30000,
) -> PreprocessedFiling:
    """Preprocess SEC filing to extract salient content.

    Uses section detection and priority-based window selection to produce
    a compact, high-quality buffer for LLM analysis. The output preserves
    document structure while eliminating XBRL junk and low-value content.

    Args:
        extracted_text: Raw extracted markdown from SEC filing
        target_buffer_size: Target size for output buffer (default 30K chars)

    Returns:
        PreprocessedFiling with compact buffer and metadata
    """
    result = PreprocessedFiling(original_length=len(extracted_text))

    if not extracted_text:
        return result

    # Step 1: Detect sections
    sections = detect_sections(extracted_text)
    result.sections = sections
    result.sections_detected = [s.name for s in sections]

    if not sections:
        # Fallback: no sections detected, use heuristic middle extraction
        # Skip first 20% (usually XBRL cover page), take next target_buffer_size
        skip = int(len(extracted_text) * 0.2)
        result.compact_buffer = extracted_text[skip : skip + target_buffer_size]
        result.buffer_length = len(result.compact_buffer)
        result.skipped_chars = skip
        logger.warning(
            f"No SEC sections detected, using fallback extraction "
            f"(skip {skip:,} chars, take {result.buffer_length:,} chars)"
        )
        return result

    # Step 2: Allocate budget by priority
    buffer_parts: list[str] = []
    total_priority = sum(s.priority for s in sections)
    total_windows = 0

    for section in sections:
        # Calculate section's budget based on its priority weight
        section_budget = int(target_buffer_size * (section.priority / total_priority))

        # Extract top-scoring windows for this section
        windows = extract_windows(
            section,
            window_size=8000,
            overlap=1000,
            budget_chars=section_budget,
        )

        if windows:
            total_windows += len(windows)
            # Add section header for structure
            section_title = section.name.upper().replace("_", " ")
            buffer_parts.append(f"\n## {section_title}\n\n")
            for window in windows:
                buffer_parts.append(window.text)
                buffer_parts.append("\n\n")

    result.compact_buffer = "".join(buffer_parts)
    result.buffer_length = len(result.compact_buffer)
    result.skipped_chars = result.original_length - result.buffer_length
    result.windows_selected = total_windows
    result.table_rows_in_buffer = _count_table_rows(result.compact_buffer)

    logger.info(
        f"Preprocessed filing: {result.original_length:,} → {result.buffer_length:,} chars "
        f"({result.buffer_length / result.original_length:.1%}), "
        f"sections: {result.sections_detected}, "
        f"windows: {result.windows_selected}, table_rows: {result.table_rows_in_buffer}"
    )

    return result
