"""NiFi TriggerMetaflow flow creation for MetaAgent.

Creates a NiFi flow that triggers Metaflow executions from within NiFi.
This enables the "dual-canvas" pattern where NiFi visualizes and triggers
Metaflow pipelines, while Metaflow sends OTel telemetry back to NiFi.

Architecture:
    NiFi Canvas                          Metaflow
    ───────────                          ────────
    ┌─────────────────┐
    │ GenerateFlowFile │   arXiv IDs
    │ (list of IDs)    │   as JSON
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │ SplitJson       │   One FlowFile
    │ ($.arxiv_ids[*])│   per arXiv ID
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐                  ┌──────────────┐
    │ExecuteStreamCmd │  ──triggers──▶   │ ArxivDocling │
    │ uv run gaius-cli│                  │ Flow         │
    └────────┬────────┘                  └──────┬───────┘
             │                                  │
             ▼                                  │ OTel
    ┌─────────────────┐                         │
    │ LogAttribute    │  ◀──telemetry──────────┘
    │ (execution log) │
    └─────────────────┘

Usage:
    from gaius.agents.metaagent.nifi import create_trigger_metaflow

    async with NiFiClient(config) as client:
        pg_id = await create_trigger_metaflow(
            client,
            parent_id=root_id,
            config=TriggerFlowConfig(
                arxiv_ids=["2312.12345", "2401.67890"],
            ),
        )
"""

import logging
from dataclasses import dataclass, field
from typing import Optional
import json

from .client import NiFiClient
from .models import Position, ProcessorConfig, PROCESSOR_TYPES

logger = logging.getLogger(__name__)


@dataclass
class TriggerFlowConfig:
    """Configuration for TriggerMetaflow flow."""

    # Process group settings
    process_group_name: str = "Metaflow-Trigger"
    position: Position = field(default_factory=lambda: Position(100, 100))

    # Initial arXiv IDs to process (can be updated later)
    arxiv_ids: list[str] = field(default_factory=list)

    # Execution settings
    scheduling_period: str = "10 min"  # How often to check for new IDs
    concurrent_tasks: int = 1  # Max parallel Metaflow executions

    # Command settings
    gaius_cli_path: str = ".devenv/state/venv/bin/python"
    cli_module: str = "-m gaius.cli"


