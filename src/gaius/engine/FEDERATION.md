# Federated Engine Architecture

This document describes the Gaius Engine Federation architecture, enabling distributed inference across heterogeneous GPU deployments using standard protocols.

## Overview

The Gaius Engine Federation allows multiple engine nodes to collaborate as a unified inference mesh. Each node can:

- Serve local GPU endpoints directly
- Forward requests to peer nodes when needed capabilities aren't local
- Participate in distributed scheduling decisions
- Mix Gaius engines with vanilla KServe-compatible servers

```mermaid
graph TB
    subgraph "Local Tinybox (Node A)"
        TUI[TUI/CLI]
        MFR[Metaflow Runner]
        Worker[Worker: base_orchestrator.py]
        SP[SchedulerProxy]
        EA[Engine Node A<br/>Port 50051]

        subgraph "Local Endpoints"
            QWQ[QwQ-32B<br/>reasoning]
            ORCH[Orchestrator-8B<br/>orchestrator]
            FAST[Mistral-7B<br/>fast]
        end

        TUI --> MFR
        MFR --> Worker
        Worker -->|"scheduler.complete(agent='massive')"| SP
        SP -->|Gaius gRPC| EA
        EA --> QWQ
        EA --> ORCH
        EA --> FAST
    end

    subgraph "LambdaLabs (Node B)"
        EB[Engine Node B]
        DEVSTRAL[Devstral-2-Large<br/>xlarge_coding]
        EB --> DEVSTRAL
    end

    subgraph "AWS EC2 (Node C)"
        EC[Engine Node C<br/>Port 50051]
        OPUS[Claude Opus<br/>via Bedrock]
        EC --> OPUS
    end

    EA <-->|KServe OIP| EB
    EA <-->|KServe OIP| EC
    EB <-->|KServe OIP| EC
```

## Request Flow Example

When a Metaflow worker needs a capability not available locally:

```mermaid
sequenceDiagram
    participant W as Metaflow Worker
    participant SP as SchedulerProxy
    participant EA as Engine Node A<br/>(Local)
    participant EB as Engine Node B<br/>(LambdaLabs)
    participant K2 as Kimi-K2-Thinking

    W->>SP: complete(agent="massive_reasoning")
    SP->>EA: gRPC: Scheduler.complete

    Note over EA: Capability lookup:<br/>massive_reasoning<br/>NOT available locally

    EA->>EB: KServe OIP: ModelInfer
    EB->>K2: Forward to vLLM

    Note over K2: Extended thinking...<br/>(1T params, 128k context)

    K2-->>EB: Response
    EB-->>EA: KServe OIP Response
    EA-->>SP: gRPC Response
    SP-->>W: CompletionResult
```

## Protocol Layers

The federation uses a layered protocol approach:

```mermaid
graph LR
    subgraph "Gaius Extension Layer"
        GE[Gaius gRPC Protocol]
        WM[Workload Management]
        EV[Evolution Coordination]
        HO[Health Observer]
    end

    subgraph "Standard Layer"
        OIP[KServe Open Inference Protocol]
        MI[ModelInfer]
        MM[ModelMetadata]
        MR[ModelReady]
    end

    subgraph "Transport"
        GRPC[gRPC/HTTP2]
    end

    GE --> OIP
    WM --> OIP
    EV --> OIP
    HO --> OIP
    OIP --> MI
    OIP --> MM
    OIP --> MR
    MI --> GRPC
    MM --> GRPC
    MR --> GRPC
```

### KServe Open Inference Protocol (Standard)

The foundation layer - any compliant server can participate:

| Method | Purpose |
|--------|---------|
| `ModelInfer` | Inference requests with tensor I/O |
| `ModelMetadata` | Model capabilities, shapes |
| `ModelReady` | Model health/readiness |
| `ServerLive` | Server liveness probe |
| `ServerReady` | Server readiness probe |

Compatible implementations:
- vLLM (native support)
- Hugging Face TGI
- NVIDIA Triton (TensorRT-LLM)
- Ray Serve (with KServe adapter)
- Seldon Core
- Any Kubernetes InferenceService

### Gaius Extension Layer (Optional)

Additional capabilities for full-featured nodes:

| Service | Purpose |
|---------|---------|
| `Scheduler` | Capability-based routing, priority queues |
| `Workload` | Multi-step workload resource allocation |
| `Evolution` | Agent training coordination |
| `HealthObserver` | Distributed health monitoring |
| `Cognition` | Cross-node thought synchronization |

Nodes without Gaius extensions simply provide inference - fully valid.

## Capability Registry

