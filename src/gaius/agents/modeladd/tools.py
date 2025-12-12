"""Tool primitives for model add workflow.

These are pure functions that can be called from:
- CLI (legacy mode)
- MCP tools (for agent access)
- Orchestrator agent

The functions are extracted from cli.py to enable agent-driven orchestration.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class HFModelData:
    """Comprehensive HuggingFace model data."""

    model_id: str
    api_info: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)
    readme: str | None = None


@dataclass
class ValidationResult:
    """Result of code validation."""

    syntax: bool = False
    imports: bool = False
    serve_cmd: bool = False
    warnings: list[str] = field(default_factory=list)
    variable_name: str | None = None

    @property
    def is_valid(self) -> bool:
        """Check if all validation checks passed."""
        return self.syntax and self.imports and self.serve_cmd


@dataclass
class CritiqueResult:
    """Result of XAI code critique."""

    score: float = 0.0
    issues: list[dict] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    approved: bool = False
    model_used: str = ""


@dataclass
class GenerationResult:
    """Result of code generation."""

    code: str
    model_used: str
    endpoint_used: str


# =============================================================================
# HuggingFace Data Fetching
# =============================================================================


async def fetch_hf_model_data(model_id: str) -> HFModelData:
    """Fetch comprehensive model data from HuggingFace.

    Args:
        model_id: HuggingFace model ID (e.g., mistralai/Mistral-7B-Instruct-v0.3)

    Returns:
        HFModelData with api_info, config, and readme
    """
    import httpx

    data = HFModelData(model_id=model_id)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        # API metadata
        api_url = f"https://huggingface.co/api/models/{model_id}"
        try:
            resp = await client.get(api_url)
            if resp.status_code == 200:
                data.api_info = resp.json()
        except Exception:
            pass

        # config.json for context_length, architecture
        config_url = f"https://huggingface.co/{model_id}/raw/main/config.json"
        try:
            resp = await client.get(config_url)
            if resp.status_code == 200:
                data.config = resp.json()
        except Exception:
            pass

        # README.md (truncated for prompt)
        readme_url = f"https://huggingface.co/{model_id}/raw/main/README.md"
        try:
            resp = await client.get(readme_url)
            if resp.status_code == 200:
                # Truncate to avoid huge prompts
                data.readme = resp.text[:4000]
        except Exception:
            pass

    return data


# =============================================================================
# Coding Model Discovery
# =============================================================================


async def get_coding_model_endpoint() -> tuple[str, str]:
    """Get best available coding model endpoint.

    Tries local coding model first (port 8082), then falls back to Grok API.

    Returns:
        Tuple of (model_id, endpoint_url)

    Raises:
        RuntimeError: If no coding model is available
    """
    # Try engine-managed coding endpoint (agent-first)
    try:
        from ...client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

        if use_engine_proxy():
            orch = await get_orchestrator_proxy()
            result = await orch.ensure_endpoint("coding")
            if result.get("healthy"):
                port = result.get("port", 8082)
                model_id = result.get("model", "coding")
                return (model_id, f"http://localhost:{port}/v1")
    except Exception:
        pass

    # Fallback to Grok via XAI API
    if os.getenv("XAI_API_KEY"):
        return ("grok-2-latest", "https://api.x.ai/v1")

    raise RuntimeError(
        "No coding model available. Either:\n"
        "  - Start the Gaius engine (gaius-engine start)\n"
        "  - Set XAI_API_KEY environment variable"
    )


async def check_coding_endpoint(port: int = 8082) -> dict:
    """Check if coding endpoint is healthy.

    Args:
        port: Port to check (ignored if engine is available)

    Returns:
        Dict with healthy, model_id, port, error fields
    """
    # Prefer engine-managed endpoint
    try:
        from ...client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

        if use_engine_proxy():
            orch = await get_orchestrator_proxy()
            status = await orch._get_status_async()
            for ep in status.get("endpoints", []):
                if ep.get("name") == "coding" and ep.get("status") == "healthy":
                    return {
                        "healthy": True,
                        "model_id": ep.get("model"),
                        "port": ep.get("port"),
                    }
            return {"healthy": False, "error": "Coding endpoint not running"}
    except Exception as e:
        pass

    # Fallback: direct HTTP check
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"http://localhost:{port}/v1/models")
            if resp.status_code == 200:
                models = resp.json().get("data", [])
                if models:
                    return {
                        "healthy": True,
                        "model_id": models[0].get("id"),
                        "port": port,
                    }
                return {"healthy": False, "error": "No models loaded", "port": port}
            return {"healthy": False, "error": f"HTTP {resp.status_code}", "port": port}
    except Exception as e:
        return {"healthy": False, "error": str(e), "port": port}


# =============================================================================
# Code Generation
# =============================================================================


def build_ai_prompt(hf_data: HFModelData) -> str:
    """Build the user prompt for AI code generation.

    Args:
        hf_data: HuggingFace data

    Returns:
        Formatted prompt string
    """
    model_id = hf_data.model_id
    config = hf_data.config
    api = hf_data.api_info
    readme = hf_data.readme

    # Extract key info
    name = model_id.split("/")[-1]
    context_len = config.get("max_position_embeddings") or config.get(
        "n_positions", 32768
    )
    architectures = config.get("architectures", [])
    model_type = config.get("model_type", "unknown")

    # Estimate parameters
    params_b = estimate_params(api, name)

    # Build prompt
    prompt = f"""Generate a ModelSpec for this model:

