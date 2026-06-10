# devenv Environment

Gaius uses [devenv](https://devenv.sh/) for a Nix-based development environment that provides all system dependencies reproducibly.

## Structure

`devenv.nix` is a pure service declaration file. It defines:

- **Packages**: System tools (kubectl, k9s, mdbook, etc.) provided by Nix
- **Environment variables**: DATABASE_URL, PGPORT, KUBECONFIG, etc.
- **Process definitions**: One-liner `exec` blocks pointing to scripts
- **Dependency graphs**: Process startup ordering via `depends_on`
- **enterShell**: Interactive shell setup (PATH, aliases, KUBECONFIG)

## Key Design Rules

### No Inline Bash

All process startup bash lives in `scripts/processes/*.sh`. The `devenv.nix` exec blocks are one-liners:

```nix
processes.gaius-engine = {
  exec = ''
    exec ${config.devenv.root}/scripts/processes/gaius-engine.sh
  '';
};
```

### Nix Store Paths as Env Vars

When a script needs Nix-managed binaries, pass them as environment variables:

```nix
processes.nifi = {
  exec = ''
    export NIFI_PACKAGE="${pkgs.nifi}"
    exec ${config.devenv.root}/scripts/processes/nifi.sh
  '';
};
```

### KUBECONFIG Handling

`enterShell` only runs for interactive shells. Process scripts must set KUBECONFIG unconditionally from `$HOME`:

```bash
export KUBECONFIG="$HOME/.config/kube/rke2.yaml"
```

Never use fallback syntax (`${KUBECONFIG:-...}`) — the system KUBECONFIG may point to a root-owned path.

## Environment Variables

| Variable | Value | Source |
|----------|-------|--------|
| `DATABASE_URL` | `postgres://gaius:gaius@localhost:5444/zndx_gaius` | devenv.nix |
| `PGPORT` | `5444` | devenv.nix |
| `KUBECONFIG` | `~/.config/kube/rke2.yaml` | enterShell |
| `METAFLOW_SERVICE_URL` | `http://localhost:30180` | enterShell |

## Nix-Managed Tools

`kubectl` and `k9s` are provided by Nix (not the system RKE2 binary). This ensures version consistency across environments.
