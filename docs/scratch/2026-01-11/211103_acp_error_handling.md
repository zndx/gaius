# ACP Rate Limit Error Handling - Implementation Plan

**Date**: 2026-01-11  
**Perspective**: Minimal Change / Response Parsing Approach  
**Guru Meditation**: #HF.00000004.ACPRATELIMIT

## Executive Summary

Design a minimal-change implementation for handling ACP errors (particularly rate limits) in the Gaius `/health fix` command. The approach focuses on **response parsing after the fact** rather than modifying the ACP client itself, maintaining the fail-fast principle while adding graceful error reporting.

## Problem Statement

Current behavior:
- ACP client calls `prompt()` which returns a string response
- Rate limit errors from Mistral Vibe appear as text in the response: `"Error: API error from mistral (model: mistral-vibe-cli-latest): Rate limit exceeded..."`
- No error detection - processing continues with error text treated as valid ACP output
- Multiple incidents may all fail with same error, creating duplicate GitHub comments
- No way to stop processing remaining incidents when rate limit is hit

Desired behavior:
- Detect error patterns in ACP response text
- Stop processing remaining incidents (`--stop` behavior)
- Post ONE GitHub comment per issue explaining the error
- Avoid duplicate error comments on the same issue
- Maintain fail-fast principle (no retries in ACP client)

## Architecture Constraints

1. **ACP Client is Fail-Fast**: No modifications to `GaiusACPClient` - errors are returned as response text
2. **Response Parsing Only**: Detection happens AFTER `await client.prompt()` returns
3. **Non-Agentic Comments**: Error comments are simple, template-based (not ACP investigations)
4. **Deduplication Required**: Check existing comments before posting
5. **CLI/TUI Parity**: Both code paths must handle errors identically

## Implementation Strategy

### Phase 1: Error Detection (Response Parsing)

**Location**: Create new helper function in both `cli.py` and `app.py`

```python
def _detect_acp_error(response: str) -> tuple[bool, str | None, str | None]:
    """Detect ACP errors in response text.
    
    Returns:
        (is_error, error_type, error_message)
        - is_error: True if response contains error pattern
        - error_type: "rate_limit" | "api_error" | "connection_error" | None
        - error_message: Extracted error text for logging
    """
    # Pattern 1: Rate limit errors
    rate_limit_pattern = r"Error: API error from \w+ \(model: [^)]+\): Rate limit exceeded"
    if re.search(rate_limit_pattern, response):
        return (True, "rate_limit", "Mistral Vibe rate limit exceeded")
    
    # Pattern 2: Generic API errors
    api_error_pattern = r"Error: API error from \w+"
    if re.search(api_error_pattern, response):
        match = re.search(api_error_pattern, response)
        return (True, "api_error", match.group(0) if match else "API error")
    
    # Pattern 3: Connection failures
    if "connection" in response.lower() and "error" in response.lower():
        return (True, "connection_error", "ACP connection error")
    
    return (False, None, None)
```

**Rationale**: Simple regex matching, no complex parsing. Patterns derived from observed error messages.

### Phase 2: GitHub Comment Deduplication

**Location**: Create new helper function in both `cli.py` and `app.py`

```python
def _has_error_comment(issue_number: int, repo: str, error_type: str) -> bool:
    """Check if issue already has an error comment of this type.
    
    Args:
        issue_number: GitHub issue number
        repo: Repository in "owner/name" format
        error_type: Type of error to check for
        
    Returns:
        True if comment exists, False otherwise
    """
    import subprocess
    
    try:
        # Fetch all comment bodies from the issue
        result = subprocess.run(
            ["gh", "issue", "view", str(issue_number), "--repo", repo, 
             "--json", "comments", "--jq", ".comments[] | .body"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        if result.returncode != 0:
            logger.warning(f"Could not check existing comments: {result.stderr}")
            return False  # Fail open - allow posting comment
        
        # Check if any comment contains our error marker
        marker = f"<!-- gaius-error:{error_type} -->"
        return marker in result.stdout
        
    except Exception as e:
        logger.warning(f"Failed to check existing comments: {e}")
        return False  # Fail open - allow posting comment
```

