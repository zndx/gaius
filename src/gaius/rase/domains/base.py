"""Domain specification and registry for RASE.

Provides the infrastructure for registering and discovering RASE domains.
Each domain (NiFi, Metabase, TUI, etc.) registers its state type, oracle,
and available constraints.

This enables:
1. Capability-based routing (which domain handles a given request)
2. Generic tooling that works across domains
3. Plugin-style extensibility for new domains
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from gaius.rase.traceability import IdScheme


@dataclass(frozen=True)
class DomainSpec:
    """Specification for a RASE domain.

    Each domain provides:
    - A state type (implementing SystemState protocol)
    - An oracle type for verification
    - Available constraint types
    - Mapping to IdScheme for traceability
    - Path to BDD features

    Attributes:
        name: Unique domain identifier
        state_type: The SystemState implementation for this domain
        oracle_type: The Oracle implementation (optional)
        constraints: Dict of constraint_name -> constraint_class
        id_scheme: IdScheme for TraceableId generation
        features_dir: Path to BDD features for this domain
        description: Human-readable description
    """

    name: str
    state_type: type
    oracle_type: type | None = None
    constraints: dict[str, type] = field(default_factory=dict)
    id_scheme: Any = None  # IdScheme - avoid import
    features_dir: str = ""
    description: str = ""

    def get_constraint(self, name: str) -> type | None:
        """Get a constraint class by name."""
        return self.constraints.get(name)

    def list_constraints(self) -> list[str]:
        """List available constraint names."""
        return list(self.constraints.keys())


class DomainRegistry:
    """Registry for RASE domains.

    Provides discovery and lookup of domain specifications.
    Domains register themselves when their module is imported.

    Usage:
        # Auto-discover all domains
        DomainRegistry.discover()

        # Get a specific domain
        nifi = DomainRegistry.get("nifi")
        if nifi:
            oracle = nifi.oracle_type()

        # List all domains
        for name in DomainRegistry.list():
            spec = DomainRegistry.get(name)
    """

    _domains: dict[str, DomainSpec] = {}

    @classmethod
    def register(cls, spec: DomainSpec) -> None:
        """Register a domain specification.

        Args:
            spec: The DomainSpec to register
        """
        cls._domains[spec.name] = spec

    @classmethod
    def get(cls, name: str) -> DomainSpec | None:
        """Get a domain specification by name.

        Args:
            name: Domain name (e.g., "nifi", "metabase")

        Returns:
            DomainSpec if found, None otherwise
        """
        return cls._domains.get(name)

    @classmethod
    def list(cls) -> list[str]:
        """List registered domain names."""
        return list(cls._domains.keys())

    @classmethod
    def all(cls) -> dict[str, DomainSpec]:
        """Get all registered domains."""
        return dict(cls._domains)

    @classmethod
    def discover(cls) -> None:
        """Auto-discover domains from gaius.rase.domains.*.

        Imports each domain module and looks for a DOMAIN_SPEC attribute.
        This enables plugin-style domain registration.
        """
        # Known domains to discover
        domain_names = ["nifi"]  # Add others as implemented

        for name in domain_names:
            try:
                mod = importlib.import_module(f"gaius.rase.domains.{name}")
                if hasattr(mod, "DOMAIN_SPEC"):
                    cls.register(mod.DOMAIN_SPEC)
            except ImportError:
                # Domain not available (missing dependencies, etc.)
                pass

    @classmethod
    def clear(cls) -> None:
        """Clear all registered domains (for testing)."""
        cls._domains.clear()


__all__ = [
    "DomainSpec",
    "DomainRegistry",
]
