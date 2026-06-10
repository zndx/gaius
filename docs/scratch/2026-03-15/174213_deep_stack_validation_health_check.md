# Deep Stack Validation Health Check + RCA Escalation

## Summary

Implemented three-component health infrastructure to catch silent pipeline failures, then fixed the root cause: KUBECONFIG sync.

1. **Metaflow Stack Health Check** (`checker.py`) — validates the full pg_cron -> NOTIFY -> engine -> Metaflow -> K8s chain
2. **RCA-Aware Escalation** (`checker.py`, `observe.py`, `cli.py`) — correlates multiple failures to common root causes, skips individual tier-0 remediation, escalates directly to ACP
3. **MetaflowFixStrategy** (`service_fixes.py`) — automated remediation for the new check
4. **KUBECONFIG auto-sync** — systemd drop-in + just recipes to permanently keep kubeconfig in sync

## Files Modified

| File | Changes |
|------|---------|
| `src/gaius/health/checker.py` | `HealthCheck.slow` field, `RCANotice` dataclass, `_DEPENDENCY_MAP` with sentinel checks and `curation_pipeline` group, `_detect_root_cause()`, `_check_metaflow_stack()` with KUBECONFIG diagnosis + staleness detection |
| `src/gaius/health/service_fixes.py` | `MetaflowFixStrategy` (3-step: diagnose KUBECONFIG/K8s/pods/service, restart port-forward, verify) |
| `src/gaius/health/observe.py` | `_run_health_check()` uses `include_slow=True`, `_process_failures()` with RCA-aware escalation |
| `src/gaius/cli.py` | `rca_notices` in JSON output, "Root Cause Analysis" section in markdown report |
| `db/migrations/20260315000001_metaflow_fmea.sql` | 3 FMEA entries: MF_001 (RPN 84), MF_002 (RPN 120), MF_003 (RPN 162) |
| `build/dev/current/heuristics/gaius/infrastructure/metaflow_stack_down.md` | KB heuristic with KUBECONFIG root cause, `just kubeconfig-sync` remediation |
| `scripts/lib/kubeconfig-sync.sh` | Sync script: copies `/etc/rancher/rke2/rke2.yaml` to `~/.config/kube/rke2.yaml` |
| `infra/systemd/rke2-kubeconfig-sync.conf` | systemd drop-in: `ExecStartPost` on rke2-server that auto-syncs kubeconfig |
| `justfile` | Added `kubeconfig-sync` and `kubeconfig-install-systemd` recipes |

## Key Design Decisions

- **KUBECONFIG auto-sync**: systemd `ExecStartPost` drop-in on `rke2-server.service` runs `kubeconfig-sync.sh` after every K8s restart. No manual intervention needed, no stale copies.
- **Staleness detection**: Health check compares mtime of system vs user kubeconfig. If system is newer, suggests `just kubeconfig-sync`.
- **Slow check pattern**: `HealthCheck.slow=True` skips the check in default health. Only the HealthObserver daemon runs it.
- **RCA sentinel checks**: Each dependency group has a sentinel check. If the sentinel passes, the group is NOT the root cause — eliminates false positives.
- **RCA groups**: `k8s`, `postgres`, `engine`, `curation_pipeline` — `curation_pipeline` captures the metaflow_stack -> landing_page -> content_freshness causal chain.

## Guru Meditation Codes

| Code | Description |
|------|-------------|
| `#MF.00000003.STACKDOWN` | Full Metaflow stack unreachable |
| `#HL.00003.ROOTCAUSE` | Multiple failures share common root cause |

## Verification

```
# KUBECONFIG sync
just kubeconfig-sync                    # -> Synced ... rke2.yaml
just kubeconfig-install-systemd         # -> Drop-in installed
systemctl cat rke2-server | grep ExecStartPost  # -> kubeconfig-sync.sh

# Default health (30 checks) — no false RCA
uv run gaius-cli --cmd "/health" --format json
# 22/30 passed, 4 warnings, 4 failures, rca_notices: null

# With slow checks (31 checks, includes Metaflow Stack)
# 22/31 passed, 4 warnings, 5 failures
# K8s cluster: reachable (via ~/.config/kube/rke2.yaml)
# RCA: curation_pipeline -> [landing_page_pipeline, metaflow_stack]
```
