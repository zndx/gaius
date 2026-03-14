# Kubernetes

Gaius uses an RKE2 cluster for running Metaflow and supporting services.

## Kubeconfig Setup

RKE2 installs its kubeconfig at `/etc/rancher/rke2/rke2.yaml` (root-owned). Copy it to a user-accessible location:

```bash
mkdir -p ~/.config/kube
sudo cp /etc/rancher/rke2/rke2.yaml ~/.config/kube/rke2.yaml
sudo chown $(id -u):$(id -g) ~/.config/kube/rke2.yaml
```

Set KUBECONFIG:
```bash
export KUBECONFIG="$HOME/.config/kube/rke2.yaml"
```

This is set automatically by `enterShell` in devenv.nix for interactive shells. Process scripts set it unconditionally.

## Nix-Managed Tools

`kubectl` and `k9s` are provided by Nix packages in devenv.nix — not the system RKE2 binary. This ensures version consistency.

## Pod Networking

K8s pods need `pg_hba.conf` entries for cluster networks:

```
host all all 10.42.0.0/16 md5   # Pod network
host all all 10.43.0.0/16 md5   # Service network
```

## Tilt

Development iteration on K8s resources uses Tilt, configured in `infra/tilt/`.

## Cleanup

```bash
just k8s-cleanup    # Clean up stale K8s resources
```
