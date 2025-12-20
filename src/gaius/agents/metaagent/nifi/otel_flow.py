"""NiFi OTel Receiving Flow creation for MetaAgent.

Creates a NiFi flow that receives OpenTelemetry data via ListenOTLP,
routes by Metaflow step name, and outputs JSON for monitoring.

Architecture:
    Metaflow Step          OTel Collector        NiFi Canvas
    ─────────────          ──────────────        ───────────

     @traced_step                                ┌─────────────┐
     def fetch_pdf()  ───▶  OTLP/gRPC  ───▶     │ ListenOTLP  │
       span attrs:          (4317)               │ (port 4319) │
       - step=fetch_pdf                          └──────┬──────┘
       - flow=ArxivFlow                                 │
       - run_id=xxx                                     ▼
                                                 ┌─────────────┐
                                                 │RouteOnAttr  │
                                                 │step=fetch_pdf
                                                 └──────┬──────┘
                                                        │
                                                        ▼
                                                 ┌─────────────┐
                                                 │ LogAttr     │◀── JSON output
                                                 └─────────────┘

Usage:
    from gaius.agents.metaagent.nifi.otel_flow import create_otel_receiving_flow

    async with NiFiClient(config) as client:
        pg_id = await create_otel_receiving_flow(
            client,
            parent_id=root_id,
            config=OTelFlowConfig(otlp_port=4319),
        )
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from .client import NiFiClient
from .models import Position, ProcessorConfig, PROCESSOR_TYPES

logger = logging.getLogger(__name__)


@dataclass
class OTelFlowConfig:
    """Configuration for OTel receiving flow."""

    # Process group settings
    process_group_name: str = "Metaflow-Telemetry"
    position: Position = field(default_factory=lambda: Position(400, 100))

    # ListenOTLP settings
    otlp_port: int = 4319  # NiFi-side OTLP receiver port

    # Step names to create dedicated routes for
    # Each gets its own LogAttribute processor
    steps_to_route: list[str] = field(
        default_factory=lambda: ["start", "end", "fetch_pdf", "extract_text"]
    )


class OTelFlowCreationError(Exception):
    """Failed to create OTel receiving flow.

    Guru Meditation: #NF.00000005.OTELFLOW
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(
            f"Failed to create OTel receiving flow.\n"
            f"  Reason: {reason}\n"
            f"  Guru Meditation: #NF.00000005.OTELFLOW\n"
            f"  Try: /health fix nifi"
        )


