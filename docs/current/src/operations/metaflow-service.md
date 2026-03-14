# Metaflow Service

The Metaflow metadata service runs in Kubernetes and enables local flow execution with centralized run tracking.

## Deployment

Metaflow service is deployed via Tilt in `infra/tilt/`.

## Port Forwarding

The service runs in-cluster and needs port-forwarding for local access:

```bash
kubectl port-forward svc/metaflow-service 8180:8080
```

This is handled automatically by the `metaflow-port-forwards.sh` process script.

## Environment

Set the service URL for flow runs:

```bash
export METAFLOW_SERVICE_URL=http://localhost:8180
```

This is set automatically by `enterShell` in devenv.nix.

## Database

Metaflow uses the same PostgreSQL instance (port 5444) with its own database, set up by the `metaflow-db-setup.sh` process script.

## Bootstrapping

The `metaflow-bootstrap.sh` script handles initial K8s resource creation for the Metaflow service.