**Rationale**: Uses `gh` CLI to fetch comments, searches for HTML comment marker. Fails open (returns False) if check fails, ensuring error comments are posted even if deduplication fails.

### Phase 3: Error Comment Posting

**Location**: Create new helper function in both `cli.py` and `app.py`

```python
def _add_acp_error_comment(
    issue_number: int,
    incident: dict,
    error_type: str,
    error_message: str,
) -> dict:
    """Add non-agentic error comment to GitHub issue.
    
    Args:
        issue_number: GitHub issue number
        incident: Incident details
        error_type: Type of error detected
        error_message: Human-readable error description
        
    Returns:
        Dict with success status and any error
    """
    import subprocess
    from datetime import datetime
    
    repo = incident.get("github_repo") or os.environ.get("GAIUS_ACP_REPO", "zndx/gaius-acp")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    fingerprint = incident.get("fingerprint", "unknown")
    
    # Check for existing error comment
    if _has_error_comment(issue_number, repo, error_type):
        logger.info(f"Issue #{issue_number} already has {error_type} error comment, skipping")
        return {"success": True, "skipped": True, "reason": "duplicate"}
    
    # Build error-specific body
    if error_type == "rate_limit":
        explanation = """
The ACP service (Claude Code with Mistral Vibe) has hit its rate limit.
This is a temporary condition - processing will resume automatically
once the rate limit window resets (typically 1 minute).

**What this means**:
- This incident has NOT been investigated by ACP yet
- The incident remains active and should be monitored
- Automatic investigation will retry during the next cycle
- You can manually investigate using `/health fix` when rate limit clears
"""
    elif error_type == "api_error":
        explanation = f"""
The ACP service encountered an API error:
```
{error_message}
```

**What this means**:
- This incident has NOT been investigated by ACP yet
- The error may be transient or require ACP service restart
- Monitor ACP service health with `/health observer status`
- You can manually investigate using `/health fix` when service recovers
"""
    else:
        explanation = f"""
The ACP service encountered an error during investigation:
```
{error_message}
```

**What this means**:
- This incident has NOT been investigated by ACP yet
- Manual investigation may be required
- Check ACP service logs for details
"""
    
    body = f"""<!-- gaius-error:{error_type} -->
## [ERROR] ACP Investigation Failed - {timestamp}

**Incident**: `{fingerprint}`  
**Error Type**: `{error_type}`

{explanation}

### Next Steps
1. Monitor this issue - it will be automatically retried
2. Check ACP service health: `uv run gaius-cli --cmd "/health observer status"`
3. If urgent, manually investigate using local remediation tools

---
Generated by `/health fix` (error handler) | Guru Meditation: #HF.00000004.ACPRATELIMIT
"""
    
    try:
        result = subprocess.run(
            ["gh", "issue", "comment", str(issue_number), "--repo", repo, "--body", body],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "success": result.returncode == 0,
            "error": result.stderr if result.returncode != 0 else None,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "error": "gh CLI not found - install GitHub CLI",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }
```

**Rationale**: Template-based, non-agentic comments. HTML comment marker enables deduplication. Different explanations for different error types provide actionable guidance.

### Phase 4: CLI Integration

**Location**: `/home/rch/local/src/zndx/gaius/src/gaius/cli.py`

**Modified Method**: `async def _health_fix_all_via_acp()`

