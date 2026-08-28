"""Gaius spawn target for the product-generic tier settle (Kudu -> Iceberg/HDF5).

This is the Transparent Hierarchical Storage control plane's worker end. gaius
pg_cron (:5444) enqueues ``scheduled_tasks(task_type='tier_settle',
payload={'product': ...})``; the engine's ScheduledTaskProcessor claims it and
spawns this module. The settle *work* is per-product (each product has its own
HDF5 layout + script); this module only dispatches to it and supplies the
environment the settle needs but the engine process does not carry.

Products (extend ``_PRODUCTS`` as ``latent`` / ``clt_activation`` gain tier1
tables + layouts):

  signal -> $SIGNALS_ROOT/scripts/signal_settle.py  (--backfill N, then --drop-days)

Design notes:
  * The child runs under ``sys.executable`` = the gaius venv python, which has
    h5py + boto3; signal_settle.py itself bridges to the signals venv (impyla)
    for the Impala verify.
  * DSN is NOT rebound to :5444 (unlike gpu_metrics_settle.py). signal_settle.py
    natively targets the warehouse :5455 for its FT reads and the
    signal_settle_state ledger -- the same plane Kumo reads (warehouse_dsn()),
    so "verified in tier1" is asserted against the exact view Kumo serves.

Guru: #SL.00000026.SETTLE
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

GURU = "#SL.00000026.SETTLE"

# How many earlier closed hours each tick also settles if still unverified.
# Bounds per-tick work; a longer outage's backlog is caught up by a wider manual
# `just signal-settle --backfill N` (staleness pressure is Kudu range count, not
# correctness -- drop_days never drops an unverified day).
_SIGNAL_BACKFILL = int(os.environ.get("GAIUS_SIGNAL_SETTLE_BACKFILL", "2"))


def _signals_root() -> Path:
    root = (os.environ.get("SIGNALS_ROOT") or "").strip()
    if not root:
        raise RuntimeError(
            f"{GURU} SIGNALS_ROOT is required (Signals checkout with "
            "scripts/signal_settle.py)"
        )
    p = Path(root)
    if not (p / "scripts" / "signal_settle.py").is_file():
        raise RuntimeError(f"{GURU} missing {p}/scripts/signal_settle.py")
    return p


def _settle_env(root: Path) -> dict[str, str]:
    """Environment a settle child needs that the engine does not carry.

    - **RustFS S3**: HDF5 objects land in RustFS, whose creds are rustfsadmin.
      The engine env injects minioadmin (legacy MinIO, being removed from
      nixpkgs as insecure) which RustFS rejects -- override explicitly.
    - **Kerberos**: the settle authenticates to Impala/Kudu via GSSAPI. Point
      KRB5_CONFIG/KRB5CCNAME at the signals KDC dir; the ticket itself is
      refreshed in _ensure_ticket().
    - **JDK21**: the Iceberg-HDF5 register (IcebergHdf5Register, class-file 65)
      needs Java 21; a gaius shell can leak JDK11.
    """
    env = dict(os.environ)
    kdc = root / ".devenv" / "kdc"
    prof = root / ".devenv" / "profile"
    # signals_kerberos.sh derives KDC_DIR from DEVENV_ROOT/$PWD; a gaius shell
    # leaks DEVENV_ROOT and points it at the wrong tree (keytabs missing). Pin it.
    env["KDC_DIR"] = str(kdc)
    if (kdc / "krb5.conf").is_file():
        env["KRB5_CONFIG"] = str(kdc / "krb5.conf")
    env["KRB5CCNAME"] = env.get("KRB5CCNAME") or str(kdc / "krb5cc")
    env["AWS_ACCESS_KEY_ID"] = os.environ.get("SIGNALS_RUSTFS_KEY", "rustfsadmin")
    env["AWS_SECRET_ACCESS_KEY"] = os.environ.get("SIGNALS_RUSTFS_SECRET", "rustfsadmin")
    env.setdefault("AWS_ENDPOINT_URL_S3", "http://127.0.0.1:9010")
    jhome = prof / "lib" / "openjdk"
    if jhome.is_dir():
        env["JAVA_HOME"] = str(jhome)
        env["PATH"] = f"{prof / 'bin'}:{env.get('PATH', '')}"
    return env


def _ensure_ticket(root: Path, env: dict[str, str]) -> None:
    """Refresh the Kerberos ticket from the keytab so the loop is autonomous.

    signals_kerberos.sh::signals_krb_kinit kinits signals@REALM into the KDC
    ticket cache the settle reads (KRB5CCNAME). Best-effort: if it is missing or
    fails, the settle still runs and fails-closed with a GSSAPI guru rather than
    silently -- surfaced, not hidden.
    """
    ksh = root / "scripts" / "signals_kerberos.sh"
    if not ksh.is_file():
        return
    try:
        subprocess.run(
            ["bash", "-c", f'. "{ksh}" && signals_krb_kinit'],
            cwd=str(root), env=env, check=True,
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        out = getattr(e, "stderr", "") or ""
        print(f"{GURU} kinit refresh failed (settle will fail-closed): {out.strip()[:300]}",
              file=sys.stderr)


def _run(root: Path, args: list[str], env: dict[str, str]) -> None:
    subprocess.run(
        [sys.executable, "scripts/signal_settle.py", *args],
        cwd=str(root), env=env, check=True,
    )


def settle_signal() -> dict:
    root = _signals_root()
    env = _settle_env(root)
    _ensure_ticket(root, env)
    _run(root, ["--backfill", str(_SIGNAL_BACKFILL)], env)
    _run(root, ["--drop-days"], env)
    return {"product": "signal", "backfill": _SIGNAL_BACKFILL, "status": "completed"}


# product -> settle callable. latent / clt_activation plug in here once their
# tier1 tables, HDF5 layouts, and settle scripts exist.
_PRODUCTS = {"signal": settle_signal}


def run(product: str) -> dict:
    fn = _PRODUCTS.get(product)
    if fn is None:
        raise RuntimeError(
            f"{GURU} unknown tier_settle product {product!r}; known: {sorted(_PRODUCTS)}"
        )
    return fn()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    product = args[0] if args else "signal"
    print(json.dumps(run(product), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
