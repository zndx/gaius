"""NiFi integration for MetaAgent.

Provides REST API client and flow projection for visualizing
Metaflow pipelines on the NiFi canvas.

State Management:
    NiFiStateManager provides the "oracle" for BDD-grounded evaluation,
    capturing flow state and comparing semantically (by name, not position).

OTel Integration:
    create_otel_receiving_flow creates a NiFi flow that receives OTel
    telemetry from Metaflow steps via ListenOTLP, routes by step name,
    and outputs JSON for monitoring.
"""

from .client import NiFiClient
from .models import (
    ConnectionMismatch,
    ConnectionState,
    FlowState,
    ProcessorMismatch,
    ProcessorState,
    SemanticDiff,
)
from .otel_flow import (
    create_otel_receiving_flow,
    get_otel_flow_status,
    OTelFlowConfig,
)
from .projector import MetaflowToNiFiProjector
from .state import NiFiStateManager
from .trigger_flow import (
    create_trigger_metaflow,
    update_arxiv_ids,
    TriggerFlowConfig,
)

__all__ = [
    "NiFiClient",
    "MetaflowToNiFiProjector",
    "NiFiStateManager",
    # State models
    "FlowState",
    "ProcessorState",
    "ConnectionState",
    "SemanticDiff",
    "ProcessorMismatch",
    "ConnectionMismatch",
    # OTel flow
    "create_otel_receiving_flow",
    "get_otel_flow_status",
    "OTelFlowConfig",
    # Trigger flow
    "create_trigger_metaflow",
    "update_arxiv_ids",
    "TriggerFlowConfig",
]