```python
async def _health_fix_all_via_acp(
    self, incidents: list[dict], dry_run: bool = False
) -> list[dict]:
    """Process ALL incidents with GitHub issues via ACP for situational awareness.
    
    ... (existing docstring) ...
    """
    from datetime import datetime
    
    results = []
    
    # Get current system state once (shared context for all incidents)
    system_state = await self._get_system_state_for_acp()
    
    # Track if we hit a blocking error (rate limit)
    encountered_blocking_error = False
    
    for incident in incidents:
        issue_number = incident.get("github_issue")
        if not issue_number:
            continue
        
        fingerprint = incident.get("fingerprint", "unknown")
        
        if dry_run:
            results.append({
                "fingerprint": fingerprint,
                "issue_number": issue_number,
                "dry_run": True,
                "would_run_acp": True,
            })
            continue
        
        # If we encountered a blocking error, skip remaining incidents
        if encountered_blocking_error:
            logger.info(f"Skipping {fingerprint} due to previous blocking error")
            results.append({
                "fingerprint": fingerprint,
                "issue_number": issue_number,
                "acp_success": False,
                "skipped": True,
                "reason": "blocked_by_previous_error",
            })
            continue
        
        # Build NOC-friendly ACP prompt
        prompt = self._build_noc_diagnosis_prompt(incident, system_state)
        
        # Run ACP session
        try:
            from .acp import GaiusACPClient, ACPConfig, ACPConnectionError
            
            config = ACPConfig(
                include_gaius_mcp=True,
                connection_timeout=120.0,
                prompt_timeout=None,  # Let Claude Code run to completion
            )
            
            async with GaiusACPClient(config) as client:
                acp_response = await client.prompt(prompt)
            
            # **NEW: Check for errors in response**
            is_error, error_type, error_message = self._detect_acp_error(acp_response)
            
            if is_error:
                logger.error(f"ACP returned error for {fingerprint}: {error_type} - {error_message}")
                
                # Add error comment to GitHub
                error_comment_result = self._add_acp_error_comment(
                    issue_number, incident, error_type, error_message
                )
                
                # Mark as blocking error if rate limit
                if error_type == "rate_limit":
                    encountered_blocking_error = True
                    logger.warning("Rate limit detected - stopping processing of remaining incidents")
                
                results.append({
                    "fingerprint": fingerprint,
                    "issue_number": issue_number,
                    "acp_success": False,
                    "error_type": error_type,
                    "error_message": error_message,
                    "error_comment": error_comment_result,
                    "blocked_remaining": error_type == "rate_limit",
                })
                continue  # Skip KB note and normal comment for this incident
            
            # **EXISTING: Normal success path continues unchanged**
            # Create KB note (best effort)
            kb_note_path = None
            try:
                kb_note_path = self._create_health_fix_note(
                    issue_number, incident, acp_response, acp_error=None
                )
            except Exception as e:
                logger.warning(f"Failed to create KB note for issue #{issue_number}: {e}")
            
            # Add NOC-friendly GitHub comment (ALWAYS - primary deliverable)
            comment_result = self._add_noc_github_comment(
                issue_number, incident, acp_response, system_state, kb_note_path
            )
            
            results.append({
                "fingerprint": fingerprint,
                "issue_number": issue_number,
                "acp_success": True,
                "kb_note": kb_note_path,
                "github_comment": comment_result,
            })
        
        except Exception as e:
            logger.error(f"ACP failed for incident {fingerprint}: {e}")
            results.append({
                "fingerprint": fingerprint,
                "issue_number": issue_number,
                "acp_success": False,
                "error": str(e),
            })
    
    return results
```

**Changes**:
1. Add `encountered_blocking_error` flag to track rate limits
2. Call `_detect_acp_error()` after receiving response
3. If error detected, call `_add_acp_error_comment()` and skip normal processing
4. If rate limit, set flag and skip remaining incidents
5. Existing success path unchanged

### Phase 5: TUI Integration

**Location**: `/home/rch/local/src/zndx/gaius/src/gaius/app.py`

**Modified Method**: `async def _fix_all_incidents_via_acp()`

