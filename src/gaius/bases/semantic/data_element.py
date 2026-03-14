"""Data Elements for dependent field semantics.

Implements the Data Element pattern inspired by M.D. Anderson's approach
to managing complex data with dependent field semantics.

A Data Element is a named, typed field with:
- Semantic grounding (ontology IRI)
- Value domain (enumeration or validation rules)
- Dependencies (fields that modify interpretation)
- Provenance (source and transformation metadata)

Example:
    # A diagnosis code depends on the coding system
    diagnosis = DataElement(
        name="diagnosis_code",
        term_iri="BFO:quality",
        kudu_type="STRING",
        depends_on=["coding_system"],
        value_domain=ValueDomain(
            when={"coding_system": "ICD10"},
            pattern=r"^[A-Z][0-9]{2}(\\.[0-9]{1,4})?$"
        ),
    )

Usage in .base YAML:
    schema:
      - name: diagnosis_code
        type: STRING
        "@id": "obo:OGMS_0000073"  # diagnosis
        depends_on: [coding_system]
        value_domain:
          - when: {coding_system: ICD10}
            pattern: "^[A-Z][0-9]{2}(\\.[0-9]{1,4})?$"
          - when: {coding_system: SNOMED}
            pattern: "^[0-9]+$"

Guru Meditation Codes:
- #DATAELEMENT.00000001.INVALID - Invalid data element definition
- #DATAELEMENT.00000002.DEPNOTFOUND - Dependency not found
- #DATAELEMENT.00000003.VALIDATION - Value validation failed
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from gaius.bases.models.types import KuduDataType


@dataclass
class ValueConstraint:
    """A constraint on valid values for a data element.

    Supports:
    - Pattern matching (regex)
    - Enumeration (allowed values)
    - Range (min/max for numeric)
    - Custom validation function
    """

    # Conditional application
    when: dict[str, Any] | None = None  # Apply only when dependencies match

    # Constraint types (at least one should be set)
    pattern: str | None = None  # Regex pattern
    enum: list[Any] | None = None  # Allowed values
    min_value: float | int | None = None
    max_value: float | int | None = None

    # Custom validator (not serializable)
    validator: Callable[[Any], bool] | None = None

    def matches_context(self, context: dict[str, Any]) -> bool:
        """Check if this constraint applies given the context.

        Args:
            context: Current values of dependency fields

        Returns:
            True if constraint applies
        """
        if self.when is None:
            return True

        for key, expected in self.when.items():
            actual = context.get(key)
            if actual != expected:
                return False
        return True

    def validate(self, value: Any) -> tuple[bool, str | None]:
        """Validate a value against this constraint.

        Args:
            value: Value to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if value is None:
            return True, None  # Null handling is separate (nullable)

        # Pattern check
        if self.pattern is not None:
            if not isinstance(value, str):
                value = str(value)
            if not re.match(self.pattern, value):
                return False, f"Value '{value}' does not match pattern: {self.pattern}"

        # Enum check
        if self.enum is not None:
            if value not in self.enum:
                return False, f"Value '{value}' not in allowed values: {self.enum}"

        # Range check
        if self.min_value is not None:
            if value < self.min_value:
                return False, f"Value {value} below minimum {self.min_value}"
        if self.max_value is not None:
            if value > self.max_value:
                return False, f"Value {value} above maximum {self.max_value}"

        # Custom validator
        if self.validator is not None:
            if not self.validator(value):
                return False, f"Custom validation failed for value: {value}"

        return True, None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {}
        if self.when:
            result["when"] = self.when
        if self.pattern:
            result["pattern"] = self.pattern
        if self.enum:
            result["enum"] = self.enum
        if self.min_value is not None:
            result["min_value"] = self.min_value
        if self.max_value is not None:
            result["max_value"] = self.max_value
        return result

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ValueConstraint:
        """Create from dictionary."""
        return cls(
            when=d.get("when"),
            pattern=d.get("pattern"),
            enum=d.get("enum"),
            min_value=d.get("min_value"),
            max_value=d.get("max_value"),
        )


