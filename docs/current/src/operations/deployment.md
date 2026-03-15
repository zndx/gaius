# Deployment

Gaius uses a hybrid deployment model: process-compose for the core platform (engine, databases, GPU workloads) and RKE2 Kubernetes for supporting services (Metaflow, infrastructure automation).

## Local Platform (process-compose)

The core platform runs locally via devenv process-compose. This includes PostgreSQL, Qdrant, the gRPC engine (37 services), NiFi, Metabase, and the Aeron IPC transport.

```bash
devenv processes up    # Start all services
devenv processes down  # Stop all services
just restart-clean     # Clean restart (preferred — ~13s warm start)
```

Process startup scripts live in `scripts/processes/*.sh` — each follows a standard pattern with shared helpers for dependency waiting, banner display, and health checks. See [Process Scripts](./processes.md) for the architecture.

## Kubernetes Services (RKE2)

Supporting services run in RKE2 Kubernetes:

| Service | Namespace | Purpose | Access |
|---------|-----------|---------|--------|
| Metaflow metadata | default | Flow run tracking | Port 8180 (forwarded from 8080) |
| Metaflow UI | default | Web dashboard for pipeline runs | Port 8083 |

Kubernetes resources are managed via Tilt in `infra/tilt/`. The kubeconfig is copied from `/etc/rancher/rke2/rke2.yaml` to `~/.config/kube/rke2.yaml` (the RKE2 original is root-owned).

## Service Dependency Graph

```
PostgreSQL ← NiFi, Engine, Metabase, Metaflow DB
Aeron ← Engine, Worker
Engine ← Worker (background tasks)
Kubernetes ← Metaflow Bootstrap, Port Forwards, UI
```

Process-compose manages the dependency ordering. `just restart-clean` handles the full lifecycle: stop all services, clean state, restart in dependency order.

## See Also

- [Kubernetes](./k8s.md) — RKE2 configuration
- [Metaflow Service](./metaflow-service.md) — Metaflow deployment
- [Infrastructure](./infrastructure.md) — Component overview