Model ID: {model_id}
Model Name: {name}
Architecture: {architectures[0] if architectures else model_type}
Context Length: {context_len}
Parameters: ~{params_b}B
Pipeline: {api.get('pipeline_tag', 'text-generation')}
Tags: {', '.join(api.get('tags', [])[:15])}
Downloads: {api.get('downloads', 0):,}

"""
    if readme:
        # Add truncated README for context
        prompt += f"Model Card (excerpt):\n{readme[:2000]}\n\n"

    prompt += """Generate the ModelSpec Python code. Include appropriate:
- capabilities list based on model type/tags
- task_scores dict with relevant TaskType mappings
- vllm_config with correct tensor_parallel_size for the parameter count
"""
    return prompt


def estimate_params(api_info: dict, name: str) -> float:
    """Estimate model parameters in billions.

    Args:
        api_info: HuggingFace API response
        name: Model name

    Returns:
        Estimated parameter count in billions
    """
    # Try safetensors metadata first
    safetensors = api_info.get("safetensors", {})
    if safetensors and safetensors.get("total"):
        return round(safetensors["total"] / 1e9, 1)

    # Parse from name (e.g., "Mistral-7B", "Qwen-32B", "14B", "30B-A3B")
    match = re.search(r"(\d+(?:\.\d+)?)[Bb]", name)
    if match:
        return float(match.group(1))

    # Check for MoE patterns (e.g., "30B-A3B" means 30B total, 3B active)
    moe_match = re.search(r"(\d+)[Bb]-[Aa](\d+)[Bb]", name)
    if moe_match:
        return float(moe_match.group(1))

    return 7.0  # Conservative default


async def generate_modelspec_code(
    hf_data: HFModelData,
    endpoint_url: str,
    model_id: str,
    system_prompt: str,
    critic_feedback: str | None = None,
) -> GenerationResult:
    """Generate ModelSpec code via AI.

    Args:
        hf_data: HuggingFace data
        endpoint_url: OpenAI-compatible API endpoint
        model_id: Model to use for generation
        system_prompt: System prompt for code generation
        critic_feedback: Optional feedback from previous attempt for retry

    Returns:
        GenerationResult with code and model info

    Raises:
        RuntimeError: If generation fails
    """
    import httpx

    prompt = build_ai_prompt(hf_data)

    if critic_feedback:
        prompt += f"\n\n## IMPORTANT: Previous attempt had issues:\n{critic_feedback}\n\nPlease fix these issues in your new generation."

    # Prepare headers
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("XAI_API_KEY", "")
    if api_key and "x.ai" in endpoint_url:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{endpoint_url}/chat/completions",
            headers=headers,
            json={
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 2000,
            },
        )
        resp.raise_for_status()

    code = resp.json()["choices"][0]["message"]["content"]

    # Strip markdown fences if present
    if "```python" in code:
        code = code.split("```python")[1].split("```")[0]
    elif "```" in code:
        code = code.split("```")[1].split("```")[0]

    return GenerationResult(
        code=code.strip(),
        model_used=model_id,
        endpoint_used=endpoint_url,
    )


# =============================================================================
# Commit to Registry
# =============================================================================


def commit_modelspec_to_registry(
    code: str,
    variable_name: str,
    registry_path: Path | None = None,
) -> dict:
    """Write ModelSpec to registry.py.

    Args:
        code: Generated Python code
        variable_name: Variable name (e.g., MISTRAL_7B)
        registry_path: Path to registry.py (auto-detected if None)

    Returns:
        Dict with success status and details
    """
    if registry_path is None:
        # Auto-detect registry path
        this_file = Path(__file__).resolve()
        registry_path = this_file.parent.parent.parent / "models" / "registry.py"

    if not registry_path.exists():
        return {"error": f"Registry not found at {registry_path}"}

    content = registry_path.read_text()

    # Insert before Registry class definition
    marker = "# " + "=" * 79 + "\n# Registry"
    if marker not in content:
        marker = "class ModelRegistry:"
        if marker not in content:
            return {"error": "Could not find insertion point in registry.py"}

    # Add the new model before the marker
    new_content = content.replace(marker, f"{code}\n\n\n{marker}")

    # Add to defaults list
    defaults_pattern = r"(defaults\s*=\s*\[)"
    if re.search(defaults_pattern, new_content):
        new_content = re.sub(
            defaults_pattern,
            f"\\1\n            {variable_name},",
            new_content,
        )
    else:
        return {"error": "Could not find defaults list in registry.py"}

    # Write the updated registry
    registry_path.write_text(new_content)

    return {
        "success": True,
        "registry_path": str(registry_path),
        "variable_name": variable_name,
    }


# =============================================================================
# XAI Critique
# =============================================================================


async def critique_modelspec_code(
    code: str,
    hf_data: HFModelData,
    hardware_context: dict | None = None,
) -> CritiqueResult:
    """Get XAI Grok critique of generated ModelSpec code.

    Args:
        code: Generated Python code
        hf_data: HuggingFace model data for context
        hardware_context: Optional hardware specs (GPU count, VRAM, model names)
            for validating tensor_parallel_size and max_model_len

    Returns:
        CritiqueResult with score and feedback
    """
    import httpx

    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        return CritiqueResult(
            score=0.0,
            issues=[{"severity": "info", "message": "XAI_API_KEY not set, skipping critique"}],
            suggestions=[],
            approved=False,
            model_used="none",
        )

    # Build system prompt with hardware awareness
    hardware_section = ""
    if hardware_context:
        gpu_count = hardware_context.get("gpu_count", 0)
        gpu_model = hardware_context.get("gpu_model", "unknown")
        total_vram = hardware_context.get("total_vram_mb", 0)
        per_gpu_vram = total_vram // gpu_count if gpu_count > 0 else 0
        hardware_section = f"""