```python
async def _fix_all_incidents_via_acp(
    self, client, dry_run: bool, content: "InfoPanel | None" = None
) -> list[str]:
    """Process ALL active incidents with GitHub issues via ACP.
    
    ... (existing docstring) ...
    """
    lines = ["", "## ACP-Powered Incident Remediation", ""]
    
    def update_panel():
        """Update Info Panel with current progress."""
        if content:
            content.show_file("health_fix.md", "# Health Fix\n" + "\n".join(lines))
    
    # Get all active incidents with GitHub issues
    incidents_result = await client.call(
        "HealthObserver", "incidents", {"status": "all"}, timeout=5.0
    )
    all_incidents = incidents_result.get("incidents", [])
    active_incidents = [
        i for i in all_incidents
        if i.get("status") != "resolved" and i.get("github_issue")
    ]
    
    if not active_incidents:
        lines.append("✓ No active incidents with GitHub issues")
        return lines
    
    lines.append(f"Found **{len(active_incidents)}** incident(s) with GitHub issues:")
    lines.append("")
    update_panel()
    
    if dry_run:
        for inc in active_incidents:
            fp = inc.get("fingerprint", "unknown")
            issue = inc.get("github_issue", 0)
            lines.append(f"- `{fp}` → Would investigate via ACP (Issue #{issue})")
        return lines
    
    # Get system state once for all incidents
    system_state = await self._get_tui_system_state(client)
    
    # Process each incident
    import asyncio
    from .acp import GaiusACPClient, ACPConfig
    import os
    from datetime import datetime
    from pathlib import Path
    
    config = ACPConfig(
        include_gaius_mcp=True,
        connection_timeout=120.0,
    )
    
    # **NEW: Track blocking errors**
    encountered_blocking_error = False
    
    for idx, inc in enumerate(active_incidents, 1):
        fingerprint = inc.get("fingerprint", "unknown")
        issue_number = inc.get("github_issue", 0)
        endpoint = inc.get("endpoint", "unknown")
        failure_mode = inc.get("failure_mode_id", "unknown")
        rpn_score = inc.get("rpn_score", 0)
        
        lines.append(f"### [{idx}/{len(active_incidents)}] {fingerprint}")
        lines.append(f"- Endpoint: `{endpoint}`")
        lines.append(f"- GitHub Issue: #{issue_number}")
        lines.append(f"- RPN Score: {rpn_score}")
        
        # **NEW: Skip if blocked by previous error**
        if encountered_blocking_error:
            lines.append("- ⊗ Skipped (blocked by previous rate limit error)")
            update_panel()
            continue
        
        # Check if endpoint is in preload config (obsolete detection)
        preload = system_state.get("preload_config", "").split(",")
        is_obsolete = endpoint not in preload and endpoint not in ["", "unknown"]
        
        if is_obsolete:
            lines.append(f"- **OBSOLETE**: `{endpoint}` not in preload config")
        
        lines.append("- *Connecting to ACP...*")
        update_panel()
        await asyncio.sleep(0)  # Yield to event loop for UI update
        
        # Build NOC diagnosis prompt (matches CLI)
        prompt = self._build_tui_noc_diagnosis_prompt(inc, system_state, is_obsolete)
        
        try:
            async with GaiusACPClient(config) as acp_client:
                # Update to show we're running ACP
                lines[-1] = "- *ACP session active - Claude Code investigating...*"
                update_panel()
                await asyncio.sleep(0)
                
                response = await acp_client.prompt(prompt, timeout=600.0)
                
                # **NEW: Check for errors in response**
                is_error, error_type, error_message = self._detect_acp_error(response)
                
                if is_error:
                    # Replace the progress line with error
                    lines[-1] = f"- ✗ ACP error: {error_type} - {error_message}"
                    
                    # Add error comment to GitHub
                    if issue_number:
                        error_comment_result = self._add_acp_error_comment(
                            issue_number, inc, error_type, error_message
                        )
                        if error_comment_result.get("success"):
                            if error_comment_result.get("skipped"):
                                lines.append("- ℹ Error comment already exists on issue")
                            else:
                                lines.append(f"- ✓ Error comment added to #{issue_number}")
                        else:
                            lines.append(f"- ✗ Failed to add error comment: {error_comment_result.get('error')}")
                    
                    # Mark as blocking if rate limit
                    if error_type == "rate_limit":
                        encountered_blocking_error = True
                        lines.append("- ⚠ **Rate limit - stopping remaining incidents**")
                    
                    update_panel()
                    continue  # Skip KB note and normal comment
                
                # **EXISTING: Normal success path continues unchanged**
                # Create KB note (Zettelkasten format)
                kb_root = Path(os.environ.get("GAIUS_KB_ROOT", "build/dev"))
                scratch_dir = kb_root / "scratch" / datetime.now().strftime("%Y-%m-%d")
                scratch_dir.mkdir(parents=True, exist_ok=True)
                
                timestamp = datetime.now().strftime("%H%M%S")
                safe_fp = fingerprint.replace(":", "_").replace("/", "_")
                kb_note_path = scratch_dir / f"{timestamp}_health_fix_{safe_fp}.md"
                
                kb_content = f"""# Health Fix: {fingerprint}

**Timestamp**: {datetime.now().isoformat()}
**GitHub Issue**: #{issue_number}
**RPN Score**: {rpn_score}

## System State

{self._format_system_state_for_kb(system_state)}

## ACP Response

{response}

---
🤖 Generated by Gaius TUI `/health fix`
"""
                kb_note_path.write_text(kb_content)
                
                # Replace the "ACP session active" line with KB note path
                lines[-1] = f"- KB Note: `{kb_note_path.relative_to(kb_root)}`"
                
                # Add GitHub comment (NOC-friendly format)
                if issue_number and not dry_run:
                    lines.append("- *Adding GitHub comment...*")
                    update_panel()
                    await asyncio.sleep(0)
                    
                    comment_result = self._add_tui_github_comment(
                        issue_number, inc, response, system_state,
                        str(kb_note_path.relative_to(kb_root))
                    )
                    if comment_result.get("success"):
                        lines[-1] = f"- ✓ GitHub comment added to #{issue_number}"
                    else:
                        lines[-1] = f"- ✗ GitHub comment failed: {comment_result.get('error', 'unknown')}"
                
                lines.append(f"- ✓ ACP complete ({len(response)} chars)")
        
        except Exception as e:
            # Replace the progress line with failure
            lines[-1] = f"- ✗ ACP failed: {e}"
        
        update_panel()
        lines.append("")  # Blank line between incidents
    
    return lines
```