@dataclass
class DataElement:
    """A semantically-grounded data element with dependent field semantics.

    Data Elements extend simple column definitions with:
    - Ontology grounding via term_iri
    - Dependencies on other fields
    - Contextual value constraints
    - Provenance tracking
    """

    # Identity
    name: str  # Column name
    display_name: str | None = None
    description: str | None = None

    # Type
    kudu_type: str = "STRING"  # Kudu type string

    # Semantic grounding
    term_iri: str | None = None  # Ontology IRI (CURIE or full)

    # Dependencies
    depends_on: list[str] = field(default_factory=list)

    # Value constraints (may be context-dependent)
    constraints: list[ValueConstraint] = field(default_factory=list)

    # Provenance
    source: str | None = None  # Where this data comes from
    transformation: str | None = None  # How it was derived

    # Metadata
    nullable: bool = True
    deprecated: bool = False
    version: str | None = None

    def validate(
        self,
        value: Any,
        context: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None]:
        """Validate a value for this data element.

        Args:
            value: Value to validate
            context: Current values of dependency fields

        Returns:
            Tuple of (is_valid, error_message)
        """
        context = context or {}

        # Null check
        if value is None:
            if not self.nullable:
                return False, f"Field '{self.name}' is not nullable"
            return True, None

        # Find applicable constraints
        for constraint in self.constraints:
            if constraint.matches_context(context):
                valid, error = constraint.validate(value)
                if not valid:
                    return False, error

        return True, None

    def get_applicable_constraints(
        self,
        context: dict[str, Any] | None = None,
    ) -> list[ValueConstraint]:
        """Get constraints that apply in the given context.

        Args:
            context: Current values of dependency fields

        Returns:
            List of applicable constraints
        """
        context = context or {}
        return [c for c in self.constraints if c.matches_context(context)]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {
            "name": self.name,
            "type": self.kudu_type,
            "nullable": self.nullable,
        }

        if self.display_name:
            result["display_name"] = self.display_name
        if self.description:
            result["description"] = self.description
        if self.term_iri:
            result["@id"] = self.term_iri
        if self.depends_on:
            result["depends_on"] = self.depends_on
        if self.constraints:
            result["value_domain"] = [c.to_dict() for c in self.constraints]
        if self.source:
            result["source"] = self.source
        if self.transformation:
            result["transformation"] = self.transformation
        if self.deprecated:
            result["deprecated"] = True
        if self.version:
            result["version"] = self.version

        return result

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DataElement:
        """Create from dictionary (e.g., from YAML schema)."""
        # Parse constraints
        constraints: list[ValueConstraint] = []
        if "value_domain" in d:
            domain = d["value_domain"]
            if isinstance(domain, list):
                constraints = [ValueConstraint.from_dict(c) for c in domain]
            elif isinstance(domain, dict):
                constraints = [ValueConstraint.from_dict(domain)]

        return cls(
            name=d["name"],
            display_name=d.get("display_name"),
            description=d.get("description"),
            kudu_type=d.get("type", d.get("data_type", "STRING")),
            term_iri=d.get("@id"),
            depends_on=d.get("depends_on", []),
            constraints=constraints,
            source=d.get("source"),
            transformation=d.get("transformation"),
            nullable=d.get("nullable", True),
            deprecated=d.get("deprecated", False),
            version=d.get("version"),
        )


@dataclass
class DataElementSchema:
    """A collection of related data elements forming a schema.

    Provides validation and dependency resolution across elements.
    """

    elements: dict[str, DataElement] = field(default_factory=dict)
    name: str | None = None
    description: str | None = None

    def add_element(self, element: DataElement) -> None:
        """Add a data element to the schema."""
        self.elements[element.name] = element

    def get_element(self, name: str) -> DataElement | None:
        """Get a data element by name."""
        return self.elements.get(name)

    def validate_row(
        self,
        row: dict[str, Any],
    ) -> list[tuple[str, str]]:
        """Validate all values in a row.

        Args:
            row: Dictionary of column values

        Returns:
            List of (field_name, error_message) tuples for validation failures
        """
        errors: list[tuple[str, str]] = []

        for name, element in self.elements.items():
            value = row.get(name)
            valid, error = element.validate(value, context=row)
            if not valid and error:
                errors.append((name, error))

        return errors

    def get_dependency_order(self) -> list[str]:
        """Get element names in dependency order (dependencies first).

        Returns:
            List of element names in topological order

        Raises:
            ValueError: If circular dependencies detected
        """
        # Build dependency graph
        graph: dict[str, set[str]] = {}
        for name, element in self.elements.items():
            deps = set(element.depends_on) & set(self.elements.keys())
            graph[name] = deps

        # Topological sort (Kahn's algorithm)
        in_degree = {n: len(deps) for n, deps in graph.items()}
        queue = [n for n, d in in_degree.items() if d == 0]
        result: list[str] = []

        while queue:
            node = queue.pop(0)
            result.append(node)

            for other, deps in graph.items():
                if node in deps:
                    in_degree[other] -= 1
                    if in_degree[other] == 0:
                        queue.append(other)

        if len(result) != len(self.elements):
            remaining = set(self.elements.keys()) - set(result)
            raise ValueError(
                f"[#DATAELEMENT.00000002.DEPNOTFOUND] Circular dependency detected: {remaining}"
            )

        return result

    @classmethod
    def from_list(cls, schema_list: list[dict[str, Any]]) -> DataElementSchema:
        """Create from a list of column definitions.

        Args:
            schema_list: List of column dicts (as in BaseDefinition.schema)

        Returns:
            DataElementSchema with parsed elements
        """
        schema = cls()
        for item in schema_list:
            element = DataElement.from_dict(item)
            schema.add_element(element)
        return schema

    def to_list(self) -> list[dict[str, Any]]:
        """Convert to list of dictionaries for serialization."""
        return [e.to_dict() for e in self.elements.values()]
