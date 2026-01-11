"""Prospects/Stewardship Flow - FMP API Integration with SEC Filing Analysis.

This module provides Metaflow flows for prospect intelligence:
- ProspectsCheckFlow: Lightweight daily check for new SEC filings
- ProspectsUpdateFlow: Full billable analysis with sync semantics

Sync Semantics (idempotent operations):
- Filing sync by accession_number (SEC's unique ID)
- Content hash verification for integrity
- Extraction phase processes only unprocessed filings
- Re-running produces no duplicates

Cost Model:
- Check: ~$0 (local LLM for decision logic)
- Update: ~$0.06/filing (Cerebras GLM 4.7) + ~$0.50/synthesis (XAI Grok)

All FMP exchanges and SEC filings are captured to Iceberg for full provenance.

Note: Flows are imported lazily to avoid circular imports with engine services.
Use direct imports: from gaius.flows.prospects.flow import ProspectsCheckFlow
"""


def __getattr__(name: str):
    """Lazy import to avoid circular dependencies with engine services."""
    if name == "ProspectsCheckFlow":
        from gaius.flows.prospects.flow import ProspectsCheckFlow
        return ProspectsCheckFlow
    elif name == "ProspectsUpdateFlow":
        from gaius.flows.prospects.update_flow import ProspectsUpdateFlow
        return ProspectsUpdateFlow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["ProspectsCheckFlow", "ProspectsUpdateFlow"]