Each engine maintains a capability registry:

```mermaid
graph TB
    subgraph "Capability Registry"
        CR[Registry Service]

        subgraph "Local Capabilities"
            LC1[reasoning: QwQ-32B]
            LC2[fast: Mistral-7B]
            LC3[orchestrator: Orchestrator-8B]
        end

        subgraph "Federated Capabilities"
            FC1[massive_reasoning: Node B]
            FC2[managed_inference: Node C]
        end

        CR --> LC1
        CR --> LC2
        CR --> LC3
        CR --> FC1
        CR --> FC2
    end

    subgraph "Routing Decision"
        RD[Request: massive_reasoning]
        RD -->|"Not local"| FC1
        FC1 -->|"Forward"| NodeB[Node B]
    end
```

### Capability Types

| Capability | Description | Typical Provider |
|------------|-------------|------------------|
| `fast` | Low-latency, small model | Local 7B |
| `reasoning` | Extended thinking | Local 32B |
| `coding` | Code generation | Local Coder model |
| `orchestrator` | Tool selection | Local Orchestrator-8B |
| `massive_reasoning` | Frontier-scale thinking | Remote 1T+ model |
| `embedding` | Text/vision embeddings | Local or managed |

## Extended 4-Node Mesh with Cloudera

Adding Cloudera's Inference Service as a fourth node demonstrates how enterprise-managed inference integrates seamlessly with self-hosted and cloud infrastructure:

```mermaid
graph TB
    subgraph "Local Tinybox (Node A)"
        TUI[TUI/CLI]
        MFR[Metaflow Runner]
        Worker[Worker: base_orchestrator.py]
        SP[SchedulerProxy]
        EA[Engine Node A<br/>Port 50051]

        subgraph "Local Endpoints"
            QWQ[QwQ-32B<br/>reasoning]
            ORCH[Orchestrator-8B<br/>orchestrator]
            FAST[Mistral-7B<br/>fast]
        end

        TUI --> MFR
        MFR --> Worker
        Worker -->|"scheduler.complete(agent='massive')"| SP
        SP -->|Gaius gRPC| EA
        EA --> QWQ
        EA --> ORCH
        EA --> FAST
    end

    subgraph "LambdaLabs (Node B)"
        EB[Engine Node B]
        DEVSTRAL[Devstral-2-Large<br/>xlarge_coding]
        EB --> DEVSTRAL
    end

    subgraph "AWS EC2 (Node C)"
        EC[Engine Node C<br/>Port 50051]
        OPUS[Claude Opus<br/>via Bedrock]
        EC --> OPUS
    end

    subgraph "Cloudera (Node D)"
        CIS[Cloudera Inference Service<br/>KServe OIP]
        subgraph "Cloudera ML Models"
            CLLM[Enterprise LLMs<br/>fine-tuned]
            CEMB[Domain Embeddings<br/>specialized]
        end
        CIS --> CLLM
        CIS --> CEMB
    end

    EA <-->|KServe OIP| EB
    EA <-->|KServe OIP| KS
    EA <-->|KServe OIP| CIS
    EB <-->|KServe OIP| KS
    EB <-->|KServe OIP| CIS
    KS <-->|KServe OIP| CIS
```

### Cloudera Inference Service Integration

Cloudera's AI Inference service provides KServe Open Inference Protocol endpoints, making it a first-class participant in the federation:

| Feature | Cloudera CIS |
|---------|--------------|
| Protocol | KServe OIP (native) |
| Authentication | CDP workload auth |
| Model Types | Fine-tuned LLMs, domain embeddings |
| Deployment | Cloudera Machine Learning |
| GPU Support | NVIDIA GPUs via CML |

### Configuration for Cloudera Node

```hocon
gaius {
  engine {
    federation {
      peers = [
        # ... existing peers ...
        {
          id = "cloudera-cis"
          endpoint = "grpc://cis.cloudera.example.com:443"
          capabilities = ["enterprise_llm", "domain_embedding"]
          protocol = "kserve"  # Standard KServe OIP

          # CDP workload authentication
          auth {
            type = "cdp_workload"
            credential_provider = "env"  # Uses CDP_WORKLOAD_* env vars
          }

          # Enterprise SLA settings
          cost_multiplier = 0.8  # On-prem advantage
          timeout_ms = 30000
          retry_policy = "exponential"
        }
      ]
    }
  }
}
```

### Use Cases for Cloudera Node

