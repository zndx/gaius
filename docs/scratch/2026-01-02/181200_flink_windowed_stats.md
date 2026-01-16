# Flink-Inspired Windowed Stats for Observe Panel

**Date:** 2026-01-02
**Status:** Complete

## Summary

Updated ObservePanel metrics to use 10-minute windowed rate calculations instead of 1-minute windows. This Flink-inspired approach keeps metrics hydrated during bursty workloads like ambient reasoning.

## Problem

With 1-minute windows, metrics showed zeros most of the time during ambient workloads because:
- Inference happens in bursts (reasoning phase)
- Long quiet periods between cycles
- Instantaneous rates dropped to zero quickly

## Solution

Changed all rate-based PromQL queries to use 10-minute windows:

| Metric | Before | After |
|--------|--------|-------|
| Latency p95 | `[5m]` | `[10m]` |
| Infer/hr | `[1m]` | `[10m]` |
| Tokens/hr | `[1m]` | `[10m]` |
| Error Rate | `[5m]` | `[10m]` |
| Heal Rate | `[5m]` | `[10m]` |
| Heals/hr | `[1m]` | `[10m]` |

## Windowed Stats Philosophy (Flink-inspired)

```
// From metrics.py header comment:
// - Use 10-minute windows for rate calculations to survive bursty workloads
// - Sparklines show 5-minute history at 15-second resolution
// - Current value shows meaningful aggregate rather than instantaneous zero
```

## Technical Details

Rate extrapolation for hourly display:
```python
# 10-minute windowed rate extrapolated to hourly
query='sum(rate(gaius_gaius_inference_count_total[10m])) * 3600'
```

This means:
- `rate(...[10m])` computes per-second rate over last 10 minutes
- `* 3600` extrapolates to hourly rate
- Even with bursty activity, the 10-minute window captures the burst

## Files Modified

| File | Change |
|------|--------|
| `src/gaius/observability/metrics.py` | Updated all PromQL queries to use 10-minute windows |

## Verification

GPU FLOPS utilization metric confirmed working via Prometheus:
```bash
curl -s "http://localhost:9090/api/v1/query?query=gaius_gaius_gpu_flops_utilization_percent"
# Returns current value
```

Inference metrics will hydrate after OTel export is active and ambient workloads run.
