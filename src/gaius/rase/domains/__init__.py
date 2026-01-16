"""RASE Domain Registry.

Provides capability-based routing for multi-domain RASE verification.
Each domain registers its state type, oracle, and constraints.

Example:
    from gaius.rase.domains import DomainRegistry

    DomainRegistry.discover()  # Auto-discover domains
    nifi_spec = DomainRegistry.get("nifi")

    # Use domain specification
    oracle = nifi_spec.oracle_type()
    state = await oracle.get_current_state()
"""

from .base import DomainSpec, DomainRegistry

__all__ = [
    "DomainSpec",
    "DomainRegistry",
]
