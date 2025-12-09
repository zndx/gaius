# Inference Gateway Architecture

Gaius implements a secure inference gateway that mediates all LLM requests. This architecture aligns with industry standards while providing local extensions for single-node deployments.

## Why a Gateway Layer?

Direct HTTP access to inference endpoints (optillm, vLLM) creates operational and security challenges:

- **No authentication**: Anyone with network access can invoke models
- **No authorization**: Cannot enforce per-user or per-application quotas
- **No audit trail**: Request/response logging requires application changes
- **No rate limiting**: Runaway scripts can exhaust GPU resources
- **Credential sprawl**: Each client needs provider API keys

A gateway layer centralizes these concerns, allowing applications to authenticate once and rely on the gateway for policy enforcement.

## Industry Standards

### Open Inference Protocol (OIP)

The [Open Inference Protocol](https://github.com/kserve/open-inference-protocol) defines a standard wire format for ML inference:

| Component | Description |
|-----------|-------------|
| **Health API** | Liveness and readiness probes |
| **Metadata API** | Model name, version, inputs/outputs |
| **Inference API** | Request/response for predictions |

OIP provides both REST and gRPC specifications. Major adopters include:

- KServe (reference implementation)
- NVIDIA Triton Inference Server
- Seldon Core
- OpenVINO Model Server
- TorchServe

**Key insight**: OIP defines the *data plane* (how requests are formatted) but not the *control plane* (authentication, routing, rate limiting). These concerns are delegated to a gateway layer.

### KServe + Envoy AI Gateway

[KServe v0.15](https://www.cncf.io/blog/2025/06/18/announcing-kserve-v0-15-advancing-generative-ai-model-serving/) (June 2025) introduced integration with [Envoy AI Gateway](https://aigateway.envoyproxy.io/), a CNCF project built on Envoy Gateway specifically for generative AI traffic.

#### Two-Tier Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Tier One Gateway                          │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ • Unified API entry point                               ││
│  │ • Authentication (internal tokens → provider creds)     ││
│  │ • Global rate limiting                                  ││
│  │ • Route to external providers OR self-hosted clusters   ││
│  └─────────────────────────────────────────────────────────┘│
└──────────────────────────┬──────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
   ┌──────────┐     ┌──────────┐     ┌──────────────┐
   │  OpenAI  │     │ Anthropic│     │ Self-Hosted  │
   │   API    │     │   API    │     │   Cluster    │
   └──────────┘     └──────────┘     └──────┬───────┘
                                            │
                           ┌────────────────┴────────────────┐
                           │       Tier Two Gateway          │
                           │ ┌────────────────────────────┐  │
                           │ │ • Endpoint picker (vLLM)   │  │
                           │ │ • Token-based autoscaling  │  │
                           │ │ • Model routing            │  │
                           │ │ • KV cache coordination    │  │
                           │ └────────────────────────────┘  │
                           └─────────────────────────────────┘
```

#### Key Capabilities

| Feature | Description |
|---------|-------------|
| **Token-based rate limiting** | Limits by tokens consumed, not just requests |
| **Credential injection** | Apps authenticate with internal token; gateway injects provider keys |
| **Dynamic routing** | Route based on request content, model metadata, or user context |
| **Multi-tenant isolation** | Fine-grained access controls per tenant |
| **Unified API** | Abstract whether models are third-party or self-hosted |
| **Endpoint picker** | LLM-aware load balancing for vLLM backends |

## Gaius Architecture

Gaius implements a simplified two-tier pattern optimized for single-node deployments with local GPUs.

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    TUI / CLI / MCP                          │
│                    (Applications)                           │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    gaius-engine                              │
│                    (gRPC Gateway)                            │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ • Authentication boundary                               ││
│  │ • Audit logging                                         ││
│  │ • Resource management                                   ││
│  │ • Scheduler with priority queues                        ││
│  │ • Future: rate limiting, quotas                         ││
│  └─────────────────────────────────────────────────────────┘│
└──────────────────────────┬──────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
   ┌──────────┐     ┌──────────┐     ┌──────────┐
   │ optillm  │     │  vLLM    │     │   XAI    │
   │(reasoning)│    │ (direct) │     │  (eval)  │
   └──────────┘     └──────────┘     └──────────┘
```

### Request Flow

1. **Application** constructs inference request
2. **InferenceClient** checks if gRPC engine is available
3. If available: route through gRPC gateway (authenticated, logged)
4. If unavailable and `GAIUS_ALLOW_FALLBACKS=true`: direct HTTP (dev mode)
5. If unavailable and fallbacks disabled: fail with error

```python
# From src/gaius/inference/client.py
if self._is_grpc_available():
    result = await self._complete_via_grpc(messages, ...)
    if result:
        return result

if not self.config.allow_fallbacks:
    raise RuntimeError(
        "gRPC engine unavailable and fallbacks disabled (secure by default). "
        "Either start the engine (gaius-engine) or enable fallbacks for "
        "development/debugging: GAIUS_ALLOW_FALLBACKS=true"
    )
```

### Security Model

| Mode | gRPC Engine | Direct HTTP | Use Case |
|------|-------------|-------------|----------|
| **Production** (default) | Required | Blocked | Enterprise deployments |
| **Development** | Preferred | Allowed with warning | Local development |

**Production** (secure by default):
- gRPC engine must be running
- All requests authenticated and logged
- Direct HTTP blocked

**Development** (`GAIUS_ALLOW_FALLBACKS=true`):
- gRPC engine preferred if available
- Falls back to direct HTTP with warning
- Warning logged: `FALLBACK: Using direct HTTP to optillm/vLLM - bypasses gRPC auth/authz`

## Feature Comparison

| Feature | KServe/Envoy AI Gateway | Gaius gRPC Gateway |
|---------|------------------------|-------------------|
| **Protocol** | HTTP/gRPC (OIP) | gRPC (custom proto) |
| **Authentication** | OAuth, JWT, mTLS | Internal (planned: mTLS) |
| **Rate limiting** | Token-based | Planned |
| **Credential injection** | Yes | N/A (local models) |
| **Multi-tenant** | Yes | Single tenant |
| **Model routing** | Dynamic | Technique-based (optillm) |
| **Autoscaling** | KEDA integration | Manual / devenv |
| **Endpoint picker** | vLLM-aware | Round-robin |
| **External providers** | OpenAI, Anthropic, etc. | XAI, OpenAI (fallback) |
| **Deployment** | Kubernetes | Single node / devenv |

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GAIUS_ALLOW_FALLBACKS` | `false` | Enable direct HTTP when gRPC unavailable |

### HOCON Configuration

```hocon
# config/base.conf
inference {
    backend = "optillm"
    optillm_url = "http://localhost:8090/v1"
    vllm_url = "http://localhost:8000/v1"
}
```

## Health Checks

The `/health quick` command distinguishes gateway from fallback paths:

```
Service              Status    Details
─────────────────────────────────────────────────
gRPC Engine          healthy   PRIMARY - authenticated inference gateway
optillm Service      healthy   DEV FALLBACK - direct HTTP (no auth)
vLLM Direct          healthy   DEV FALLBACK - direct HTTP (no auth)
```

## Future Alignment

### Planned Enhancements

| Feature | Timeline | Notes |
|---------|----------|-------|
| Token-based rate limiting | v0.3 | Align with Envoy AI Gateway |
| mTLS authentication | v0.3 | Service-to-service security |
| Usage quotas | v0.4 | Per-agent, per-domain limits |
| OIP compatibility | v0.4 | Standard health/metadata endpoints |

### Migration Path to KServe

For deployments that outgrow single-node:

1. **Phase 1**: Run gaius-engine alongside KServe InferenceService
2. **Phase 2**: Route external traffic through Envoy AI Gateway
3. **Phase 3**: Migrate internal traffic to KServe gRPC interface

The gRPC gateway pattern ensures applications don't need modification during migration—only the gateway configuration changes.

## References

- [Open Inference Protocol](https://github.com/kserve/open-inference-protocol) - Wire format specification
- [KServe v0.15 Announcement](https://www.cncf.io/blog/2025/06/18/announcing-kserve-v0-15-advancing-generative-ai-model-serving/) - Envoy AI Gateway integration
- [Envoy AI Gateway Reference Architecture](https://aigateway.envoyproxy.io/blog/envoy-ai-gateway-reference-architecture/) - Two-tier pattern
- [Gaius README](../../../README.md) - Security section on gRPC gateway
