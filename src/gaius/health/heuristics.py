"""Heuristic loader for health checks.

Loads heuristics from KB and provides structured access to their components.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Heuristic:
    """A diagnostic heuristic with four components."""

    id: str  # Derived from file path, e.g., "engine/grpc_connection_stale"
    name: str  # H1 title from markdown
    category: str  # Directory name (engine, tui, cognition, etc.)

    symptom: str = ""
    cause: str = ""
    observation: str = ""
    solution: str = ""

    # Automation levels extracted from content
    observation_level: str = "C"  # A, B, or C
    solution_level: str = "C"

    # Code snippets for automated checks
    check_code: Optional[str] = None
    fix_code: Optional[str] = None

    # Raw markdown for display
    raw_content: str = ""


class HeuristicLoader:
    """Loads heuristics from KB directory structure."""

    def __init__(self, heuristics_root: Path):
        """Initialize loader.

        Args:
            heuristics_root: Path to heuristics directory (e.g., build/dev/current/heuristics/gaius)
        """
        self.root = Path(heuristics_root)
        self._cache: dict[str, Heuristic] = {}

    def load_all(self) -> list[Heuristic]:
        """Load all heuristics from KB.

        Returns:
            List of Heuristic objects
        """
        heuristics = []

        if not self.root.exists():
            logger.warning(f"Heuristics directory not found: {self.root}")
            return heuristics

        for md_file in self.root.rglob("*.md"):
            # Skip index files
            if md_file.name.startswith("_"):
                continue

            try:
                heuristic = self._parse_file(md_file)
                if heuristic:
                    heuristics.append(heuristic)
                    self._cache[heuristic.id] = heuristic
            except Exception as e:
                logger.warning(f"Failed to parse heuristic {md_file}: {e}")

        logger.debug(f"Loaded {len(heuristics)} heuristics from {self.root}")
        return heuristics

    def load_category(self, category: str) -> list[Heuristic]:
        """Load heuristics from a specific category.

        Args:
            category: Category name (engine, tui, cognition, etc.)

        Returns:
            List of Heuristic objects in that category
        """
        category_path = self.root / category
        if not category_path.exists():
            return []

        heuristics = []
        for md_file in category_path.glob("*.md"):
            if md_file.name.startswith("_"):
                continue

            try:
                heuristic = self._parse_file(md_file)
                if heuristic:
                    heuristics.append(heuristic)
            except Exception as e:
                logger.warning(f"Failed to parse heuristic {md_file}: {e}")

        return heuristics

    def get(self, heuristic_id: str) -> Optional[Heuristic]:
        """Get a specific heuristic by ID.

        Args:
            heuristic_id: Heuristic ID (e.g., "engine/grpc_connection_stale")

        Returns:
            Heuristic or None if not found
        """
        if heuristic_id in self._cache:
            return self._cache[heuristic_id]

        # Try to load from file
        file_path = self.root / f"{heuristic_id}.md"
        if file_path.exists():
            heuristic = self._parse_file(file_path)
            if heuristic:
                self._cache[heuristic_id] = heuristic
            return heuristic

        return None

    def _parse_file(self, file_path: Path) -> Optional[Heuristic]:
        """Parse a heuristic markdown file.

        Args:
            file_path: Path to markdown file

        Returns:
            Heuristic object or None if parsing fails
        """
        content = file_path.read_text()

        # Extract ID from path
        rel_path = file_path.relative_to(self.root)
        heuristic_id = str(rel_path.with_suffix(""))
        category = rel_path.parts[0] if len(rel_path.parts) > 1 else "uncategorized"

        # Extract title (H1)
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        name = title_match.group(1) if title_match else file_path.stem.replace("_", " ").title()

        heuristic = Heuristic(
            id=heuristic_id,
            name=name,
            category=category,
            raw_content=content,
        )

        # Extract sections
        sections = self._extract_sections(content)

        heuristic.symptom = sections.get("symptom", "")
        heuristic.cause = sections.get("cause", "")
        heuristic.observation = sections.get("observation", "")
        heuristic.solution = sections.get("solution", "")

        # Extract automation levels
        heuristic.observation_level = self._extract_automation_level(heuristic.observation)
        heuristic.solution_level = self._extract_automation_level(heuristic.solution)

        # Extract code blocks
        heuristic.check_code = self._extract_python_code(heuristic.observation)
        heuristic.fix_code = self._extract_python_code(heuristic.solution)

        return heuristic

    def _extract_sections(self, content: str) -> dict[str, str]:
        """Extract H2 sections from markdown.

        Args:
            content: Markdown content

        Returns:
            Dict mapping section name (lowercase) to content
        """
        sections = {}
        current_section = None
        current_content = []

        for line in content.split("\n"):
            if line.startswith("## "):
                # Save previous section
                if current_section:
                    sections[current_section] = "\n".join(current_content).strip()

                # Start new section
                current_section = line[3:].strip().lower()
                current_content = []
            elif current_section:
                current_content.append(line)

        # Save last section
        if current_section:
            sections[current_section] = "\n".join(current_content).strip()

        return sections

    def _extract_automation_level(self, content: str) -> str:
        """Extract automation level from section content.

        Args:
            content: Section content

        Returns:
            Automation level: "A", "B", or "C"
        """
        # Look for "Automation Level: X" pattern
        match = re.search(r"Automation Level:\s*([ABC])", content, re.IGNORECASE)
        if match:
            return match.group(1).upper()

        # Look for "(Full)" "(Partial)" patterns
        if "Full Automation" in content or "(Full)" in content:
            return "A"
        if "Partial Automation" in content or "(Partial)" in content:
            return "B"

        return "C"

    def _extract_python_code(self, content: str) -> Optional[str]:
        """Extract Python code block from content.

        Args:
            content: Section content

        Returns:
            Python code or None
        """
        # Match ```python ... ``` blocks
        match = re.search(r"```python\n(.*?)```", content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None
