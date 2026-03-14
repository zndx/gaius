# Inference

The inference layer routes requests across multiple backends: vLLM for local GPU models, optillm for reasoning enhancement, and external APIs (xAI, Cerebras) for cloud-based inference.

## Backend Router

The BackendRouter selects the appropriate backend based on capability requirements:

```python
class BackendRouter:
    async def route_inference(
        self,
        model: str,
        prompt: str,
        max_tokens: int,
        technique: str = "",  # optillm technique
    ) -> str
```

## Backends

| Backend | Purpose | Hardware |
|---------|---------|----------|
| vLLM | Local model inference | 6x NVIDIA GPUs |
| optillm | Reasoning enhancement (CoT, BoN, MoA) | Proxies to vLLM |
| xAI (Grok) | External API inference | Cloud |
| Cerebras | External API inference | Cloud |
| Nomic | Text embeddings | 1 GPU |

## optillm Techniques

| Technique | Description |
|-----------|-------------|
| `cot_reflection` | Chain-of-thought with reflection |
| `bon` | Best-of-N sampling |
| `moa` | Mixture of Agents |
| `rto` | Round-trip optimization |
| `z3` | Z3 solver integration |
| `leap` | Learn from examples |

## Request Flow

```
Client → gRPC → Scheduler → BackendRouter → Backend
                                           ↗ vLLM (local)
                                          ↗ optillm → vLLM
                                         ↗ xAI API (cloud)
```

All inference requests route through the gRPC engine for centralized authentication, audit logging, and resource management.

## Subchapters

- [vLLM Controller](./vllm.md) — GPU process management
- [Makespan Scheduling](./makespan.md) — Multi-workload optimization
- [XAI Budget](./xai-budget.md) — External API rate limiting
