"""Gaius entry for gpu_metrics Iceberg verify + Kudu DROP RANGE.

Work lives in Signals (`signals.ops.gpu_metrics_settle`). This module
is the engine/Metaflow/pg_cron spawn target. SIGNALS_ROOT must point at
the Signals checkout.

Guru: #SL.00000026.SETTLE
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _signals_src() -> Path:
    root = (os.environ.get("SIGNALS_ROOT") or "").strip()
    if not root:
        raise RuntimeError(
            "#SL.00000026.SETTLE SIGNALS_ROOT is required "
            "(Signals checkout with src/signals/ops/gpu_metrics_settle.py)"
        )
    src = Path(root) / "src"
    if not (src / "signals" / "ops" / "gpu_metrics_settle.py").is_file():
        raise RuntimeError(f"#SL.00000026.SETTLE missing {src}/signals/ops/gpu_metrics_settle.py")
    return src


def run(*, apply: bool = True, analog: bool = True) -> dict:
    # Prefer Gaius zndx_gaius FDW (system Impala/Kudu). Signals walk still
    # defaults SIGNALS_PGPORT=5455 unless we bind the operator database.
    os.environ.setdefault("SIGNALS_PGHOST", "127.0.0.1")
    os.environ.setdefault("SIGNALS_PGPORT", os.environ.get("PGPORT", "5444"))
    os.environ.setdefault("SIGNALS_PGUSER", os.environ.get("PGUSER", "gaius"))
    os.environ.setdefault("SIGNALS_PGDATABASE", "zndx_gaius")
    os.environ.setdefault("PGPASSWORD", os.environ.get("PGPASSWORD", "gaius"))
    src = _signals_src()
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from signals.ops.gpu_metrics_settle import walk

    return walk(apply=apply, analog=analog)


def main() -> int:
    doc = run(apply=True, analog=True)
    print(json.dumps(doc, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
