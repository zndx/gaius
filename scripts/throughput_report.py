#!/usr/bin/env python
"""Throughput report: local vLLM thinking lane vs the paid Cerebras API.

Reads HX ``llm.generations`` (Iceberg on RustFS via the HX catalog), where
every card summary lands with ``model_name``, ``input_tokens``,
``output_tokens`` and ``latency_ms``. The ``card_open_weights`` rows are the
LOCAL thinking lane (Qwen/Qwen3.8-27B on vLLM); ``card_cerebras`` rows were
the Cerebras API on the same model (``qwen-3.8-27b``, 2026-09-05/06 — six
cards: 759 tok/s vs 10.5 local), the same prompt shape, so the comparison is
like for like. Since 2026-09-06 the pipeline no longer produces cerebras
summaries: the API is reserved for interactive agent-rtc workloads
(``cerebras-thinking`` in the YuniKorn token-metered queue), whose generations
will land here under their own summary_type as that lane comes up.

    .devenv/state/venv/bin/python scripts/throughput_report.py [--days 7]

Read-only: never ``uv run`` beside the live engine (memory:
uv-run-churns-live-engine-venv). ``latency_ms`` is wall time of the whole
generation as the enrichment saw it (queueing on the local lane included) —
that IS the number the product feels.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from datetime import datetime, timedelta, timezone


def _q(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--days", type=float, default=7.0, help="trailing window in days (default 7)")
    ap.add_argument("--all-types", action="store_true", help="include non-card generation types")
    args = ap.parse_args()

    import zlib  # noqa: F401 — Nix venv probe ordering (memory: nix-python-bare-probe-libz)

    from gaius.hx.catalog import get_catalog
    from gaius.hx.tables import get_llm_generation_table

    table = get_llm_generation_table(get_catalog())
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    scan = table.scan(
        selected_fields=("summary_type", "model_name", "input_tokens", "output_tokens", "latency_ms", "generated_at"),
    )
    rows = scan.to_arrow().to_pylist()

    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        ts = r.get("generated_at")
        if ts is None or ts < since:
            continue
        st = str(r.get("summary_type") or "")
        if not args.all_types and not st.startswith("card_"):
            continue
        out = int(r.get("output_tokens") or 0)
        ms = int(r.get("latency_ms") or 0)
        if out <= 0 or ms <= 0:
            continue
        groups.setdefault((st, str(r.get("model_name") or "?")), []).append(
            {"out": out, "inp": int(r.get("input_tokens") or 0), "ms": ms, "tps": out / (ms / 1000.0)}
        )

    if not groups:
        print(f"no generations with tokens+latency in the last {args.days:g} d", file=sys.stderr)
        return 1

    print(f"HX llm.generations — trailing {args.days:g} d (since {since:%Y-%m-%d %H:%M}Z)")
    print(f"{'summary_type':<18} {'model_name':<34} {'n':>4} {'tok/s p50':>10} {'tok/s p90':>10} {'lat p50 s':>10} {'lat p90 s':>10} {'out tok':>9}")
    for (st, model), g in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        tps = sorted(x["tps"] for x in g)
        lat = sorted(x["ms"] / 1000.0 for x in g)
        print(
            f"{st:<18} {model[:34]:<34} {len(g):>4} {statistics.median(tps):>10.1f} {_q(tps, 0.9):>10.1f} "
            f"{statistics.median(lat):>10.1f} {_q(lat, 0.9):>10.1f} {sum(x['out'] for x in g):>9}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
