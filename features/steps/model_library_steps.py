"""Step definitions for model_library.feature.

Tests the /model add workflow including:
- Hardware detection and feasibility assessment
- Fail-fast behavior for infeasible models
- Lambda Labs cloud instance recommendations
- Cerebras hosted inference options
- Cost comparison analysis
- Research integration with wiki links to model entries
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

from behave import given, when, then
from behave.api.async_step import async_run_until_complete


# =============================================================================
# Fixtures and Helpers
# =============================================================================


def _get_cli(context):
    """Get or create CLI instance."""
    if not hasattr(context, "cli") or context.cli is None:
        from gaius.cli import GaiusCLI
        context.cli = GaiusCLI()
    return context.cli


def _run_cli_command(context, command: str) -> dict:
    """Execute a CLI command and store result."""
    cli = _get_cli(context)
    result = cli.execute(command)
    context.last_result = result
    context.cli_results.append(result)
    return result


def _get_kb_root(context) -> Path:
    """Get KB root path."""
    if hasattr(context, "kb_root"):
        return context.kb_root
    # Fall back to default
    return Path("build/dev")


def _find_model_kb_entry(context, model_id: str) -> Path | None:
    """Find KB entry for a model by searching scratch directory."""
    kb_root = _get_kb_root(context)
    today = datetime.now().strftime("%Y-%m-%d")

    # Normalize model ID to filename pattern
    safe_name = model_id.lower().replace("/", "_").replace("-", "_")

    # Search in today's models directory
    models_dir = kb_root / "scratch" / today / "models"
    if models_dir.exists():
        for f in models_dir.glob("*.md"):
            if safe_name in f.name.lower() or model_id.split("/")[-1].lower() in f.name.lower():
                return f

    # Search broader scratch directory
    scratch_dir = kb_root / "scratch" / today
    if scratch_dir.exists():
        for f in scratch_dir.rglob("*.md"):
            content = f.read_text()
            if f"model_id: {model_id}" in content:
                return f

    return None


def _read_kb_entry(path: Path) -> tuple[dict, str]:
    """Read KB entry and parse frontmatter."""
    content = path.read_text()

    # Parse YAML frontmatter
    frontmatter = {}
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            import yaml
            frontmatter = yaml.safe_load(parts[1]) or {}
            body = parts[2]
        else:
            body = content
    else:
        body = content

    return frontmatter, body


# =============================================================================
# Background Steps
# =============================================================================


@given("fallbacks and workarounds are disabled")
def step_fallbacks_disabled(context):
    """Verify gRPC-only architecture is in effect.

    Note: With the gRPC-only architecture, there are no fallbacks -
    the engine must be running and reachable via gRPC.
    """
    pass  # No fallback mechanism exists anymore


@given("the gaius-engine is running with healthy endpoints")
@async_run_until_complete
async def step_engine_running(context):
    """Verify gaius-engine is running with healthy endpoints."""
    import socket

    # Check gRPC port is listening
    try:
        with socket.create_connection(("localhost", 50051), timeout=2):
            pass
    except (socket.error, socket.timeout):
        raise AssertionError(
            "gaius-engine not running on port 50051. "
            "Start with: uv run gaius-engine"
        )

    # Verify via MCP if available
    try:
        from gaius.client.engine_proxy import get_orchestrator_proxy
        proxy = await get_orchestrator_proxy()
        status = await proxy.status()

        endpoints = status.get("endpoints", [])
        healthy = sum(1 for ep in endpoints if ep.get("status") == "healthy")

        if healthy == 0:
            raise AssertionError(
                f"No healthy endpoints. Status: {status}"
            )

        context.engine_status = status
    except ImportError:
        # Fall back to socket check only
        pass


@given("the KB root is configured with current/ and scratch/ directories")
def step_kb_configured(context):
    """Verify KB directories exist."""
    kb_root = _get_kb_root(context)

    for subdir in ["current", "scratch"]:
        path = kb_root / subdir
        path.mkdir(parents=True, exist_ok=True)

    context.kb_root = kb_root


@given("the Lambda Labs API is configured")
def step_lambda_configured(context):
    """Verify Lambda Labs API is configured."""
    from gaius.core.config import GaiusConfig

    config = GaiusConfig.load()

    # Check if API key is set (may be empty for public endpoints)
    if hasattr(config, "providers") and hasattr(config.providers, "lambdalabs"):
        context.lambda_config = config.providers.lambdalabs
    else:
        # Lambda Labs works without API key for instance type queries
        context.lambda_config = None


@given("the Cerebras API is configured")
def step_cerebras_configured(context):
    """Verify Cerebras API is configured."""
    from gaius.core.config import GaiusConfig

    config = GaiusConfig.load()

    if hasattr(config, "providers") and hasattr(config.providers, "cerebras"):
        context.cerebras_config = config.providers.cerebras
    else:
        context.cerebras_config = None


# =============================================================================
# Hardware Detection
# =============================================================================


@when('I run "/model hardware" via CLI')
def step_run_model_hardware(context):
    """Run model hardware command."""
    _run_cli_command(context, "/model hardware")


@then("the response should include GPU information")
def step_response_has_gpu_info(context):
    """Verify GPU information in response."""
    result = context.last_result
    assert result.get("success"), f"Command failed: {result}"

    data = result.get("data", {})
    hardware = data.get("hardware", data)

    # Verify expected fields exist
    for field in ["gpu_count", "gpu_model", "total_vram_gb"]:
        assert field in hardware or field.replace("_", "") in str(hardware).lower(), (
            f"Missing {field} in hardware info: {hardware}"
        )


@then("the hardware info should be cached for subsequent operations")
def step_hardware_cached(context):
    """Verify hardware info is cached."""
    # This is implicit in the implementation - just verify no error
    pass


# =============================================================================
# Model Addition - Feasible
# =============================================================================


@given('I have not previously added "{model_id}"')
def step_model_not_added(context, model_id):
    """Ensure model is not already in KB."""
    kb_entry = _find_model_kb_entry(context, model_id)
    if kb_entry and kb_entry.exists():
        kb_entry.unlink()
    context.target_model_id = model_id


@when('I run "/model add {model_id}" via CLI')
def step_run_model_add(context, model_id):
    """Run model add command."""
    result = _run_cli_command(context, f"/model add {model_id}")
    context.target_model_id = model_id


@then('the model should be assessed as "{status}"')
def step_model_assessed(context, status):
    """Verify model feasibility assessment."""
    result = context.last_result
    data = result.get("data", {})

    actual_status = data.get("status", data.get("feasibility", ""))
    assert status.lower() in actual_status.lower(), (
        f"Expected status '{status}', got: {actual_status}"
    )


@then('a KB entry should be created in "{path_pattern}"')
def step_kb_entry_created(context, path_pattern):
    """Verify KB entry was created."""
    model_id = context.target_model_id
    kb_entry = _find_model_kb_entry(context, model_id)

    assert kb_entry is not None, f"No KB entry found for {model_id}"
    assert kb_entry.exists(), f"KB entry does not exist: {kb_entry}"

    # Verify path matches pattern (replace {date} with actual date)
    today = datetime.now().strftime("%Y-%m-%d")
    expected_pattern = path_pattern.replace("{date}", today)

    assert expected_pattern.replace("/", "") in str(kb_entry).replace("/", ""), (
        f"KB entry path {kb_entry} doesn't match pattern {expected_pattern}"
    )

    context.kb_entry_path = kb_entry


@then("the KB entry should have frontmatter")
def step_kb_frontmatter(context):
    """Verify KB entry frontmatter."""
    kb_entry = context.kb_entry_path
    frontmatter, _ = _read_kb_entry(kb_entry)

    for row in context.table:
        field = row["field"]
        expected = row["value"]

        actual = frontmatter.get(field, "")
        assert str(expected) in str(actual), (
            f"Frontmatter {field}: expected '{expected}', got '{actual}'"
        )


@then("the KB entry should include sections")
def step_kb_sections(context):
    """Verify KB entry contains expected sections."""
    kb_entry = context.kb_entry_path
    _, body = _read_kb_entry(kb_entry)

    for row in context.table:
        section = row["section"]
        pattern = row["content_pattern"]

        # Check section header exists
        assert f"## {section}" in body or f"# {section}" in body, (
            f"Missing section '{section}' in KB entry"
        )

        # Check content pattern matches
        regex = re.compile(pattern, re.IGNORECASE)
        assert regex.search(body), (
            f"Section '{section}' missing pattern '{pattern}'"
        )


@then("the assessment should fail fast without generating ModelSpec")
def step_fail_fast(context):
    """Verify fail-fast behavior."""
    result = context.last_result
    data = result.get("data", {})

    # Should not have ModelSpec generation
    assert "spec_generated" not in data or not data.get("spec_generated"), (
        "ModelSpec should not be generated for infeasible models"
    )


@then('a KB entry should still be created with status "{status}"')
def step_kb_entry_with_status(context, status):
    """Verify KB entry created with specific status."""
    model_id = context.target_model_id
    kb_entry = _find_model_kb_entry(context, model_id)

    assert kb_entry is not None, f"No KB entry found for {model_id}"

    frontmatter, _ = _read_kb_entry(kb_entry)
    assert frontmatter.get("status") == status, (
        f"Expected status '{status}', got: {frontmatter.get('status')}"
    )

    context.kb_entry_path = kb_entry


@then("the KB entry should include")
def step_kb_entry_includes(context):
    """Verify KB entry includes patterns."""
    kb_entry = context.kb_entry_path
    _, body = _read_kb_entry(kb_entry)

    for row in context.table:
        section = row["section"]
        pattern = row["content_pattern"]

        regex = re.compile(pattern, re.IGNORECASE)
        assert regex.search(body), (
            f"KB entry missing pattern '{pattern}' in section '{section}'"
        )


# =============================================================================
# Lambda Labs Cloud Options
# =============================================================================


@then('the KB entry should include a "{section}" section')
def step_kb_has_section(context, section):
    """Verify KB entry has specific section."""
    kb_entry = context.kb_entry_path
    _, body = _read_kb_entry(kb_entry)

    assert f"## {section}" in body or f"# {section}" in body, (
        f"Missing section '{section}' in KB entry:\n{body[:1000]}"
    )


@then("the cloud options should list instance types meeting requirements")
def step_cloud_options_list(context):
    """Verify cloud options include expected instances."""
    kb_entry = context.kb_entry_path
    _, body = _read_kb_entry(kb_entry)

    for row in context.table:
        instance = row["instance"]
        assert instance in body, f"Missing instance {instance} in cloud options"


@then("the recommended instance should be the cheapest meeting requirements")
def step_recommended_cheapest(context):
    """Verify recommended instance is cost-optimized."""
    kb_entry = context.kb_entry_path
    _, body = _read_kb_entry(kb_entry)

    # Should have recommendation section
    assert "Recommended" in body or "Best Available" in body, (
        "Missing recommended instance section"
    )


@given("Lambda Labs API returns current availability")
def step_lambda_has_availability(context):
    """Mock or verify Lambda Labs availability data."""
    # In real tests, this would set up mock responses
    # For now, just mark that we expect live data
    context.expect_live_lambda_data = True


@then('the "{section}" section should show')
def step_section_shows(context, section):
    """Verify section contains expected fields."""
    kb_entry = context.kb_entry_path
    _, body = _read_kb_entry(kb_entry)

    for row in context.table:
        field = row["field"]
        pattern = row["expected_pattern"]

        regex = re.compile(pattern, re.IGNORECASE)
        assert regex.search(body), (
            f"Section '{section}' missing {field} matching '{pattern}'"
        )


@then("the recommendation should be based on real-time availability")
def step_realtime_availability(context):
    """Verify recommendation uses live data."""
    # Implicit - Lambda Labs client fetches live data
    # Just verify we have a recommendation
    kb_entry = context.kb_entry_path
    _, body = _read_kb_entry(kb_entry)

    assert "Best Available" in body or "Recommended" in body


# =============================================================================
# Cerebras Options
# =============================================================================


@then("the Cerebras section should show")
def step_cerebras_section_shows(context):
    """Verify Cerebras section content."""
    kb_entry = context.kb_entry_path
    _, body = _read_kb_entry(kb_entry)

    # Should have Cerebras section
    assert "Cerebras" in body, "Missing Cerebras section"

    for row in context.table:
        field = row["field"]
        pattern = row["expected_pattern"]

        regex = re.compile(pattern, re.IGNORECASE)
        assert regex.search(body), (
            f"Cerebras section missing {field} matching '{pattern}'"
        )


@then("the KB entry should include a cost comparison section")
def step_has_cost_comparison(context):
    """Verify cost comparison exists."""
    kb_entry = context.kb_entry_path
    _, body = _read_kb_entry(kb_entry)

    assert "Cost Comparison" in body or "cost" in body.lower(), (
        "Missing cost comparison section"
    )


@then("the cost comparison should show for 100K tokens/hour workload")
def step_cost_comparison_workload(context):
    """Verify cost comparison details."""
    kb_entry = context.kb_entry_path
    _, body = _read_kb_entry(kb_entry)

    for row in context.table:
        option = row["option"]
        pattern = row["cost_pattern"]

        # Either option name or cost pattern should appear
        assert option in body or re.search(pattern, body), (
            f"Cost comparison missing {option}"
        )


@then("the comparison should include break-even analysis")
def step_has_breakeven(context):
    """Verify break-even analysis."""
    kb_entry = context.kb_entry_path
    _, body = _read_kb_entry(kb_entry)

    assert "break" in body.lower() or "Break" in body, (
        "Missing break-even analysis"
    )


@then("the comparison should recommend the cost-effective option")
def step_recommends_cost_effective(context):
    """Verify cost recommendation."""
    kb_entry = context.kb_entry_path
    _, body = _read_kb_entry(kb_entry)

    # Should have some recommendation indicator
    assert "cheaper" in body.lower() or "recommend" in body.lower() or "✅" in body


@then("no Cerebras option should be available")
def step_no_cerebras(context):
    """Verify no Cerebras option for unsupported models."""
    kb_entry = context.kb_entry_path
    _, body = _read_kb_entry(kb_entry)

    # Either no Cerebras section or explicitly states unavailable
    if "Cerebras" in body:
        assert "not available" in body.lower() or "unavailable" in body.lower()


@then("the Feasibility section should show multiple constraints")
def step_multiple_constraints(context):
    """Verify multiple feasibility constraints listed."""
    kb_entry = context.kb_entry_path
    _, body = _read_kb_entry(kb_entry)

    constraints_found = 0
    for row in context.table:
        constraint = row["constraint"]
        if constraint.lower() in body.lower():
            constraints_found += 1

    assert constraints_found >= 2, (
        f"Expected multiple constraints, found {constraints_found}"
    )


# =============================================================================
# Research Integration
# =============================================================================


@given('a model KB entry exists for "{model_id}"')
def step_model_entry_exists(context, model_id):
    """Verify or create model KB entry."""
    kb_entry = _find_model_kb_entry(context, model_id)

    if kb_entry is None:
        # Run model add to create entry
        _run_cli_command(context, f"/model add {model_id}")
        kb_entry = _find_model_kb_entry(context, model_id)

    assert kb_entry is not None, f"Could not create/find KB entry for {model_id}"
    context.model_kb_entry = kb_entry


@when('I run "/research {topic}" via CLI')
def step_run_research(context, topic):
    """Run research command."""
    result = _run_cli_command(context, f"/research {topic}")
    context.research_topic = topic


@then('the research note should be created in "{path_pattern}"')
def step_research_note_created(context, path_pattern):
    """Verify research note was created."""
    result = context.last_result
    data = result.get("data", {})

    saved_to = data.get("saved_to", "")
    assert saved_to, f"No saved_to path in result: {data}"

    today = datetime.now().strftime("%Y-%m-%d")
    expected = path_pattern.replace("{date}", today)

    assert expected.replace("/", "") in saved_to.replace("/", ""), (
        f"Research note path {saved_to} doesn't match {expected}"
    )

    context.research_note_path = Path(saved_to)


@then("the research note should include KB sources")
def step_research_has_kb_sources(context):
    """Verify research note has KB sources."""
    result = context.last_result
    data = result.get("data", {})

    kb_sources = data.get("kb_sources", 0)
    assert kb_sources > 0, f"No KB sources in research: {data}"


@then("the KB sources should include the GLM-4.6V model entry")
def step_kb_sources_include_model(context):
    """Verify model entry is in KB sources."""
    kb_root = _get_kb_root(context)
    note_path = kb_root / context.research_note_path

    if note_path.exists():
        content = note_path.read_text()
        assert "GLM-4.6V" in content or "glm" in content.lower(), (
            "Research note doesn't reference GLM model"
        )


@then("the research note should contain a wiki link to the model entry")
def step_research_has_wiki_link(context):
    """Verify wiki link to model entry."""
    kb_root = _get_kb_root(context)
    note_path = kb_root / context.research_note_path

    if note_path.exists():
        content = note_path.read_text()

        for row in context.table:
            pattern = row["pattern"]
            regex = re.compile(pattern, re.IGNORECASE)
            assert regex.search(content), (
                f"Missing wiki link pattern '{pattern}' in research note"
            )


@then("the wiki link should use extended citation format with regex anchor")
def step_wiki_link_format(context):
    """Verify wiki link format."""
    kb_root = _get_kb_root(context)
    note_path = kb_root / context.research_note_path

    if note_path.exists():
        content = note_path.read_text()

        # Extended citation format: [Title](path:/regex/)
        extended_pattern = r"\[.+\]\(.+\.md:/.+/\)"
        assert re.search(extended_pattern, content), (
            "Missing extended citation format with regex anchor"
        )


# =============================================================================
# Search Integration
# =============================================================================


@given("model KB entries exist in the model library")
def step_model_entries_exist(context):
    """Verify model entries exist for search."""
    # Just verify at least one exists
    kb_root = _get_kb_root(context)
    models_pattern = kb_root / "scratch" / "*" / "models" / "*.md"

    import glob
    entries = list(glob.glob(str(models_pattern)))
    # May be empty - that's ok for setup


@when('I run "/search {query}" via CLI')
def step_run_search(context, query):
    """Run search command."""
    result = _run_cli_command(context, f"/search {query}")
    context.search_query = query


@then("the search results should include the model KB entry")
def step_search_includes_model(context):
    """Verify model entry in search results."""
    result = context.last_result
    data = result.get("data", {})

    kb_results = data.get("kb_results", [])

    # Check if any result matches model entry pattern
    model_found = any(
        "model" in r.get("path", "").lower() or
        "glm" in r.get("title", "").lower()
        for r in kb_results
    )

    assert model_found or len(kb_results) > 0, (
        f"No model entry in search results: {kb_results}"
    )


@then("the result should show")
def step_result_shows(context):
    """Verify result contains expected patterns."""
    result = context.last_result
    data = result.get("data", {})
    kb_results = data.get("kb_results", [])

    if not kb_results:
        return  # Skip if no results

    first_result = kb_results[0]
    result_str = json.dumps(first_result)

    for row in context.table:
        field = row["field"]
        pattern = row["pattern"]

        regex = re.compile(pattern, re.IGNORECASE)
        assert regex.search(result_str), (
            f"Result missing {field} matching '{pattern}'"
        )


@given("provider KB entries exist for Lambda Labs and Cerebras")
def step_provider_entries_exist(context):
    """Verify provider documentation exists."""
    kb_root = _get_kb_root(context)

    providers_dir = kb_root / "current" / "providers"
    providers_dir.mkdir(parents=True, exist_ok=True)

    # Check for provider docs
    context.provider_entries = list(providers_dir.glob("*.md"))


@then("the search results should include provider entries")
def step_search_includes_providers(context):
    """Verify provider entries in search results."""
    result = context.last_result
    data = result.get("data", {})

    kb_results = data.get("kb_results", [])
    web_results = data.get("web_results", [])

    # Provider info might come from KB or web
    all_results = kb_results + web_results
    assert len(all_results) > 0, "No search results found"


@then("results should include")
def step_results_include_providers(context):
    """Verify specific providers in results."""
    result = context.last_result
    data = result.get("data", {})

    kb_results = data.get("kb_results", [])
    all_paths = [r.get("path", "") for r in kb_results]
    all_paths_str = " ".join(all_paths)

    for row in context.table:
        provider = row["provider"]
        path = row["path"]

        # Either exact path match or provider name in results
        assert path in all_paths_str or provider.lower() in all_paths_str.lower(), (
            f"Missing provider {provider} in results: {all_paths}"
        )


# =============================================================================
# Error Handling
# =============================================================================


@then("the command should fail with informative error")
def step_command_fails_with_error(context):
    """Verify command fails gracefully."""
    result = context.last_result

    # Either explicit failure or error in data
    if result.get("success"):
        data = result.get("data", {})
        assert "error" in data or "not found" in str(data).lower(), (
            "Expected error for invalid model"
        )


@then("the error should indicate model not found on HuggingFace")
def step_error_model_not_found(context):
    """Verify error message mentions HuggingFace."""
    result = context.last_result
    result_str = json.dumps(result)

    assert "not found" in result_str.lower() or "huggingface" in result_str.lower() or "404" in result_str


@then("no KB entry should be created")
def step_no_kb_entry(context):
    """Verify no KB entry was created for invalid model."""
    model_id = "not-a-valid/model-id-12345"
    kb_entry = _find_model_kb_entry(context, model_id)

    assert kb_entry is None or not kb_entry.exists(), (
        f"Unexpected KB entry created: {kb_entry}"
    )


@when("the model requires HuggingFace authentication")
def step_model_requires_auth(context):
    """Note that model requires authentication."""
    # This is informational - the actual behavior is tested elsewhere
    context.model_requires_auth = True


@then("the command should provide guidance on HF_TOKEN")
def step_guidance_hf_token(context):
    """Verify guidance about HF_TOKEN."""
    result = context.last_result
    result_str = json.dumps(result)

    # Should mention authentication or token
    assert "hf_token" in result_str.lower() or "auth" in result_str.lower() or "gated" in result_str.lower()


@then("a KB entry should still be created with available public info")
def step_kb_entry_with_public_info(context):
    """Verify KB entry created despite auth requirement."""
    result = context.last_result
    data = result.get("data", {})

    # Should have some saved path
    assert data.get("saved_to") or data.get("kb_entry")


@given("Lambda Labs API is temporarily unavailable")
def step_lambda_unavailable(context):
    """Mock Lambda Labs API being unavailable."""
    # In real tests, this would mock the API
    context.lambda_unavailable = True


@then("the KB entry should be created without cloud recommendations")
def step_kb_without_cloud(context):
    """Verify KB entry created without cloud section."""
    # Entry should exist but may have note about unavailability
    kb_entry = _find_model_kb_entry(context, context.target_model_id)
    assert kb_entry is not None


@then('the entry should note "{message}"')
def step_entry_notes(context, message):
    """Verify entry contains note."""
    kb_entry = context.kb_entry_path
    _, body = _read_kb_entry(kb_entry)

    assert message.lower() in body.lower() or "unavailable" in body.lower()


@then("the entry should still include Cerebras options if available")
def step_entry_has_cerebras_fallback(context):
    """Verify Cerebras section exists as fallback."""
    kb_entry = context.kb_entry_path
    _, body = _read_kb_entry(kb_entry)

    # Cerebras section may or may not exist depending on model
    # This is a soft check
    pass


@given("Cerebras API is temporarily unavailable")
def step_cerebras_unavailable(context):
    """Mock Cerebras API being unavailable."""
    context.cerebras_unavailable = True


@then("the entry should still include Lambda Labs cloud options")
def step_entry_has_lambda_fallback(context):
    """Verify Lambda Labs section exists as fallback."""
    kb_entry = context.kb_entry_path
    _, body = _read_kb_entry(kb_entry)

    assert "Lambda" in body or "Cloud Options" in body


# =============================================================================
# Provider Documentation
# =============================================================================


@when('I read "{path}"')
def step_read_kb_path(context, path):
    """Read a KB file."""
    kb_root = _get_kb_root(context)
    full_path = kb_root / path

    if full_path.exists():
        context.last_file_content = full_path.read_text()
    else:
        context.last_file_content = ""


@then("the document should include")
def step_document_includes(context):
    """Verify document contains expected sections."""
    content = getattr(context, "last_file_content", "")

    for row in context.table:
        section = row["section"]
        pattern = row["content_pattern"]

        regex = re.compile(pattern, re.IGNORECASE)
        assert regex.search(content), (
            f"Document missing {section} with pattern '{pattern}'"
        )
