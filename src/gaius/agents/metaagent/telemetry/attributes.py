"""Standard OTel attribute names for MetaAgent instrumentation.

These follow OTel semantic conventions where applicable, with custom
gaius.* namespace for domain-specific attributes.

Usage:
    from gaius.agents.metaagent.telemetry.attributes import MetaflowAttrs, NiFiAttrs

    span.set_attribute(MetaflowAttrs.STEP_NAME, "fetch_pdf")
    span.set_attribute(NiFiAttrs.CORRELATION_ID, correlation_id)
"""


class MetaflowAttrs:
    """Metaflow-specific OTel attributes.

    These attributes link Metaflow execution to NiFi observability.
    """

    # Flow identification
    FLOW_NAME = "metaflow.flow_name"  # e.g., "ArxivFetchFlow"
    STEP_NAME = "metaflow.step_name"  # e.g., "fetch_pdf"
    RUN_ID = "metaflow.run_id"  # e.g., "1703091234567"
    TASK_ID = "metaflow.task_id"  # e.g., "1"

    # Execution context
    NAMESPACE = "metaflow.namespace"  # e.g., "user:gaius"
    USERNAME = "metaflow.username"  # e.g., "gaius"

    # Parameters
    PARAM_PREFIX = "metaflow.param."  # e.g., metaflow.param.arxiv_id


class NiFiAttrs:
    """NiFi-specific OTel attributes.

    These attributes enable NiFi-side filtering and correlation.
    """

    # Correlation
    CORRELATION_ID = "nifi.correlation_id"  # UUID linking run to FlowFile

    # Process group context
    PROCESS_GROUP_ID = "nifi.process_group_id"
    PROCESS_GROUP_NAME = "nifi.process_group_name"

    # Processor context (for API operations)
    PROCESSOR_ID = "nifi.processor_id"
    PROCESSOR_NAME = "nifi.processor_name"
    PROCESSOR_TYPE = "nifi.processor_type"

    # Connection context
    CONNECTION_ID = "nifi.connection_id"
    CONNECTION_NAME = "nifi.connection_name"

    # Operation details
    OPERATION_TYPE = "nifi.operation_type"  # e.g., "create_processor"
    RESPONSE_TIME_MS = "nifi.response_time_ms"

    # FlowFile attributes (when receiving from NiFi)
    FLOWFILE_UUID = "nifi.flowfile.uuid"
    FLOWFILE_SIZE = "nifi.flowfile.size"


class GaiusAttrs:
    """Gaius-specific OTel attributes.

    Cross-cutting attributes for the Gaius system.
    """

    # Component identification
    COMPONENT = "gaius.component"  # e.g., "metaagent", "engine", "scheduler"

    # Domain context
    DOMAIN = "gaius.domain"  # e.g., "pension", "kudu"

    # Agent context (for swarm/evolution)
    AGENT_ID = "gaius.agent_id"
    AGENT_VERSION = "gaius.agent_version"

    # BDD/Evaluation context
    SCENARIO_ID = "gaius.scenario_id"
    SCENARIO_NAME = "gaius.scenario_name"
    EVALUATION_RUN_ID = "gaius.evaluation_run_id"


# Semantic event names for step.add_event()
class EventNames:
    """Standard event names for span events.

    Use these with span.add_event() for fine-grained observability.
    NiFi RouteOnAttribute can filter by event.name.
    """

    # Step lifecycle
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"

    # PDF processing
    PDF_EXTRACTION_STARTED = "pdf.extraction.started"
    PDF_EXTRACTION_COMPLETED = "pdf.extraction.completed"
    PDF_EXTRACTION_FAILED = "pdf.extraction.failed"

    # NiFi operations
    NIFI_FLOW_CREATED = "nifi.flow.created"
    NIFI_PROCESSOR_CREATED = "nifi.processor.created"
    NIFI_CONNECTION_CREATED = "nifi.connection.created"
    NIFI_STATE_CAPTURED = "nifi.state.captured"

    # Topic modeling
    TOPICS_EXTRACTED = "topics.extracted"

    # Relevance scoring
    SCORING_STARTED = "scoring.started"
    SCORING_COMPLETED = "scoring.completed"
    SCORING_FAILED = "scoring.failed"

    # KB/Zettelkasten
    ZETTELKASTEN_CREATED = "zettelkasten.created"

    # Evaluation
    EVALUATION_STARTED = "evaluation.started"
    EVALUATION_COMPLETED = "evaluation.completed"