**Changes**:
1. Add `encountered_blocking_error` flag
2. Skip incidents if blocked by rate limit
3. Call `_detect_acp_error()` after receiving response
4. If error, call `_add_acp_error_comment()` and show TUI-friendly status
5. Existing success path unchanged

## Testing Strategy

### Unit Tests
No new unit tests required - this is response parsing only.

### Integration Tests

1. **Test Error Detection**:
```bash
# Create a mock response with rate limit error
uv run python -c "
from gaius.cli import GaiusCLI
cli = GaiusCLI()
response = 'Error: API error from mistral (model: mistral-vibe-cli-latest): Rate limit exceeded for requests: 20 per 1 minute. Please try again later.'
is_error, error_type, msg = cli._detect_acp_error(response)
assert is_error == True
assert error_type == 'rate_limit'
print('✓ Error detection works')
"
```

2. **Test Comment Deduplication**:
```bash
# Requires a real GitHub issue with an error comment
# Manual verification via gh CLI
gh issue view <issue-number> --repo zndx/gaius-acp --json comments --jq '.comments[] | .body' | grep "gaius-error"
```

3. **Test Stop Behavior**:
```bash
# Run CLI with multiple incidents, simulate rate limit on first
# Verify remaining incidents show "skipped" in results
uv run gaius-cli --cmd "/health fix" --format json
```

