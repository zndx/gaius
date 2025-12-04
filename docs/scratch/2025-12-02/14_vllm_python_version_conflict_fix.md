# vLLM Python Version Conflict Fix

**Date:** 2025-12-02
**Problem:** vLLM fails to import with `ModuleNotFoundError: No module named 'rpds.rpds'`

## Root Cause

The `devenv.nix` had `ansible` as a Nix package, which brought Python 3.13 and all its dependencies into `sys.path` BEFORE the Python 3.12 venv packages, causing import conflicts:

```
vLLM: /path/to/python3.12/site-packages/vllm/
rpds-py: /nix/store/.../python3.13-rpds-py-0.25.0/  ← Wrong version!
```

## Fix Applied

**Removed ansible from devenv.nix (line 26-27):**
```nix
packages = with pkgs; [
  # ansible  # Commented out - conflicts with Python 3.12 venv (brings Python 3.13)
            # Install via pip/uv if needed: uv pip install ansible
  cmake
  ...
];
```

## To Complete the Fix

**Exit and re-enter the devenv shell:**

```bash
# Exit current shell
exit

# Re-enter devenv
devenv shell
```

**Or restart your terminal session entirely.**

## Verify the Fix

After re-entering the shell:

```bash
# Should show NO python3.13 paths
uv run python -c "import sys; print([p for p in sys.path if 'python3.13' in p])"

# Should import successfully
uv run python -c "import vllm; print('✓ vLLM works!')"
```

## If You Need Ansible

If ansible is actually needed for this project, install it via pip in the venv:

```bash
uv pip install ansible
```

This ensures it uses the same Python version (3.12) as the rest of your dependencies.

## Testing vLLM

Once the fix is verified:

```bash
# Test the serve script
export LOCAL_MODEL="meta-llama/Meta-Llama-3-8B-Instruct"
export OPENAI_API_PORT="8080"
./serve.sh

# Or test via CLI
uv run python -m gaius.cli --cmd "/inference ensure" --format json
```

## Why This Happened

Nix packages that include Python libraries add their Python site-packages to `sys.path`. When you have a Nix package built with Python 3.13 (like `ansible`) alongside a devenv Python 3.12 environment, both versions' site-packages end up in `sys.path`, with the Nix version often taking precedence.

**The fix:** Only use Nix packages for non-Python tools (mdbook, git, jq, etc.). Install Python packages via uv/pip in the venv.

## Related Files

- `devenv.nix:26-27` - Ansible removed
- `serve.sh` - vLLM startup script
- `pyproject.toml:25` - vLLM dependency

## Status

✅ devenv.nix updated
⏳ User needs to re-enter shell to apply changes
⏳ Then verify vLLM imports correctly
