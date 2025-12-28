"""Cerebras Inference API client.

Provides access to Cerebras' ultra-fast inference service for open-weight models.
This offers an alternative to renting GPUs - pay per token instead of per hour.

Key advantages:
- Extremely fast inference (2000+ tokens/sec for some models)
- No GPU management needed
- Pay only for what you use
- Supports large models that may not fit on local hardware

Usage:
    from gaius.providers.cerebras import CerebrasClient

    client = CerebrasClient()
    models = await client.get_available_models()
    match = client.find_matching_model("llama-3.1-70b")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


@dataclass
class CerebrasModel:
    """Cerebras hosted model specification."""

    model_id: str  # API model identifier
    name: str  # Human-readable name
    params_b: float  # Approximate parameter count in billions
    context_length: int  # Max context window
    input_price_per_m: float  # $ per million input tokens
    output_price_per_m: float  # $ per million output tokens
    speed_tokens_per_sec: int  # Approximate output speed
    family: str  # Model family (llama, qwen, etc.)
    is_preview: bool = False  # Preview models may be discontinued

    @property
    def avg_price_per_m(self) -> float:
        """Average price per million tokens (input + output / 2)."""
        return (self.input_price_per_m + self.output_price_per_m) / 2

    def matches_model(self, model_id: str) -> bool:
        """Check if this Cerebras model could serve the given model ID.

        Matches based on model family and approximate size.
        """
        model_lower = model_id.lower()

        # Extract family from model_id
        if "llama" in model_lower:
            if self.family != "llama":
                return False
            # Check size match
            if "70b" in model_lower and self.params_b >= 65:
                return True
            if "8b" in model_lower and 7 <= self.params_b <= 10:
                return True
            if "405b" in model_lower and self.params_b >= 400:
                return True

        elif "qwen" in model_lower:
            if self.family != "qwen":
                return False
            if "32b" in model_lower and 30 <= self.params_b <= 35:
                return True
            if "235b" in model_lower and self.params_b >= 200:
                return True

        elif "deepseek" in model_lower:
            # DeepSeek R1 distilled to Llama architecture
            if "r1" in model_lower and "70b" in model_lower:
                return self.family == "llama" and self.params_b >= 65

        return False


# Static model catalog (from Cerebras pricing page, Dec 2025)
# These are the models available via Cerebras Inference API
CEREBRAS_MODELS: list[CerebrasModel] = [
    CerebrasModel(
        model_id="llama3.1-8b",
        name="Llama 3.1 8B",
        params_b=8,
        context_length=128000,
        input_price_per_m=0.10,
        output_price_per_m=0.10,
        speed_tokens_per_sec=2200,
        family="llama",
    ),
    CerebrasModel(
        model_id="llama-3.3-70b",
        name="Llama 3.3 70B",
        params_b=70,
        context_length=128000,
        input_price_per_m=0.85,
        output_price_per_m=1.20,
        speed_tokens_per_sec=2100,
        family="llama",
    ),
    CerebrasModel(
        model_id="qwen-3-32b",
        name="Qwen 3 32B",
        params_b=32,
        context_length=32000,
        input_price_per_m=0.40,
        output_price_per_m=0.80,
        speed_tokens_per_sec=2600,
        family="qwen",
    ),
    CerebrasModel(
        model_id="qwen-3-235b-instruct",
        name="Qwen 3 235B Instruct",
        params_b=235,
        context_length=32000,
        input_price_per_m=0.60,
        output_price_per_m=1.20,
        speed_tokens_per_sec=1400,
        family="qwen",
        is_preview=True,
    ),
    CerebrasModel(
        model_id="gpt-oss-120b",
        name="GPT OSS 120B",
        params_b=120,
        context_length=32000,
        input_price_per_m=0.35,
        output_price_per_m=0.75,
        speed_tokens_per_sec=3000,
        family="gpt-oss",
    ),
    CerebrasModel(
        model_id="glm-4.6",
        name="GLM 4.6",
        params_b=9,  # Approximate
        context_length=128000,
        input_price_per_m=2.25,
        output_price_per_m=2.75,
        speed_tokens_per_sec=1000,
        family="glm",
        is_preview=True,
    ),
]


class CerebrasClient:
    """Client for Cerebras Inference API."""

    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        """Initialize Cerebras client.

        Args:
            api_key: Cerebras API key (uses config/env if not provided)
            api_base: API base URL (uses config/env if not provided)
        """
        self._api_key = api_key
        self._api_base = api_base

    @property
    def api_key(self) -> str:
        """Get API key from config or environment."""
        if self._api_key:
            return self._api_key

        try:
            from ..core.config import get_config
            config = get_config()
            if config.providers.cerebras.api_key:
                return config.providers.cerebras.api_key
        except Exception:
            pass

        import os
        return os.getenv("CEREBRAS_API_KEY", "")

    @property
    def api_base(self) -> str:
        """Get API base URL from config or default."""
        if self._api_base:
            return self._api_base

        try:
            from ..core.config import get_config
            config = get_config()
            return config.providers.cerebras.api_base
        except Exception:
            return "https://api.cerebras.ai/v1"

    @property
    def has_api_key(self) -> bool:
        """Check if API key is configured."""
        return bool(self.api_key)

    async def get_available_models(self) -> list[CerebrasModel]:
        """Get available models from Cerebras API.

        Returns static catalog if API unavailable.
        """
        if not self.has_api_key:
            logger.debug("No Cerebras API key - using static model catalog")
            return CEREBRAS_MODELS

        import httpx

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self.api_base}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()

                # API returns list of model objects
                # For now, we merge with static catalog for pricing info
                api_models = {m.get("id"): m for m in data.get("data", [])}

                models = []
                for static_model in CEREBRAS_MODELS:
                    # Check if model is available via API
                    if static_model.model_id in api_models:
                        models.append(static_model)
                    else:
                        # Try partial matching
                        for api_id in api_models:
                            if static_model.model_id in api_id or api_id in static_model.model_id:
                                models.append(static_model)
                                break

                return models if models else CEREBRAS_MODELS

        except Exception as e:
            logger.warning(f"Cerebras API error: {e} - using static catalog")
            return CEREBRAS_MODELS

    def find_matching_model(self, hf_model_id: str) -> CerebrasModel | None:
        """Find a Cerebras model that can serve a given HuggingFace model.

        Args:
            hf_model_id: HuggingFace model ID (e.g., "meta-llama/Llama-3.1-70B-Instruct")

        Returns:
            Matching CerebrasModel or None if no match found
        """
        for model in CEREBRAS_MODELS:
            if model.matches_model(hf_model_id):
                return model
        return None

    def estimate_cost(
        self,
        model: CerebrasModel,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Estimate cost for a given request.

        Args:
            model: Cerebras model to use
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Estimated cost in USD
        """
        input_cost = (input_tokens / 1_000_000) * model.input_price_per_m
        output_cost = (output_tokens / 1_000_000) * model.output_price_per_m
        return input_cost + output_cost

    def compare_to_gpu_rental(
        self,
        model: CerebrasModel,
        gpu_cost_per_hour: float,
        tokens_per_hour: int = 100_000,
    ) -> dict:
        """Compare Cerebras API cost to GPU rental for a workload.

        Args:
            model: Cerebras model
            gpu_cost_per_hour: Cost to rent GPU instance (e.g., Lambda Labs)
            tokens_per_hour: Expected token throughput per hour

        Returns:
            Dict with cost comparison and break-even analysis
        """
        # Assume 50/50 input/output split
        hourly_cerebras_cost = self.estimate_cost(
            model,
            input_tokens=tokens_per_hour // 2,
            output_tokens=tokens_per_hour // 2,
        )

        # Break-even: at what usage does GPU rental become cheaper?
        # GPU cost = Cerebras cost
        # gpu_cost_per_hour = tokens * avg_price_per_m / 1M
        # tokens = gpu_cost_per_hour * 1M / avg_price_per_m
        break_even_tokens = int(gpu_cost_per_hour * 1_000_000 / model.avg_price_per_m)

        return {
            "cerebras_cost_per_hour": hourly_cerebras_cost,
            "gpu_cost_per_hour": gpu_cost_per_hour,
            "cheaper_option": "cerebras" if hourly_cerebras_cost < gpu_cost_per_hour else "gpu",
            "savings_per_hour": abs(gpu_cost_per_hour - hourly_cerebras_cost),
            "break_even_tokens_per_hour": break_even_tokens,
            "cerebras_speed_tokens_sec": model.speed_tokens_per_sec,
        }

    def format_options_markdown(self, hf_model_id: str, gpu_cost_per_hour: float | None = None) -> str:
        """Format Cerebras options as markdown for KB entry.

        Args:
            hf_model_id: HuggingFace model ID to find alternatives for
            gpu_cost_per_hour: Optional GPU rental cost for comparison

        Returns:
            Markdown formatted options text
        """
        match = self.find_matching_model(hf_model_id)

        if not match:
            return ""

        lines = [
            "## Hosted Inference Option (Cerebras)",
            "",
            f"**Available via Cerebras API**: `{match.model_id}`",
            f"- **Speed**: ~{match.speed_tokens_per_sec:,} tokens/sec",
            f"- **Pricing**: ${match.input_price_per_m:.2f}/M input, ${match.output_price_per_m:.2f}/M output",
            f"- **Context**: {match.context_length:,} tokens",
        ]

        if match.is_preview:
            lines.append("- [!] *Preview model - may be discontinued*")

        # Add cost comparison if GPU cost provided
        if gpu_cost_per_hour:
            comparison = self.compare_to_gpu_rental(match, gpu_cost_per_hour)
            lines.extend([
                "",
                "### Cost Comparison (100K tokens/hr workload)",
                f"- **Cerebras API**: ${comparison['cerebras_cost_per_hour']:.2f}/hr",
                f"- **GPU Rental**: ${comparison['gpu_cost_per_hour']:.2f}/hr",
                f"- **Break-even**: {comparison['break_even_tokens_per_hour']:,} tokens/hr",
            ])

            if comparison["cheaper_option"] == "cerebras":
                lines.append(f"- [+] Cerebras is **${comparison['savings_per_hour']:.2f}/hr cheaper** at this usage")
            else:
                lines.append(f"- [i] GPU rental is cheaper for sustained high-volume usage")

        lines.extend([
            "",
            "**Cerebras advantages**: No GPU management, instant scaling, pay-per-token",
            "",
        ])

        return "\n".join(lines)
