"""OpenTelemetry instrumentation for MetaAgent.

This package provides OTel tracing for the MetaAgent pipeline:
- Metaflow step tracing via TracedFlow and @traced_step
- NiFi API operation tracing via @trace_nifi_operation
- Standard attribute names for cross-component correlation

Key Concepts:
    correlation_id: Links Metaflow runs to NiFi FlowFiles
    step_name: Metaflow step for NiFi RouteOnAttribute filtering

Example:
    from gaius.agents.metaagent.telemetry import TracedFlow, traced_step

    class MyFlow(TracedFlow):
        @traced_step
        def fetch_pdf(self):
            # Span automatically created with metaflow.step_name="fetch_pdf"
            pass
"""

from .attributes import MetaflowAttrs, NiFiAttrs
from .metaflow_trace import TracedFlow, traced_step
from .nifi_trace import trace_nifi_operation

__all__ = [
    "TracedFlow",
    "traced_step",
    "trace_nifi_operation",
    "MetaflowAttrs",
    "NiFiAttrs",
]