1. **Domain-Specific Models**: Fine-tuned models for financial, healthcare, or industrial domains
2. **Data Locality**: Keep inference close to data lakes for compliance
3. **Enterprise Embeddings**: Specialized embedding models trained on proprietary corpora
4. **Hybrid Burst**: Use Cloudera for steady-state, burst to cloud for peaks

## Deployment Patterns

### Pattern 1: Local + Burst

Primary workloads run locally; burst to cloud for peak demand.

```mermaid
graph LR
    subgraph "Always On (Tinybox)"
        A[Engine A]
        A --> R[reasoning]
        A --> F[fast]
    end

    subgraph "On Demand (LambdaLabs)"
        B[Engine B]
        B --> M[massive]
    end

    A -->|"Burst traffic"| B
    B -.->|"Scale to zero"| X[Terminated]
```

### Pattern 2: Hybrid Cloud

Mix self-hosted and managed services:

```mermaid
graph TB
    subgraph "Self-Hosted"
        E1[Engine]
        E1 --> V1[vLLM: Private Models]
    end

    subgraph "Managed (GKE)"
        KS[KServe]
        KS --> V2[Vertex AI]
    end

    subgraph "API Provider"
        API[OpenAI-compatible]
        API --> GPT[GPT-4]
    end

    E1 <--> KS
    E1 <--> API
```

### Pattern 3: Multi-Region

Distribute for latency and redundancy:

```mermaid
graph TB
    subgraph "US-West"
        UW[Engine US-W]
    end

    subgraph "US-East"
        UE[Engine US-E]
    end

    subgraph "EU"
        EU[Engine EU]
    end

    UW <-->|"Peer mesh"| UE
    UE <-->|"Peer mesh"| EU
    EU <-->|"Peer mesh"| UW

    C1[Client West] --> UW
    C2[Client East] --> UE
    C3[Client EU] --> EU
```

## Configuration

### Peer Discovery

Peers are configured in `agents.conf`:

```hocon
gaius {
  engine {
    federation {
      # Local node identity
      node_id = "tinybox-local"

      # Peer nodes
      peers = [
        {
          id = "lambda-burst"
          endpoint = "grpc://lambda.example.com:50051"
          capabilities = ["xlarge_coding"]
          cost_multiplier = 1.5  # Cloud premium
        },
        {
          id = "aws-ec2"
          endpoint = "grpc://ec2-gaius.us-east-1.example.com:50051"
          capabilities = ["frontier_reasoning"]
          # Full Gaius engine with Bedrock backend for Claude Opus
        }
      ]

      # Routing policy
      routing {
        prefer_local = true
        cost_weight = 0.3
        latency_weight = 0.7
      }
    }
  }
}
```

### Capability Advertisement

Each node advertises its capabilities on startup:

```python
from gaius.engine.federation import FederationService

federation = FederationService(config)
await federation.advertise_capabilities([
    Capability(name="reasoning", model="Qwen/QwQ-32B", gpu_memory_gb=48),
    Capability(name="fast", model="mistralai/Mistral-7B", gpu_memory_gb=16),
])
```

## Security Considerations

### Authentication

Inter-node communication uses mTLS:

```mermaid
graph LR
    A[Node A] -->|"mTLS"| B[Node B]

    subgraph "Certificate Chain"
        CA[Federation CA]
        CA --> NA[Node A Cert]
        CA --> NB[Node B Cert]
    end
```

### Authorization

Capability-based access control:

| Capability | Access Level |
|------------|--------------|
| `public` | Any authenticated node |
| `internal` | Same organization |
| `restricted` | Explicit allowlist |

## Observability

### Distributed Tracing

Requests carry trace context across nodes:

```mermaid
graph LR
    subgraph "Trace: abc123"
        S1[Span: Worker] --> S2[Span: Engine A]
        S2 --> S3[Span: Engine B]
        S3 --> S4[Span: Kimi-K2]
    end
```

### Metrics

Each node exports federation metrics:

| Metric | Description |
|--------|-------------|
| `federation_requests_total` | Requests by destination node |
| `federation_latency_seconds` | Cross-node latency |
| `federation_errors_total` | Failed federation calls |
| `capability_availability` | Per-capability health |

## Future Directions

1. **Dynamic Peer Discovery** - mDNS/DNS-SD for local network nodes
2. **Capability Negotiation** - Runtime capability matching
3. **Cost-Aware Routing** - Real-time pricing integration
4. **Federated Training** - Distributed model fine-tuning
5. **State Synchronization** - Cross-node KB replication

## References

- [KServe Open Inference Protocol](https://github.com/kserve/open-inference-protocol)
- [gRPC Service Definition](./proto/gaius_service.proto)
- [Engine Architecture](./README.md)
