"""Objective model for De Novo Objective Elucidation.

Objectives are first-class KB entities that describe what the system
is trying to achieve and how to verify it. They follow the Agent Skills
format with progressive disclosure.

Key concepts:
- Objectives are capabilities-in-reverse
- Gates provide verification criteria at different levels
- Frontmatter enables discovery and machine-readability
- Body provides detailed instructions (pulled on demand)

Schema follows Claude Code Skills format:
---
name: research-synthesis-verification
description: Verify synthesized KB entries ground claims in sources
domain: kb
type: rase-objective
priority: high
environment: kb-operations
allowed_tools: [Read, Grep, WebFetch]
gates:
  - name: document_parses
    level: syntactic
    constraint_type: DocumentParses
  - name: wikilinks_resolve
    level: syntactic
    constraint_type: WikilinksResolve
  - name: has_citations
    level: semantic
    constraint_type: HasCitations
    params: {min_citations: 1}
---
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from gaius.rase.traceability import IdScheme, TraceableId


class GateLevel(str, Enum):
    """Verification gate levels.

    Gates are evaluated in order of increasing cost:
    - SYNTACTIC: Cheap, fast checks (parsing, schema)
    - SEMANTIC: Medium cost (link resolution, structure)
    - EMPIRICAL: Expensive, definitive (tests, metrics, HTTP checks)
    """

    SYNTACTIC = "syntactic"
    SEMANTIC = "semantic"
    EMPIRICAL = "empirical"


class ObjectiveGate(BaseModel):
    """A verification gate for an objective.

    Gates define the success criteria for objectives. Each gate
    maps to a RASE constraint type with optional parameters.

    Attributes:
        name: Human-readable gate name
        level: Gate level (syntactic, semantic, empirical)
        constraint_type: Name of the Constraint class to use
        params: Parameters to pass to the constraint
        weight: Relative weight for graded rewards (default 1.0)
    """

    name: str
    level: GateLevel
    constraint_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    weight: float = 1.0

    model_config = {"frozen": True}

    def to_traceable_id(self, objective_id: TraceableId) -> TraceableId:
        """Generate TraceableId for this gate."""
        return TraceableId(
            scheme=IdScheme.RASE,
            path=f"{objective_id.path}/gates/{self.name}",
        )


class ObjectiveFrontmatter(BaseModel):
    """Frontmatter metadata for an objective document.

    Follows the Agent Skills format with RASE-specific extensions.

    Required fields:
        name: Unique objective identifier
        description: Human-readable description

    Optional fields:
        domain: RASE domain (kb, nifi, etc.)
        type: Objective type (rase-objective)
        priority: Execution priority (high, medium, low)
        environment: Execution environment
        allowed_tools: List of permitted tools
        gates: List of verification gates
        derived_from: List of source KB paths
        evidence_path: Where to store evidence artifacts
    """

    # Required (Agent Skills standard)
    name: str
    description: str

    # RASE extensions
    domain: str = "kb"
    type: str = "rase-objective"
    priority: str = "medium"
    environment: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    gates: list[ObjectiveGate] = Field(default_factory=list)

    # Provenance
    derived_from: list[str] = Field(default_factory=list)
    evidence_path: str = ""

    # Optional metadata
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ObjectiveFrontmatter":
        """Parse frontmatter from dict.

        Handles both flat format and nested gates format.
        """
        # Handle gates specially - they may be dicts or ObjectiveGate
        gates = []
        for gate_data in data.get("gates", []):
            if isinstance(gate_data, dict):
                # Convert level string to enum
                if "level" in gate_data and isinstance(gate_data["level"], str):
                    gate_data["level"] = GateLevel(gate_data["level"])
                gates.append(ObjectiveGate(**gate_data))
            elif isinstance(gate_data, ObjectiveGate):
                gates.append(gate_data)

        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            domain=data.get("domain", "kb"),
            type=data.get("type", "rase-objective"),
            priority=data.get("priority", "medium"),
            environment=data.get("environment", ""),
            allowed_tools=data.get("allowed_tools", data.get("allowed-tools", [])),
            gates=gates,
            derived_from=data.get("derived_from", data.get("derived-from", [])),
            evidence_path=data.get("evidence_path", data.get("evidence-path", "")),
            metadata=data.get("metadata", {}),
        )


class Objective(BaseModel):
    """A complete objective document.

    Combines frontmatter metadata with body content.
    The body is pulled on demand (progressive disclosure).

    Attributes:
        path: Relative path in KB
        frontmatter: Parsed metadata
        body: Markdown body content
        raw_content: Original full content
    """

    path: str
    frontmatter: ObjectiveFrontmatter
    body: str = ""
    raw_content: str = ""

    def to_traceable_id(self) -> TraceableId:
        """Generate TraceableId for this objective."""
        return TraceableId(
            scheme=IdScheme.RASE,
            path=f"objectives/{self.frontmatter.name}",
        )

    @property
    def name(self) -> str:
        """Objective name from frontmatter."""
        return self.frontmatter.name

    @property
    def description(self) -> str:
        """Objective description from frontmatter."""
        return self.frontmatter.description

    @property
    def gates(self) -> list[ObjectiveGate]:
        """Verification gates from frontmatter."""
        return self.frontmatter.gates

    def gates_by_level(self, level: GateLevel) -> list[ObjectiveGate]:
        """Get gates at a specific level."""
        return [g for g in self.gates if g.level == level]

    @classmethod
    def from_content(cls, path: str, content: str) -> "Objective":
        """Parse objective from markdown content.

        Args:
            path: Relative path in KB
            content: Raw markdown content with frontmatter

        Returns:
            Parsed Objective

        Raises:
            ValueError: If frontmatter is missing or invalid
        """
        from gaius.storage.filesystem import parse_frontmatter

        frontmatter_dict, body = parse_frontmatter(content)

        if not frontmatter_dict:
            raise ValueError(f"Objective at {path} missing frontmatter")

        if "name" not in frontmatter_dict:
            raise ValueError(f"Objective at {path} missing required 'name' field")

        if "description" not in frontmatter_dict:
            raise ValueError(f"Objective at {path} missing required 'description' field")

        frontmatter = ObjectiveFrontmatter.from_dict(frontmatter_dict)

        return cls(
            path=path,
            frontmatter=frontmatter,
            body=body,
            raw_content=content,
        )

    @classmethod
    def from_file(cls, path: str, kb_root: str = "build/dev") -> "Objective":
        """Load objective from KB file.

        Args:
            path: Relative path in KB (e.g., "current/objectives/rsv.md")
            kb_root: KB root directory

        Returns:
            Parsed Objective
        """
        full_path = Path(kb_root) / path
        if not full_path.suffix:
            full_path = full_path.with_suffix(".md")

        if not full_path.exists():
            raise FileNotFoundError(f"Objective not found: {full_path}")

        content = full_path.read_text()
        return cls.from_content(path, content)

    def validate_schema(self) -> list[str]:
        """Validate objective schema.

        Returns list of validation errors (empty if valid).
        """
        errors = []

        if not self.frontmatter.name:
            errors.append("Missing required field: name")

        if not self.frontmatter.description:
            errors.append("Missing required field: description")

        if not self.frontmatter.gates:
            errors.append("Objective has no gates defined")

        # Check gate constraint types exist
        from gaius.rase.domains.kb import DOMAIN_SPEC
        for gate in self.gates:
            if gate.constraint_type not in DOMAIN_SPEC.constraints:
                errors.append(
                    f"Gate '{gate.name}' references unknown constraint: {gate.constraint_type}"
                )

        return errors


__all__ = [
    "GateLevel",
    "ObjectiveGate",
    "ObjectiveFrontmatter",
    "Objective",
]
