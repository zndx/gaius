# Metaflow Health Framework Enhancement

## Summary

Enhanced the health framework's Metaflow stack check with deeper K8s validation,
fixed a port mismatch (8180 -> 30180), and resolved the CoreDNS DNS loop that was
blocking all K8s services.

## Root Cause Chain

```
CoreDNS CrashLoopBackOff (forward . /etc/resolv.conf -> 127.0.0.53 -> loop)
  -> K8s pod DNS resolution fails
  -> Metaflow init container can't resolve "devenv-postgres"
  -> Metaflow service pod stuck in Unknown state
  -> Port 30180 has nothing listening
  -> No flow runs, content stale
```

## Changes Made

### Port Fix (8180 -> 30180)
- `checker.py`: Default Metaflow service URL
- `service_fixes.py`: Diagnosis and wait steps
- `devenv.nix`: Added `METAFLOW_SERVICE_URL` to `enterShell`
- All docs and heuristics updated

### Enhanced K8s Validation (checker.py)
- Added pod status check after `cluster-info` (step 3b)
- Added CoreDNS health check (step 3c)
- Detects CrashLoopBackOff, Error, Unknown states
- Reports `coredns_status` and `coredns_remediation` in details

### Enhanced MetaflowFixStrategy (service_fixes.py)
- Fixed label selector: `app=metaflow-service` -> `app.kubernetes.io/name=metaflow-service`
- Added CoreDNS check in diagnosis (before Metaflow pods)
- Added init container status reporting
- Added dedicated CoreDNS health step (step 2b) with guru code `#MF.00000004.DNSDOWN`

### CLI Integration (cli.py)
- Added `metaflow`/`k8s` to `/health fix` service dispatch
- Uses `RemediationExecutor` from the remediation framework
- Supports `--dry-run`

### FMEA
- Added MF_004 to SQL migration and Python registry
- Severity 9, Occurrence 2, Detection 7 (RPN 126)

### Infrastructure Fix
- CoreDNS ConfigMap: `forward . /etc/resolv.conf` -> `forward . 192.168.1.1 8.8.8.8`
- Restarted CoreDNS deployment, Metaflow service, Metaflow UI
- All pods now 1/1 Running

## Key Discovery

The plan originally identified kubectl version mismatch (v1.35.0 vs v1.34.3) as a
gap. Investigation showed both versions produce the same API discovery stderr
warnings, but `get pods` works fine with both. The warnings are cosmetic.

The real bugs were:
1. Wrong label selector in diagnosis (`app=` vs `app.kubernetes.io/name=`)
2. No CoreDNS or pod-level checks in the health checker
3. Wrong default port (8180 vs 30180)
4. `/health fix metaflow` not wired in CLI dispatch
