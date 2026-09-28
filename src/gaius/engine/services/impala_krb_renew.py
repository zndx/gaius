"""One refresh of the Impala Kudu client ticket cache.

catalogd and impalad re-read ``/tmp/krb5cc_impala`` and do not log in from the
keytab. Airflow is the clock (``gaius_impala_krb_renew``); this function is
one ``kinit -kt``. A loop here would be a second, unsupervised scheduler.

Guru: #SL.00000033.IMPALAKRB
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

GURU = "#SL.00000033.IMPALAKRB"


def signals_root() -> Path:
    root = (os.environ.get("SIGNALS_ROOT") or "").strip()
    if not root:
        raise RuntimeError(f"{GURU} SIGNALS_ROOT is required")
    p = Path(root)
    script = p / "scripts" / "signals_kerberos.sh"
    if not script.is_file():
        raise RuntimeError(f"{GURU} missing {script}")
    return p


def renew_impala_ticket(root: Path | None = None) -> dict[str, str]:
    """Replace ``/tmp/krb5cc_impala`` from the Impala keytab. One shot."""
    root = root or signals_root()
    script = root / "scripts" / "signals_kerberos.sh"
    env = dict(os.environ)
    env.pop("UV_PROJECT_ENVIRONMENT", None)
    env.pop("VIRTUAL_ENV", None)
    # signals_kerberos.sh derives KDC_DIR from DEVENV_ROOT. A Gaius shell
    # leaks its own root and then cannot see the Impala keytab.
    env["DEVENV_ROOT"] = str(root)
    kdc = root / ".devenv" / "kdc"
    env["KDC_DIR"] = str(kdc)
    if (kdc / "krb5.conf").is_file():
        env["KRB5_CONFIG"] = str(kdc / "krb5.conf")
    prof_bin = root / ".devenv" / "profile" / "bin"
    env["PATH"] = f"{prof_bin}:{env.get('PATH', '')}"
    try:
        proc = subprocess.run(
            ["bash", "-c", f'. "{script}" && signals_impala_kinit "{root}"'],
            cwd=str(root),
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "").strip()
        raise RuntimeError(f"{GURU} kinit failed: {detail[:400]}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"{GURU} kinit timed out") from e
    out = (proc.stdout or "").strip()
    return {"status": "completed", "output": out[:500]}
