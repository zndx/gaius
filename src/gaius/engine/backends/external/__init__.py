"""External inference backends.

Provides access to external inference APIs (XAI, Cerebras, Bytez)
with unified budget tracking and routing.

Usage:
    from gaius.engine.backends.external import (
        ExternalInferenceRouter,
        get_external_router,
        ExternalBudget,
        get_external_budget,
    )

    # Get singleton router
    router = get_external_router()

    # Complete with auto-routing
    response = await router.complete(messages)

    # Check budget status
    budget = get_external_budget()
    print(budget.to_dict())

Backends:
- XAI: Grok-3 frontier model (per-token)
- Cerebras: zai-glm-4.7 fast inference with reasoning (per-token)
- Bytez: Subscription model (unlimited tokens, 2 concurrent)

Cerebras models use their own ID format (e.g., llama-3.3-70b, zai-glm-4.7, qwen-3-32b).
GLM is a reasoning model that outputs chain-of-thought in the 'reasoning' field.
"""

from .base import ExternalBackend, ExternalResponse, ToolCall
from .budget import (
    ExternalBudget,
    ProviderBudget,
    get_external_budget,
    reset_external_budget,
)
from .router import (
    ExternalInferenceRouter,
    get_external_router,
    reset_external_router,
)
from .xai_backend import XAIBackend
from .cerebras_backend import CerebrasBackend
from .bytez_backend import BytezBackend

__all__ = [
    # Base
    "ExternalBackend",
    "ExternalResponse",
    "ToolCall",
    # Budget
    "ExternalBudget",
    "ProviderBudget",
    "get_external_budget",
    "reset_external_budget",
    # Router
    "ExternalInferenceRouter",
    "get_external_router",
    "reset_external_router",
    # Backends
    "XAIBackend",
    "CerebrasBackend",
    "BytezBackend",
]
