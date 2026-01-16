"""NiFi BDD step definitions.

These steps drive NiFi verification for the MetaAgent training curriculum.
They use the RASE domain for constraint verification.

Usage:
    These steps are used in NiFi curriculum feature files to define
    training scenarios for the MetaAgent.
"""

from behave import given, when, then


# --- Background steps ---


@given('a NiFi instance is running at "{url}"')
def step_nifi_running(context, url):
    """Verify NiFi is accessible at the given URL."""
    # TODO: Implement NiFi client connection
    context.nifi_url = url


@given('I have authenticated with NiFi')
def step_nifi_authenticated(context):
    """Authenticate with NiFi API."""
    # TODO: Implement authentication
    pass


@given('I am viewing the root process group')
def step_viewing_root(context):
    """Navigate to root process group."""
    context.current_group = "root"


@given('the root process group is empty')
def step_root_empty(context):
    """Ensure root process group has no processors."""
    # TODO: Clear root group or verify empty
    pass


# --- Processor creation steps ---


@when('I add a "{processor_type}" processor to the canvas')
def step_add_processor(context, processor_type):
    """Add a processor of the given type."""
    # TODO: Use NiFi client to add processor
    context.last_processor_type = processor_type


@then('the processor "{name}" should exist in the root group')
def step_processor_exists(context, name):
    """Verify processor exists."""
    # TODO: Use RASE ProcessorExists constraint
    pass


@then('the processor should be in {state} state')
def step_processor_state(context, state):
    """Verify processor run state."""
    # TODO: Use RASE constraint
    pass


# --- Configuration steps ---


@given('I have a "{processor_type}" processor named "{name}"')
def step_have_processor(context, processor_type, name):
    """Ensure a processor exists with given name and type."""
    # TODO: Create or verify processor
    pass


@when('I configure the processor with')
def step_configure_processor(context):
    """Configure processor properties from table."""
    # context.table contains the properties
    pass


@then('the processor "{name}" should have property "{prop}" = "{value}"')
def step_processor_property(context, name, prop, value):
    """Verify processor property value."""
    # TODO: Use RASE ProcessorHasProperty constraint
    pass


# --- Connection steps ---


@given('I have processors')
def step_have_processors(context):
    """Create multiple processors from table."""
    # context.table contains processor definitions
    pass


@when('I connect "{source}" to "{dest}" with relationship "{rel}"')
def step_connect_processors(context, source, dest, rel):
    """Create connection between processors."""
    # TODO: Use NiFi client to create connection
    pass


@then('a connection should exist from "{source}" to "{dest}"')
def step_connection_exists(context, source, dest):
    """Verify connection exists."""
    # TODO: Use RASE ConnectionExists constraint
    pass


# --- Start/Stop steps ---


@given('I have a running "{processor_type}" processor')
def step_have_running_processor(context, processor_type):
    """Ensure processor is running."""
    pass


@when('I stop the processor "{name}"')
def step_stop_processor(context, name):
    """Stop a processor."""
    pass


@when('I start the processor "{name}"')
def step_start_processor(context, name):
    """Start a processor."""
    pass
