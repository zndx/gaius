"""Lattice Complete helper + Signals Metaflow fail-closed."""

from __future__ import annotations

import pytest

from gaius.engine.grpc.servicers.zndx_engine_servicer import (
    CAPABILITY_COGNITION,
    resolve_complete_alias,
)
from gaius.flows.lattice import (
    DEFAULT_CAPABILITY,
    engine_target,
    require_signals_metaflow,
)
from gaius.flows.platform_metaflow import PlatformMetaflowError


def test_engine_target_default() -> None:
    assert engine_target({}) == "127.0.0.1:50051"


def test_engine_target_rejects_localhost_in_cluster() -> None:
    with pytest.raises(RuntimeError, match="GAIUS_ENGINE_GRPC"):
        engine_target(
            {
                "KUBERNETES_SERVICE_HOST": "10.0.0.1",
                "GAIUS_ENGINE_GRPC": "127.0.0.1:50051",
            }
        )


def test_engine_target_allows_cluster_svc() -> None:
    addr = engine_target(
        {
            "KUBERNETES_SERVICE_HOST": "10.0.0.1",
            "GAIUS_ENGINE_GRPC": "gaius-engine.metaflow.svc.cluster.local:50051",
        }
    )
    assert addr.startswith("gaius-engine.metaflow.svc")


def test_require_signals_metaflow_rejects_local() -> None:
    with pytest.raises(PlatformMetaflowError, match="METAFLOW_DEFAULT_DATASTORE"):
        require_signals_metaflow({"METAFLOW_DEFAULT_DATASTORE": "local"})


def test_require_signals_metaflow_accepts_rustfs() -> None:
    require_signals_metaflow(
        {
            "METAFLOW_DEFAULT_DATASTORE": "s3",
            "METAFLOW_DATASTORE_SYSROOT_S3": "s3://metaflow/metaflow",
            "METAFLOW_S3_ENDPOINT_URL": "http://127.0.0.1:9010",
        }
    )


def test_require_signals_metaflow_rejects_tilt_k8s_profile() -> None:
    with pytest.raises(PlatformMetaflowError, match="Tilt"):
        require_signals_metaflow(
            {
                "METAFLOW_DEFAULT_DATASTORE": "s3",
                "METAFLOW_S3_ENDPOINT_URL": "http://devenv-minio:9010",
            }
        )


def test_empty_lattice_capability_is_thinking() -> None:
    assert DEFAULT_CAPABILITY == "thinking"
    assert CAPABILITY_COGNITION == "cognition"
    assert resolve_complete_alias("") == "thinking"
    assert resolve_complete_alias("cognition") == "thinking"
    assert resolve_complete_alias("thinking") == "thinking"


def test_in_cluster_metaflow_profile_is_platform() -> None:
    import os

    from gaius.flows.config import get_metaflow_profile

    old = os.environ.get("KUBERNETES_SERVICE_HOST")
    os.environ["KUBERNETES_SERVICE_HOST"] = "10.43.0.1"
    os.environ.pop("GAIUS_METAFLOW_MODE", None)
    try:
        assert get_metaflow_profile() == "platform"
    finally:
        if old is None:
            os.environ.pop("KUBERNETES_SERVICE_HOST", None)
        else:
            os.environ["KUBERNETES_SERVICE_HOST"] = old
