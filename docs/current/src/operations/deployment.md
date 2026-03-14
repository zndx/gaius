# Deployment

Gaius uses RKE2 Kubernetes for production services (Metaflow, supporting infrastructure) and local process-compose for the core platform.

## Local Development

The primary deployment model is local, using devenv process-compose:

```bash
devenv processes up    # Start all services
devenv processes down  # Stop all services
just restart-clean     # Clean restart (preferred)
```

## Kubernetes Services

Supporting services run in RKE2 Kubernetes:

| Service | Namespace | Purpose |
|---------|-----------|---------|
| Metaflow metadata | default | Flow run tracking |
| Metaflow UI | default | Web dashboard |

Kubernetes resources are managed via Tilt in `infra/tilt/`.

## See Also

- [Kubernetes](./k8s.md) — RKE2 configuration
- [Metaflow Service](./metaflow-service.md) — Metaflow deployment
