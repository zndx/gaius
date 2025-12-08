# `/model add` - AI-Powered Model Registry Extension

**Date**: 2025-12-08
**Branch**: `feature/model-add-ai`

## Summary

Implemented `/model add <model_id>` command that uses AI code generation to add new models to the Gaius registry. The feature uses a tiered model selection approach:
1. Local coding model (Qwen3-Coder on port 8082)
2. Fallback to frontier model (xAI Grok)

## Usage

```bash
# Generate ModelSpec for a HuggingFace model
/model add Qwen/Qwen3-8B

# Review the generated code, then:
/model add-confirm   # Commit to registry
/model add-cancel    # Discard

# Verify
/model info Qwen3-8B
```

## Implementation

### New Commands

| Command | Description |
|---------|-------------|
| `/model add <model_id>` | Generate ModelSpec from HuggingFace metadata |
| `/model add-confirm` | Commit pending model to registry.py |
| `/model add-cancel` | Discard pending model |

### Flow

1. **Fetch HuggingFace data**: API metadata, config.json, README.md
2. **AI code generation**: Few-shot prompt with ModelSpec example
3. **Subprocess validation**: syntax check, import test, serve_command test
4. **User review**: Show generated code and validation results
5. **Commit**: Append to registry.py, add to defaults list, create KB note

### Key Methods Added to `cli.py`

- `_cmd_model_add()` - Main entry point
- `_fetch_hf_comprehensive()` - Fetch HuggingFace data
- `_get_coding_model()` - Tiered model selection
- `_generate_modelspec()` - AI code generation via OpenAI-compatible API
- `_build_ai_prompt()` - Construct prompt with model info
- `_validate_modelspec_code()` - Subprocess validation
- `_cmd_model_add_confirm()` - Commit to registry
- `_cmd_model_add_cancel()` - Discard pending

### State Persistence

Pending model state is persisted to `{kb_root}/.pending_model_add.json` to support separate CLI invocations for add/confirm.

## Test Results

### Qwen3-8B (successful)
```json
{
  "status": "pending_review",
  "validation": {
    "syntax": true,
    "imports": true,
    "serve_cmd": true,
    "warnings": []
  }
}
```

Generated code included:
- Correct capabilities: CHAT, REASONING, CODING, FUNCTION_CALLING
- Appropriate task_scores
- `trust_remote_code=True` (correct for Qwen)
- `tensor_parallel_size=1` (correct for 8B model)

### Files Modified

- `src/gaius/cli.py` - Added ~530 lines for model add feature
- `src/gaius/models/registry.py` - QWEN3_8B model added automatically

## Validation Strategy

The validation uses subprocess isolation to safely test AI-generated code:

1. **AST parsing** - Check syntax without execution
2. **Import test** - Load ModelSpec in isolated subprocess
3. **serve_command test** - Verify vLLM command generation

This catches issues like incorrect field names (e.g., `model_name` vs `name`) before committing.

## Future Enhancements

- Deepagents sandbox for richer validation
- Evolution evaluator scoring for code quality
- Automatic vLLM config tuning based on GPU inventory