class TriggerFlowCreationError(Exception):
    """Failed to create TriggerMetaflow flow.

    Guru Meditation: #NF.00000006.TRIGGERFLOW
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(
            f"Failed to create TriggerMetaflow flow.\n"
            f"  Reason: {reason}\n"
            f"  Guru Meditation: #NF.00000006.TRIGGERFLOW\n"
            f"  Try: /health fix nifi"
        )


async def create_trigger_metaflow(
    client: NiFiClient,
    parent_id: str,
    config: Optional[TriggerFlowConfig] = None,
) -> str:
    """Create NiFi flow for triggering Metaflow executions.

    Creates:
    1. Process group named "Metaflow-Trigger"
    2. GenerateFlowFile with arXiv IDs as JSON
    3. SplitJson to split into individual IDs
    4. EvaluateJsonPath to extract arxiv_id attribute
    5. ExecuteStreamCommand to run gaius-cli
    6. LogAttribute for execution logging

    Args:
        client: Connected NiFi client
        parent_id: Parent process group ID
        config: Flow configuration (uses defaults if not provided)

    Returns:
        ID of the created process group

    Raises:
        TriggerFlowCreationError: If creation fails
    """
    config = config or TriggerFlowConfig()

    try:
        # Create containing process group
        pg = await client.create_process_group(
            parent_id=parent_id,
            name=config.process_group_name,
            position=config.position,
            comments="Triggers Metaflow pipelines for arXiv paper processing",
        )
        pg_id = pg["id"]
        logger.info(f"Created process group: {config.process_group_name} ({pg_id})")

        # 1. GenerateFlowFile - produces JSON with arXiv IDs
        # This can be updated later or replaced with a more dynamic source
        arxiv_json = json.dumps({
            "arxiv_ids": [
                f"https://arxiv.org/abs/{aid}" for aid in config.arxiv_ids
            ] if config.arxiv_ids else [
                "https://arxiv.org/abs/2312.12345"  # Default example
            ]
        })

        generate = await client.create_processor(
            process_group_id=pg_id,
            processor_type=PROCESSOR_TYPES["generate"],
            name="ArXiv-IDs",
            position=Position(400, 50),
            config=ProcessorConfig(
                properties={
                    "Custom Text": arxiv_json,
                    "generate-ff-custom-text": arxiv_json,
                },
                scheduling_period=config.scheduling_period,
            ),
        )
        generate_id = generate["id"]
        logger.info(f"Created GenerateFlowFile: {generate_id}")

        # 2. SplitJson - split into individual arXiv IDs
        split = await client.create_processor(
            process_group_id=pg_id,
            processor_type="org.apache.nifi.processors.standard.SplitJson",
            name="Split-ArXiv-IDs",
            position=Position(400, 150),
            config=ProcessorConfig(
                properties={
                    "JsonPath Expression": "$.arxiv_ids[*]",
                },
            ),
        )
        split_id = split["id"]
        logger.info(f"Created SplitJson: {split_id}")

        # 3. EvaluateJsonPath - extract arxiv_url as FlowFile attribute
        evaluate = await client.create_processor(
            process_group_id=pg_id,
            processor_type="org.apache.nifi.processors.standard.EvaluateJsonPath",
            name="Extract-ArXiv-URL",
            position=Position(400, 250),
            config=ProcessorConfig(
                properties={
                    "Destination": "flowfile-attribute",
                    "arxiv_url": "$",  # The entire content is the URL
                },
            ),
        )
        evaluate_id = evaluate["id"]
        logger.info(f"Created EvaluateJsonPath: {evaluate_id}")

        # 4. ExecuteStreamCommand - trigger gaius-cli
        # Uses the arxiv_url attribute from the FlowFile
        execute = await client.create_processor(
            process_group_id=pg_id,
            processor_type=PROCESSOR_TYPES["execute_command"],
            name="Trigger-Metaflow",
            position=Position(400, 350),
            config=ProcessorConfig(
                properties={
                    "Command Path": config.gaius_cli_path,
                    "Command Arguments": f'{config.cli_module};--cmd;/flow run docling ${{arxiv_url}}',
                    "Argument Delimiter": ";",
                    "Ignore STDIN": "true",
                    "Output Destination Attribute": "execution_output",
                },
                scheduling_strategy="TIMER_DRIVEN",
                scheduling_period="0 sec",  # Run as fast as possible
            ),
        )
        execute_id = execute["id"]
        logger.info(f"Created ExecuteStreamCommand: {execute_id}")

        # 5. LogAttribute - log execution results
        log_success = await client.create_processor(
            process_group_id=pg_id,
            processor_type=PROCESSOR_TYPES["log"],
            name="Log-Execution",
            position=Position(400, 450),
            config=ProcessorConfig(
                properties={
                    "Log Level": "info",
                    "Log Payload": "true",
                    "Attributes to Log": "arxiv_url, execution_output",
                },
            ),
        )
        log_success_id = log_success["id"]
        logger.info(f"Created LogAttribute (success): {log_success_id}")

        # 6. LogAttribute for failures
        log_failure = await client.create_processor(
            process_group_id=pg_id,
            processor_type=PROCESSOR_TYPES["log"],
            name="Log-Failure",
            position=Position(600, 350),
            config=ProcessorConfig(
                properties={
                    "Log Level": "error",
                    "Log Payload": "true",
                },
            ),
        )
        log_failure_id = log_failure["id"]
        logger.info(f"Created LogAttribute (failure): {log_failure_id}")

        # Create connections
        # Generate -> Split
        await client.create_connection(
            process_group_id=pg_id,
            source_id=generate_id,
            dest_id=split_id,
            relationships=["success"],
            name="generate-to-split",
        )

        # Split -> Evaluate (split relationship)
        await client.create_connection(
            process_group_id=pg_id,
            source_id=split_id,
            dest_id=evaluate_id,
            relationships=["split"],
            name="split-to-evaluate",
        )

        # Evaluate -> Execute (matched)
        await client.create_connection(
            process_group_id=pg_id,
            source_id=evaluate_id,
            dest_id=execute_id,
            relationships=["matched"],
            name="evaluate-to-execute",
        )

        # Execute -> Log Success
        await client.create_connection(
            process_group_id=pg_id,
            source_id=execute_id,
            dest_id=log_success_id,
            relationships=["output stream"],
            name="execute-to-log-success",
        )

        # Execute -> Log Failure (nonzero status)
        await client.create_connection(
            process_group_id=pg_id,
            source_id=execute_id,
            dest_id=log_failure_id,
            relationships=["nonzero status"],
            name="execute-to-log-failure",
        )

        # Handle split's original relationship (auto-terminate or log)
        await client.create_connection(
            process_group_id=pg_id,
            source_id=split_id,
            dest_id=log_failure_id,
            relationships=["original", "failure"],
            name="split-failures",
        )

        # Handle evaluate's unmatched and failure
        await client.create_connection(
            process_group_id=pg_id,
            source_id=evaluate_id,
            dest_id=log_failure_id,
            relationships=["unmatched", "failure"],
            name="evaluate-failures",
        )

        logger.info(f"TriggerMetaflow flow created successfully: {pg_id}")
        return pg_id

    except Exception as e:
        raise TriggerFlowCreationError(str(e))


async def update_arxiv_ids(
    client: NiFiClient,
    process_group_id: str,
    arxiv_ids: list[str],
) -> bool:
    """Update the arXiv IDs in an existing TriggerMetaflow flow.

    Finds the GenerateFlowFile processor and updates its Custom Text property.

    Args:
        client: Connected NiFi client
        process_group_id: ID of the TriggerMetaflow process group
        arxiv_ids: New list of arXiv IDs to process

    Returns:
        True if successful
    """
    try:
        # Find the GenerateFlowFile processor
        processors = await client.list_processors(process_group_id)
        generate_processor = None

        for proc in processors:
            comp = proc.get("component", {})
            if comp.get("name") == "ArXiv-IDs":
                generate_processor = proc
                break

        if not generate_processor:
            logger.error("Could not find ArXiv-IDs processor")
            return False

        proc_id = generate_processor["id"]
        revision = generate_processor["revision"]["version"]

        # Build new JSON
        arxiv_json = json.dumps({
            "arxiv_ids": [
                f"https://arxiv.org/abs/{aid}" for aid in arxiv_ids
            ]
        })

        # Update the processor
        from .models import Revision
        await client.update_processor(
            processor_id=proc_id,
            revision=Revision(version=revision),
            updates={
                "config": {
                    "properties": {
                        "Custom Text": arxiv_json,
                        "generate-ff-custom-text": arxiv_json,
                    },
                },
            },
        )

        logger.info(f"Updated ArXiv-IDs with {len(arxiv_ids)} IDs")
        return True

    except Exception as e:
        logger.error(f"Failed to update arXiv IDs: {e}")
        return False


__all__ = [
    "create_trigger_metaflow",
    "update_arxiv_ids",
    "TriggerFlowConfig",
    "TriggerFlowCreationError",
]
