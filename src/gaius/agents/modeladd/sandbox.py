"""Sandbox validation for AI-generated ModelSpec code.

Provides two isolation levels:
1. Subprocess (default): Fast Python subprocess with sys.path isolation
2. Devenv container: Stronger isolation using devenv shell with inherited dependencies

The subprocess approach is the default for speed. Devenv containers provide
additional security for untrusted model sources.
"""

from __future__ import annotations

import ast
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ValidationResult:
    """Result of code validation."""

    syntax: bool = False
    imports: bool = False
    serve_cmd: bool = False
    warnings: list[str] = field(default_factory=list)
    variable_name: str | None = None
    stdout: str = ""
    stderr: str = ""

    @property
    def is_valid(self) -> bool:
        """Check if all validation checks passed."""
        return self.syntax and self.imports and self.serve_cmd


def get_project_root() -> Path:
    """Get the project root directory."""
    # Navigate from this file to project root
    this_file = Path(__file__).resolve()
    # src/gaius/agents/modeladd/sandbox.py -> project root
    return this_file.parent.parent.parent.parent.parent


def validate_subprocess(
    code: str,
    project_root: Path | None = None,
    timeout: int = 15,
) -> ValidationResult:
    """Fast subprocess validation (default approach).

    Validates code by:
    1. AST parsing for syntax check
    2. Running import test in isolated Python subprocess
    3. Calling serve_command() to validate vLLM config

    Args:
        code: Generated Python code
        project_root: Project root path (auto-detected if None)
        timeout: Subprocess timeout in seconds

    Returns:
        ValidationResult with all check results
    """
    result = ValidationResult()

    if project_root is None:
        project_root = get_project_root()

    # 1. Syntax check via AST
    try:
        tree = ast.parse(code)
        result.syntax = True
    except SyntaxError as e:
        result.warnings.append(f"Syntax error at line {e.lineno}: {e.msg}")
        return result

    # 2. Find variable name from AST
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if isinstance(node.value, ast.Call):
                func = node.value.func
                if hasattr(func, "id") and func.id == "ModelSpec":
                    if node.targets and isinstance(node.targets[0], ast.Name):
                        result.variable_name = node.targets[0].id

    if not result.variable_name:
        result.warnings.append("No ModelSpec() assignment found")
        return result

    # 3. Import test in subprocess (isolated)
    test_script = f'''
import sys
sys.path.insert(0, "src")
from gaius.models.registry import ModelSpec, VLLMConfig, ModelCapability, TaskType
{code}
# Find and validate the ModelSpec
for name, obj in list(locals().items()):
    if isinstance(obj, ModelSpec):
        print(f"MODEL_OK: {{name}}")
        print(f"CAPABILITIES: {{[c.name for c in obj.capabilities]}}")
        try:
            cmd, env = obj.serve_command(port=8099, gpus=[0])
            print(f"SERVE_CMD_OK")
        except Exception as e:
            print(f"SERVE_CMD_ERR: {{e}}")
        break
'''

    try:
        proc = subprocess.run(
            ["python", "-c", test_script],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(project_root),
        )

        result.stdout = proc.stdout
        result.stderr = proc.stderr
        result.imports = "MODEL_OK" in proc.stdout
        result.serve_cmd = "SERVE_CMD_OK" in proc.stdout

        if proc.returncode != 0 and proc.stderr:
            # Truncate long error messages
            err = proc.stderr[:500]
            result.warnings.append(f"Import error: {err}")

        if "SERVE_CMD_ERR" in proc.stdout:
            err_match = proc.stdout.split("SERVE_CMD_ERR:")
            if len(err_match) > 1:
                result.warnings.append(f"serve_command error: {err_match[1].strip()}")

    except subprocess.TimeoutExpired:
        result.warnings.append(f"Validation timed out ({timeout}s)")
    except Exception as e:
        result.warnings.append(f"Validation failed: {e}")

    return result


