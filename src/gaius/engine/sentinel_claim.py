"""Best-effort YK Application (sentinel pod) for a spawned Gaius flow.

Does not block the flow if kubectl is missing. preStop last-gasp hits
Signals C2 so Yield reaches this engine over gRPC.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

log = logging.getLogger("gaius.engine.sentinel_claim")

_NS = os.environ.get("SIGNALS_SENTINEL_NAMESPACE", "federation-signals")
_C2 = os.environ.get("SIGNALS_C2_URL", "http://127.0.0.1:50561")
_QUEUE = os.environ.get("GAIUS_FLOW_SENTINEL_QUEUE", "root.gaius")


def sentinels_enabled() -> bool:
    raw = os.environ.get("GAIUS_FLOW_SENTINEL", "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    return shutil.which("kubectl") is not None


def apply_flow_sentinel(workload_id: str, kind: str) -> bool:
    if not sentinels_enabled():
        return False
    yaml_body = _pod_yaml(workload_id, kind)
    r = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=yaml_body,
        text=True,
        capture_output=True,
        timeout=30,
    )
    if r.returncode != 0:
        log.warning("sentinel apply %s: %s", workload_id, (r.stderr or r.stdout)[:400])
        return False
    log.info("sentinel Application %s on %s", workload_id, _QUEUE)
    return True


def delete_flow_sentinel(workload_id: str) -> None:
    if not sentinels_enabled():
        return
    subprocess.run(
        [
            "kubectl",
            "-n",
            _NS,
            "delete",
            "pod",
            workload_id,
            "--ignore-not-found=true",
            "--wait=false",
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )


def _pod_yaml(workload_id: str, kind: str) -> str:
    # hostNetwork: last-gasp to lab C2 on the node. Queue label is YK placement.
    return f"""apiVersion: v1
kind: Pod
metadata:
  name: {workload_id}
  namespace: {_NS}
  labels:
    app.kubernetes.io/component: minifi-sentinel
    federation.project: gaius
    federation.workload_id: {workload_id}
    federation.kind: {kind}
    applicationId: {workload_id}
    queue: {_QUEUE}
spec:
  restartPolicy: Never
  hostNetwork: true
  containers:
    - name: sentinel
      image: public.ecr.aws/docker/library/busybox:1.36
      command: ["sh", "-c", "sleep 86400"]
      lifecycle:
        preStop:
          exec:
            command:
              - sh
              - -c
              - |
                wget -q -O- --post-data='{{"workload_id":"{workload_id}","project":"gaius","phase":"preempted","sentinel_id":"{workload_id}"}}' \\
                  --header='Content-Type: application/json' \\
                  "{_C2}/c2-protocol/last-gasp" || true
      resources:
        requests:
          cpu: 10m
          memory: 16Mi
"""
