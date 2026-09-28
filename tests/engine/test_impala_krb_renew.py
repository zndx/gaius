"""The Impala ticket refresh is one Airflow workload, not a resident loop."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gaius.engine.services import impala_krb_renew as renew
from gaius.engine.services import workload_catalog as wc


def test_impala_krb_renew_is_airflow_only() -> None:
    entry = wc.entry_for("impala_krb_renew")
    assert entry is not None
    assert entry.enabled and entry.source == "airflow"
    assert entry.runner == wc.RUNNER_TASK
    assert not entry.pg_cron_active and entry.pg_cron_job == ""
    assert entry.cron == "20 */8 * * *"
    assert wc.airflow_dag_id(entry) == "gaius_impala_krb_renew"
    assert wc.claims_for("impala_krb_renew") == []


def test_renew_requires_the_signals_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SIGNALS_ROOT", raising=False)
    with pytest.raises(RuntimeError, match="SIGNALS_ROOT"):
        renew.signals_root()
    monkeypatch.setenv("SIGNALS_ROOT", str(tmp_path))
    with pytest.raises(RuntimeError, match="signals_kerberos.sh"):
        renew.signals_root()


def test_renew_is_one_kinit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    script = tmp_path / "scripts"
    script.mkdir()
    (script / "signals_kerberos.sh").write_text("# stub\n", encoding="utf-8")
    kdc = tmp_path / ".devenv" / "kdc"
    kdc.mkdir(parents=True)
    (kdc / "krb5.conf").write_text("[libdefaults]\n", encoding="utf-8")
    seen: dict[str, object] = {}

    def _run(argv, **kwargs):  # type: ignore[no-untyped-def]
        seen["argv"] = argv
        seen["env"] = kwargs["env"]
        seen["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(argv, 0, stdout="kinit ok: impala/host\n", stderr="")

    monkeypatch.setattr(renew.subprocess, "run", _run)
    out = renew.renew_impala_ticket(tmp_path)
    assert out["status"] == "completed"
    assert "signals_impala_kinit" in str(seen["argv"])
    env = seen["env"]
    assert isinstance(env, dict)
    assert env["DEVENV_ROOT"] == str(tmp_path)
    assert env["KDC_DIR"] == str(kdc)
    assert env["KRB5_CONFIG"] == str(kdc / "krb5.conf")
    assert "UV_PROJECT_ENVIRONMENT" not in env