5. Hardware compatibility: Validate against target hardware:
   - GPUs: {gpu_count}x {gpu_model}
   - VRAM per GPU: {per_gpu_vram}MB ({per_gpu_vram / 1024:.1f}GB)
   - Total VRAM: {total_vram}MB ({total_vram / 1024:.1f}GB)

   Check that:
   - tensor_parallel_size <= {gpu_count} (available GPUs)
   - tensor_parallel_size divides evenly into num_attention_heads
   - Model weights (~2 bytes/param for BF16) fit in available VRAM
   - max_model_len is achievable with remaining VRAM after weights
"""

    system_prompt = f"""You are a code reviewer for ModelSpec definitions in the Gaius model registry.

Evaluate the generated code for:
1. Correctness: Valid Python, correct enum usage
2. Accuracy: model_id matches HuggingFace, context_length is accurate
3. Completeness: All required fields populated, reasonable task_scores
4. Best practices: tensor_parallel_size appropriate for model size
{hardware_section}
Respond with JSON:
{{
    "score": 0.0-1.0,
    "issues": [{{"severity": "high|medium|low", "field": "...", "message": "..."}}],
    "suggestions": ["..."],
    "approved": true|false
}}

Approve (score >= 0.7) if the code is usable with minor issues.
"""

    # Build user prompt with hardware context
    hardware_info = ""
    if hardware_context:
        hardware_info = f"""
Target Hardware:
- {hardware_context.get('gpu_count', 0)}x {hardware_context.get('gpu_model', 'unknown')}
- {hardware_context.get('total_vram_mb', 0) / 1024:.1f}GB total VRAM
"""

    user_prompt = f"""Review this ModelSpec code:

```python
{code}
```

Context:
- Model ID: {hf_data.model_id}
- Context Length from config: {hf_data.config.get('max_position_embeddings', 'unknown')}
- Architecture: {hf_data.config.get('architectures', ['unknown'])}
- Tags: {hf_data.api_info.get('tags', [])}
{hardware_info}"""

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json={
                    "model": "grok-2-latest",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1000,
                },
            )
            resp.raise_for_status()

        content = resp.json()["choices"][0]["message"]["content"]

        # Parse JSON from response
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        result = json.loads(content)
        return CritiqueResult(
            score=result.get("score", 0.0),
            issues=result.get("issues", []),
            suggestions=result.get("suggestions", []),
            approved=result.get("approved", False),
            model_used="grok-2-latest",
        )

    except Exception as e:
        return CritiqueResult(
            score=0.0,
            issues=[{"severity": "high", "message": f"Critique failed: {e}"}],
            suggestions=[],
            approved=False,
            model_used="grok-2-latest",
        )
