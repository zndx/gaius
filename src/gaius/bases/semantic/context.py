"""Ontology context for semantic column resolution.

Implements JSON-LD style @context for mapping column names to ontology IRIs.
This enables BFO-grounded queries using term() in the fluent API.

Example .base YAML:
    ---
    "@context":
      "@vocab": "https://gaius.zndx.dev/ontology/"
      entity_id:
        "@id": "BFO:0000040"
        "@type": "STRING"
      site:
        "@id": "BFO:site"
      event_time:
        "@id": "BFO:temporal_region"
        "@type": "UNIXTIME_MICROS"
    ---

Usage:
    ctx = OntologyContext.from_dict(base_definition.context)
    column_name = ctx.resolve_term("BFO:site")  # Returns "site"
    iri = ctx.resolve_column("entity_id")  # Returns "BFO:0000040"

Guru Meditation Codes:
- #SEMANTIC.00000001.NOTERM - Term not found in context
- #SEMANTIC.00000002.INVALIDCTX - Invalid @context structure
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gaius.bases.semantic.prefixes import (
    DEFAULT_PREFIXES,
    BFO_ALIASES,
    expand_curie,
    compact_iri,
)


@dataclass
class TermMapping:
    """Mapping from a column name to an ontology term.

    Attributes:
        column_name: The physical column name in the table
        term_iri: The ontology IRI (may be CURIE or full IRI)
        term_type: Optional Kudu type override
        description: Optional human-readable description
    """

    column_name: str
    term_iri: str
    term_type: str | None = None
    description: str | None = None

    @property
    def expanded_iri(self) -> str:
        """Get the fully expanded IRI."""
        return expand_curie(self.term_iri)


@dataclass
class OntologyContext:
    """Context for resolving ontology terms to column names.

    Provides bidirectional mapping between:
    - Column names (physical schema)
    - Ontology terms (semantic schema)

    The @context follows JSON-LD conventions:
    - "@vocab": Default namespace for unqualified terms
    - "@id": Maps column to ontology IRI
    - "@type": Optional type annotation
    """

    vocab: str | None = None
    prefixes: dict[str, str] = field(default_factory=dict)
    term_mappings: dict[str, TermMapping] = field(default_factory=dict)
    iri_to_column: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Build reverse index after initialization."""
        # Merge with default prefixes
        merged_prefixes = {**DEFAULT_PREFIXES, **self.prefixes}
        self.prefixes = merged_prefixes

        # Build IRI -> column reverse index
        for col_name, mapping in self.term_mappings.items():
            # Index by both CURIE and expanded IRI
            self.iri_to_column[mapping.term_iri] = col_name
            expanded = expand_curie(mapping.term_iri, self.prefixes)
            self.iri_to_column[expanded] = col_name

            # Also index by local name for BFO aliases
            if ":" in mapping.term_iri:
                prefix, local = mapping.term_iri.split(":", 1)
                if prefix == "BFO":
                    self.iri_to_column[f"BFO:{local}"] = col_name

    @classmethod
    def from_dict(cls, context_dict: dict[str, Any] | None) -> OntologyContext:
        """Create OntologyContext from @context dictionary.

        Args:
            context_dict: JSON-LD style @context dictionary

        Returns:
            Parsed OntologyContext

        Raises:
            ValueError: If context structure is invalid
        """
        if not context_dict:
            return cls()

        vocab = context_dict.get("@vocab")
        prefixes: dict[str, str] = {}
        term_mappings: dict[str, TermMapping] = {}

        for key, value in context_dict.items():
            if key.startswith("@"):
                # JSON-LD keyword
                if key == "@vocab":
                    continue  # Already handled
                elif key == "@base":
                    # Could be used for relative IRI resolution
                    pass
                continue

            # Term mapping
            if isinstance(value, str):
                # Simple mapping: "column_name": "IRI"
                term_mappings[key] = TermMapping(
                    column_name=key,
                    term_iri=value,
                )
            elif isinstance(value, dict):
                # Expanded mapping with @id, @type, etc.
                term_iri = value.get("@id", key)
                term_type = value.get("@type")
                description = value.get("description") or value.get("@comment")

                # Check for prefix definitions (JSON-LD style)
                if "@id" in value and isinstance(value.get("@id"), str):
                    if value["@id"].endswith("/") or value["@id"].endswith("#"):
                        # This is a prefix definition
                        prefixes[key] = value["@id"]
                        continue

                term_mappings[key] = TermMapping(
                    column_name=key,
                    term_iri=term_iri,
                    term_type=term_type,
                    description=description,
                )
            else:
                raise ValueError(
                    f"[#SEMANTIC.00000002.INVALIDCTX] Invalid @context value for '{key}': {value}"
                )

        return cls(
            vocab=vocab,
            prefixes=prefixes,
            term_mappings=term_mappings,
        )

    def resolve_term(self, term_iri: str) -> str | None:
        """Resolve an ontology term IRI to a column name.

        Used by the compiler to translate term("BFO:site") to "site_column".

        Args:
            term_iri: Ontology IRI (CURIE or full IRI)

        Returns:
            Column name if found, None otherwise
        """
        # Direct lookup
        if term_iri in self.iri_to_column:
            return self.iri_to_column[term_iri]

        # Try expanding CURIE
        try:
            expanded = expand_curie(term_iri, self.prefixes)
            if expanded in self.iri_to_column:
                return self.iri_to_column[expanded]
        except ValueError:
            pass

        # Try BFO aliases (e.g., "BFO:site" -> BFO_ALIASES["site"])
        if ":" in term_iri:
            prefix, local = term_iri.split(":", 1)
            if prefix == "BFO" and local.lower() in BFO_ALIASES:
                aliased_iri = BFO_ALIASES[local.lower()]
                if aliased_iri in self.iri_to_column:
                    return self.iri_to_column[aliased_iri]

        # Try vocab + local name
        if self.vocab and ":" not in term_iri:
            full_iri = self.vocab + term_iri
            if full_iri in self.iri_to_column:
                return self.iri_to_column[full_iri]

        return None

    def resolve_column(self, column_name: str) -> str | None:
        """Resolve a column name to its ontology IRI.

        Used to get the semantic meaning of a column.

        Args:
            column_name: Physical column name

        Returns:
            Ontology IRI if mapped, None otherwise
        """
        mapping = self.term_mappings.get(column_name)
        if mapping:
            return mapping.term_iri
        return None

    def get_column_type(self, column_name: str) -> str | None:
        """Get the semantic type annotation for a column.

        Args:
            column_name: Physical column name

        Returns:
            Type annotation if present, None otherwise
        """
        mapping = self.term_mappings.get(column_name)
        if mapping:
            return mapping.term_type
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert back to JSON-LD style @context dictionary."""
        result: dict[str, Any] = {}

        if self.vocab:
            result["@vocab"] = self.vocab

        # Add custom prefixes (not in DEFAULT_PREFIXES)
        for prefix, iri in self.prefixes.items():
            if prefix not in DEFAULT_PREFIXES:
                result[prefix] = {"@id": iri}

        # Add term mappings
        for col_name, mapping in self.term_mappings.items():
            if mapping.term_type or mapping.description:
                entry: dict[str, Any] = {"@id": mapping.term_iri}
                if mapping.term_type:
                    entry["@type"] = mapping.term_type
                if mapping.description:
                    entry["description"] = mapping.description
                result[col_name] = entry
            else:
                result[col_name] = mapping.term_iri

        return result

    def merge(self, other: OntologyContext) -> OntologyContext:
        """Merge with another context, with other taking precedence.

        Args:
            other: Context to merge in

        Returns:
            New merged context
        """
        merged_prefixes = {**self.prefixes, **other.prefixes}
        merged_mappings = {**self.term_mappings, **other.term_mappings}

        return OntologyContext(
            vocab=other.vocab or self.vocab,
            prefixes=merged_prefixes,
            term_mappings=merged_mappings,
        )


class TermResolutionError(Exception):
    """Error resolving an ontology term.

    Guru Meditation: #SEMANTIC.00000001.NOTERM
    """

    def __init__(self, term_iri: str, message: str | None = None):
        self.term_iri = term_iri
        if message is None:
            message = f"Term not found in @context: {term_iri}"
        super().__init__(f"[#SEMANTIC.00000001.NOTERM] {message}")