async def create_otel_receiving_flow(
    client: NiFiClient,
    parent_id: str,
    config: Optional[OTelFlowConfig] = None,
) -> str:
    """Create NiFi flow for receiving and routing OTel data.

    Creates:
    1. Process group named "Metaflow-Telemetry"
    2. ListenOTLP processor on specified port
    3. RouteOnAttribute to route by metaflow.step_name
    4. LogAttribute for each configured step (JSON output)
    5. LogAttribute for unmatched (catch-all)

    Args:
        client: Connected NiFi client
        parent_id: Parent process group ID
        config: Flow configuration (uses defaults if not provided)

    Returns:
        ID of the created process group

    Raises:
        OTelFlowCreationError: If creation fails
    """
    config = config or OTelFlowConfig()

    try:
        # Create containing process group
        pg = await client.create_process_group(
            parent_id=parent_id,
            name=config.process_group_name,
            position=config.position,
            comments="Receives OTel telemetry from Metaflow steps",
        )
        pg_id = pg["id"]
        logger.info(f"Created process group: {config.process_group_name} ({pg_id})")

        # Create ListenOTLP processor
        # Note: This is a placeholder since ListenOTLP may not be available
        # in all NiFi installations. Fall back to GenerateFlowFile for testing.
        listen_otlp = await _create_listen_otlp_or_placeholder(
            client, pg_id, config.otlp_port
        )
        listen_id = listen_otlp["id"]
        logger.info(f"Created ListenOTLP: {listen_id}")

        # Create RouteOnAttribute for step-based routing
        route_props = {
            # Dynamic properties for each step
            **{
                step: "${metaflow.step_name:equals('" + step + "')}"
                for step in config.steps_to_route
            }
        }
        route_config = ProcessorConfig(properties=route_props)
        route = await client.create_processor(
            process_group_id=pg_id,
            processor_type=PROCESSOR_TYPES["route"],
            name="Route-By-Step",
            position=Position(400, 200),
            config=route_config,
        )
        route_id = route["id"]
        logger.info(f"Created RouteOnAttribute: {route_id}")

        # Connect ListenOTLP to RouteOnAttribute
        await client.create_connection(
            process_group_id=pg_id,
            source_id=listen_id,
            dest_id=route_id,
            relationships=["success"],
            name="otel-to-route",
        )

        # Create LogAttribute for each step
        step_log_ids: dict[str, str] = {}
        for i, step in enumerate(config.steps_to_route):
            log = await client.create_processor(
                process_group_id=pg_id,
                processor_type=PROCESSOR_TYPES["log"],
                name=f"Log-{step}",
                position=Position(200 + i * 200, 400),
                config=ProcessorConfig(
                    properties={
                        "Log Level": "info",
                        "Log Payload": "true",
                        "Attributes to Log": "metaflow.*, nifi.*, gaius.*",
                    }
                ),
            )
            step_log_ids[step] = log["id"]
            logger.info(f"Created LogAttribute for step '{step}': {log['id']}")

            # Connect route to step logger
            await client.create_connection(
                process_group_id=pg_id,
                source_id=route_id,
                dest_id=log["id"],
                relationships=[step],
                name=f"route-to-{step}",
            )

        # Create catch-all LogAttribute for unmatched
        unmatched_log = await client.create_processor(
            process_group_id=pg_id,
            processor_type=PROCESSOR_TYPES["log"],
            name="Log-unmatched",
            position=Position(600, 400),
            config=ProcessorConfig(
                properties={
                    "Log Level": "debug",
                    "Log Payload": "true",
                }
            ),
        )
        logger.info(f"Created unmatched LogAttribute: {unmatched_log['id']}")

        # Connect route to unmatched logger
        await client.create_connection(
            process_group_id=pg_id,
            source_id=route_id,
            dest_id=unmatched_log["id"],
            relationships=["unmatched"],
            name="route-to-unmatched",
        )

        logger.info(f"OTel receiving flow created successfully: {pg_id}")
        return pg_id

    except Exception as e:
        raise OTelFlowCreationError(str(e))


async def _create_listen_otlp_or_placeholder(
    client: NiFiClient,
    pg_id: str,
    otlp_port: int,
) -> dict:
    """Create ListenOTLP processor or GenerateFlowFile placeholder.

    ListenOTLP may not be available in all NiFi installations.
    Falls back to GenerateFlowFile with simulated attributes for testing.
    """
    try:
        # Try to create actual ListenOTLP
        return await client.create_processor(
            process_group_id=pg_id,
            processor_type=PROCESSOR_TYPES["listen_otlp"],
            name="ListenOTLP",
            position=Position(400, 50),
            config=ProcessorConfig(
                properties={
                    "HTTP Port": str(otlp_port),
                }
            ),
        )
    except Exception as e:
        # Fall back to placeholder for testing
        logger.warning(
            f"ListenOTLP not available ({e}), using GenerateFlowFile placeholder"
        )
        return await client.create_processor(
            process_group_id=pg_id,
            processor_type=PROCESSOR_TYPES["generate"],
            name="OTel-Placeholder",
            position=Position(400, 50),
            config=ProcessorConfig(
                properties={
                    "Custom Text": '{"metaflow.step_name": "fetch_pdf", "metaflow.flow_name": "ArxivFlow"}',
                },
                scheduling_period="10 sec",
            ),
        )


async def get_otel_flow_status(
    client: NiFiClient,
    parent_id: str,
    flow_name: str = "Metaflow-Telemetry",
) -> Optional[dict]:
    """Get status of the OTel receiving flow if it exists.

    Returns:
        Process group status dict, or None if not found
    """
    try:
        contents = await client.get_process_group_contents(parent_id)
        flow = contents.get("processGroupFlow", {}).get("flow", {})

        for pg in flow.get("processGroups", []):
            comp = pg.get("component", {})
            if comp.get("name") == flow_name:
                return await client.get_flow_status(pg["id"])

        return None
    except Exception as e:
        logger.warning(f"Failed to get OTel flow status: {e}")
        return None


__all__ = [
    "create_otel_receiving_flow",
    "get_otel_flow_status",
    "OTelFlowConfig",
    "OTelFlowCreationError",
]