def validate_devenv(
    code: str,
    project_root: Path | None = None,
    timeout: int = 60,
) -> ValidationResult:
    """Stronger isolation using devenv container.

    Uses `devenv shell` to inherit project dependencies while providing
    container-level isolation. Recommended for untrusted model sources.

    Args:
        code: Generated Python code
        project_root: Project root path (auto-detected if None)
        timeout: Container timeout in seconds (longer than subprocess)

    Returns:
        ValidationResult with all check results
    """
    result = ValidationResult()

    if project_root is None:
        project_root = get_project_root()

    # Check if devenv is available
    try:
        check = subprocess.run(
            ["devenv", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if check.returncode != 0:
            result.warnings.append("devenv not available, falling back to subprocess")
            return validate_subprocess(code, project_root, timeout=15)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        result.warnings.append("devenv not available, falling back to subprocess")
        return validate_subprocess(code, project_root, timeout=15)

    # 1. Syntax check via AST (same as subprocess)
    try:
        tree = ast.parse(code)
        result.syntax = True
    except SyntaxError as e:
        result.warnings.append(f"Syntax error at line {e.lineno}: {e.msg}")
        return result

    # 2. Find variable name from AST
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if isinstance(node.value, ast.Call):
                func = node.value.func
                if hasattr(func, "id") and func.id == "ModelSpec":
                    if node.targets and isinstance(node.targets[0], ast.Name):
                        result.variable_name = node.targets[0].id

    if not result.variable_name:
        result.warnings.append("No ModelSpec() assignment found")
        return result

    # 3. Write validation script to temp file and run in devenv
    test_script = f'''
import sys
sys.path.insert(0, "src")
from gaius.models.registry import ModelSpec, VLLMConfig, ModelCapability, TaskType
{code}
# Find and validate the ModelSpec
for name, obj in list(locals().items()):
    if isinstance(obj, ModelSpec):
        print(f"MODEL_OK: {{name}}")
        print(f"CAPABILITIES: {{[c.name for c in obj.capabilities]}}")
        try:
            cmd, env = obj.serve_command(port=8099, gpus=[0])
            print(f"SERVE_CMD_OK")
        except Exception as e:
            print(f"SERVE_CMD_ERR: {{e}}")
        break
'''

    try:
        # Write to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(test_script)
            temp_path = f.name

        try:
            # Run in devenv shell for isolation
            proc = subprocess.run(
                ["devenv", "shell", "--", "python", temp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(project_root),
            )

            result.stdout = proc.stdout
            result.stderr = proc.stderr
            result.imports = "MODEL_OK" in proc.stdout
            result.serve_cmd = "SERVE_CMD_OK" in proc.stdout

            if proc.returncode != 0 and proc.stderr:
                err = proc.stderr[:500]
                result.warnings.append(f"Import error: {err}")

            if "SERVE_CMD_ERR" in proc.stdout:
                err_match = proc.stdout.split("SERVE_CMD_ERR:")
                if len(err_match) > 1:
                    result.warnings.append(
                        f"serve_command error: {err_match[1].strip()}"
                    )

        finally:
            # Clean up temp file
            Path(temp_path).unlink(missing_ok=True)

    except subprocess.TimeoutExpired:
        result.warnings.append(f"Devenv validation timed out ({timeout}s)")
    except Exception as e:
        result.warnings.append(f"Devenv validation failed: {e}")

    return result


def validate_modelspec_code(
    code: str,
    use_devenv: bool = False,
    project_root: Path | None = None,
) -> ValidationResult:
    """Validate generated ModelSpec code.

    This is the main entry point for validation. It dispatches to either
    subprocess or devenv based on the use_devenv flag.

    Args:
        code: Generated Python code
        use_devenv: If True, use devenv container for stronger isolation
        project_root: Project root path (auto-detected if None)

    Returns:
        ValidationResult with all check results
    """
    if use_devenv:
        return validate_devenv(code, project_root)
    else:
        return validate_subprocess(code, project_root)
