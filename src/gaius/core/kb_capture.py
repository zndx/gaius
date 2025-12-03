"""KB capture utilities for serializing explain output."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re


def serialize_minigrid(data: list[list[float]], spaced: bool = True) -> str:
    """Serialize 9x9 float grid to Unicode block representation.

    Matches the widget rendering in widgets/minigrid.py.

    Args:
        data: 9x9 grid of float values [0, 1]
        spaced: Whether to add spaces between characters

    Returns:
        Multi-line string of Unicode blocks
    """
    def value_to_char(v: float) -> str:
        if v > 0.8:
            return "█"
        elif v > 0.6:
            return "▓"
        elif v > 0.4:
            return "▒"
        elif v > 0.2:
            return "░"
        elif v > 0.05:
            return "·"
        else:
            return " "

    lines = []
    separator = " " if spaced else ""
    for row in data:
        line = separator.join(value_to_char(v) for v in row)
        lines.append(line)

    return "\n".join(lines)


def get_next_sequence(scratch_dir: Path, date: str, prefix: str = "explain") -> int:
    """Get next available sequence number for today's captures.

    Args:
        scratch_dir: Root scratch directory (e.g., build/dev/scratch)
        date: ISO date string (YYYY-MM-DD)
        prefix: File prefix to search for

    Returns:
        Next sequence number (1-based)
    """
    date_dir = scratch_dir / date
    if not date_dir.exists():
        return 1

    existing = list(date_dir.glob(f"*_{prefix}_*.md"))
    if not existing:
        return 1

    sequences = []
    for f in existing:
        match = re.match(r"(\d+)_", f.name)
        if match:
            sequences.append(int(match.group(1)))

    return max(sequences) + 1 if sequences else 1


@dataclass
class ExplainCapture:
    """Complete explain capture data for KB serialization."""

    # Position
    position: str  # Go notation (e.g., "K10")
    x: int
    y: int

    # Document
    document_title: str | None
    document_path: str | None
    nearby_documents: list[str] = field(default_factory=list)

    # Geometry
    curvature: float | None = None
    gradient: tuple[float, float] | None = None
    risk_score: float | None = None

    # Topology
    h0_count: int = 0
    h1_count: int = 0
    h2_count: int = 0
    tda_entropy: float = 0.0

    # Mini-grids (9x9 float arrays)
    embed_grid: list[list[float]] | None = None
    iso_grid: list[list[float]] | None = None

    # Metadata
    grid_coverage: float = 0.0
    total_documents: int = 0
    view_mode: str = "Go"
    overlay_mode: str = "none"
    domain: str = ""
    profile: str = "default"

    # LLM output
    explanation: str = ""
    model: str = "unknown"
    elapsed_ms: int = 0

    def to_markdown(self) -> str:
        """Render complete markdown document."""
        timestamp = datetime.now().isoformat()
        title = self.document_title or "Empty"

        # Build YAML frontmatter
        frontmatter_lines = [
            "---",
            f"created: {timestamp}",
            "type: explain",
            f"position: {self.position}",
            f"coordinates: [{self.x}, {self.y}]",
        ]

        if self.document_title:
            # Escape quotes in title for YAML
            safe_title = self.document_title.replace('"', '\\"')
            frontmatter_lines.append(f'document: "{safe_title}"')

        if self.curvature is not None:
            frontmatter_lines.append(f"curvature: {self.curvature:.4f}")

        if self.gradient:
            frontmatter_lines.append(f"gradient: [{self.gradient[0]:.4f}, {self.gradient[1]:.4f}]")

        if self.risk_score is not None:
            frontmatter_lines.append(f"risk_score: {self.risk_score:.4f}")

        frontmatter_lines.extend([
            f"h0_count: {self.h0_count}",
            f"h1_count: {self.h1_count}",
            f"h2_count: {self.h2_count}",
            f"tda_entropy: {self.tda_entropy:.4f}",
            f"grid_coverage: {self.grid_coverage:.2%}",
            f"total_documents: {self.total_documents}",
            f"view_mode: {self.view_mode}",
            f"overlay_mode: {self.overlay_mode}",
            f"model: {self.model}",
            f"elapsed_ms: {self.elapsed_ms}",
            "---",
        ])

        frontmatter = "\n".join(frontmatter_lines)

        # Build body
        body_parts = [
            f"# Explain: {self.position} - {title}",
            "",
            frontmatter,
            "",
            "## Position Context",
            "",
            f"**Location:** {self.position} ({self.x}, {self.y})",
            f"**Document:** {self.document_title or 'Empty cell'}",
        ]

        if self.document_path:
            body_parts.append(f"**Path:** `{self.document_path}`")

        # Nearby documents
        if self.nearby_documents:
            body_parts.extend([
                "",
                "### Nearby Documents",
            ])
            for doc in self.nearby_documents[:8]:
                body_parts.append(f"- {doc}")

        # Mini-grid visuals
        body_parts.extend([
            "",
            "## Mini-Grid Visuals",
        ])

        if self.embed_grid:
            embed_unicode = serialize_minigrid(self.embed_grid)
            body_parts.extend([
                "",
                "### Embed View (Similarity)",
                "```",
                embed_unicode,
                "```",
                "_Cosine similarity to cursor document. Brighter = more similar._",
            ])

        if self.iso_grid:
            iso_unicode = serialize_minigrid(self.iso_grid)
            body_parts.extend([
                "",
                "### Iso View (Curvature)",
                "```",
                iso_unicode,
                "```",
                "_Ricci curvature elevation. High = boundaries, Low = interiors._",
            ])

        # Geometric features table
        body_parts.extend([
            "",
            "## Geometric Features",
            "",
            "| Metric | Value | Interpretation |",
            "|--------|-------|----------------|",
        ])

        # Curvature interpretation
        kappa_interp = "N/A"
        if self.curvature is not None:
            if self.curvature < -0.3:
                kappa_interp = "STRONG BOUNDARY"
            elif self.curvature < 0:
                kappa_interp = "boundary"
            elif self.curvature > 0.3:
                kappa_interp = "STRONG INTERIOR"
            elif self.curvature > 0:
                kappa_interp = "interior"
            else:
                kappa_interp = "flat"
            body_parts.append(f"| Curvature (κ) | {self.curvature:.4f} | {kappa_interp} |")
        else:
            body_parts.append("| Curvature (κ) | N/A | - |")

        # Gradient
        if self.gradient:
            body_parts.append(f"| Gradient | ({self.gradient[0]:.3f}, {self.gradient[1]:.3f}) | semantic flow |")
        else:
            body_parts.append("| Gradient | N/A | - |")

        # Risk score interpretation
        risk_interp = "N/A"
        if self.risk_score is not None:
            if self.risk_score > 0.7:
                risk_interp = "critical"
            elif self.risk_score > 0.4:
                risk_interp = "bridge point"
            else:
                risk_interp = "stable"
            body_parts.append(f"| Risk Score | {self.risk_score:.4f} | {risk_interp} |")
        else:
            body_parts.append("| Risk Score | N/A | - |")

        # Topological context
        body_parts.extend([
            "",
            "## Topological Context",
            "",
            "| Feature | Count | Notes |",
            "|---------|-------|-------|",
            f"| H0 (Components) | {self.h0_count} | Disconnected clusters |",
            f"| H1 (Loops) | {self.h1_count} | Knowledge cycles |",
            f"| H2 (Voids) | {self.h2_count} | Missing knowledge |",
            f"| Entropy | {self.tda_entropy:.4f} | Complexity measure |",
        ])

        # LLM explanation
        body_parts.extend([
            "",
            "## LLM Explanation",
            "",
            self.explanation,
            "",
            "---",
            "",
            f"*Generated by {self.model} in {self.elapsed_ms}ms*",
        ])

        return "\n".join(body_parts)

    def save_to_kb(self, scratch_root: Path) -> Path:
        """Save to KB and return file path.

        Args:
            scratch_root: Root scratch directory (e.g., build/dev/scratch)

        Returns:
            Path to saved file
        """
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        date_dir = scratch_root / today

        # Ensure directory exists
        date_dir.mkdir(parents=True, exist_ok=True)

        # Use HHMMSS prefix (matching thoughts format: 022406_thoughts.md)
        time_prefix = now.strftime("%H%M%S")

        # Build filename: HHMMSS_explain_K10.md
        filename = f"{time_prefix}_explain_{self.position}.md"
        filepath = date_dir / filename

        # Write content
        content = self.to_markdown()
        filepath.write_text(content, encoding="utf-8")

        return filepath