### E2E Test

Create a test scenario:
1. Create 3 test incidents with GitHub issues
2. Simulate rate limit error on incident #1
3. Verify:
   - Error comment posted to issue #1
   - Incidents #2 and #3 skipped
   - No duplicate error comments if run twice

## Rollout Plan

### Phase 1: CLI Only (Low Risk)
1. Add helper functions to `cli.py`
2. Modify `_health_fix_all_via_acp()` in `cli.py`
3. Test with `uv run gaius-cli --cmd "/health fix"`

### Phase 2: TUI Integration (After CLI Validated)
1. Add helper functions to `app.py` (same code)
2. Modify `_fix_all_incidents_via_acp()` in `app.py`
3. Test with `uv run gaius` and `/health fix` command

### Phase 3: Documentation
1. Add to `docs/scratch/2026-01-11/211103_acp_error_handling.md`
2. Update CLAUDE.md with new error patterns
3. Add to troubleshooting guide

## Error Messages and Logging

### Guru Meditation Codes

| Code | Description |
|------|-------------|
| #HF.00000004.ACPRATELIMIT | ACP hit rate limit |
| #HF.00000005.ACPAPIERROR | ACP API error (non-rate-limit) |
| #HF.00000006.ACPCONNERROR | ACP connection error |

### Log Messages

- `ERROR: ACP returned error for {fingerprint}: {error_type} - {error_message}`
- `WARNING: Rate limit detected - stopping processing of remaining incidents`
- `INFO: Issue #{issue_number} already has {error_type} error comment, skipping`
- `INFO: Skipping {fingerprint} due to previous blocking error`

## Open Questions

1. **Should we retry on rate limit after a delay?**
   - **Decision**: No - maintain fail-fast. Let HealthObserver daemon retry on next cycle.

2. **Should we post error comments for connection errors?**
   - **Decision**: Yes - all ACP errors get error comments for visibility.

3. **What if `gh` CLI is not available?**
   - **Decision**: Error comment posting fails, but we log the error. No fallback.

4. **Should we differentiate between "soft" and "hard" errors?**
   - **Decision**: Only rate limits block remaining incidents. Other errors are per-incident.

## Success Criteria

1. Rate limit errors detected and reported via GitHub comment
2. Remaining incidents skipped when rate limit hit
3. No duplicate error comments on same issue
4. TUI shows clear status for skipped incidents
5. CLI JSON output includes error details for scripting
6. Zero changes to ACP client (fail-fast preserved)

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Regex doesn't match new error formats | Errors not detected | Use broad patterns, fail open |
| GitHub comment check fails | Duplicate comments | Fail open - allow posting |
| gh CLI not installed | No error comments | Log error, continue processing |
| Rate limit recovery takes > 1 minute | Incidents remain uninvestigated | HealthObserver retries automatically |

## File Inventory

Files to modify:
1. `/home/rch/local/src/zndx/gaius/src/gaius/cli.py` - CLI implementation
2. `/home/rch/local/src/zndx/gaius/src/gaius/app.py` - TUI implementation

New helpers added to both files:
- `_detect_acp_error(response: str) -> tuple[bool, str | None, str | None]`
- `_has_error_comment(issue_number: int, repo: str, error_type: str) -> bool`
- `_add_acp_error_comment(issue_number: int, incident: dict, error_type: str, error_message: str) -> dict`

Modified methods:
- `cli.py::GaiusCLI._health_fix_all_via_acp()` - Add error detection and stop logic
- `app.py::GaiusApp._fix_all_incidents_via_acp()` - Add error detection and stop logic

## Dependencies

- Python `re` module (already imported)
- `subprocess` module (already imported)
- `gh` CLI (already required for GitHub operations)
- No new external dependencies

