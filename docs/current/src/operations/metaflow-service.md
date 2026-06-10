# Metaflow Service

The Metaflow metadata service runs in Kubernetes and enables local flow execution with centralized run tracking.

## Deployment

Metaflow service is deployed via Tilt in `infra/tilt/`.

## Network Access

The service is exposed via K8s NodePort (30180) for local access. The `metaflow-port-forwards.sh` process script patches the service to NodePort automatically on startup.

## Environment

Set the service URL for flow runs:

```bash
export METAFLOW_SERVICE_URL=http://localhost:30180
```

This is set automatically by `enterShell` in devenv.nix.

## Database

Metaflow uses the same PostgreSQL instance (port 5444) with its own database, set up by the `metaflow-db-setup.sh` process script.

## Bootstrapping

The `metaflow-bootstrap.sh` script handles initial K8s resource creation for the Metaflow service.
