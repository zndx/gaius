# Gaius operational tasks
# Usage: just <recipe>    (from devenv shell or any shell with just+devenv)
# List:  just --list

set positional-arguments

# ─── Stack Management ────────────────────────────────────────────

# Register system Impala/Kudu on Gaius zndx_gaius via impala_fdw (Signals FDW stays).
warehouse-fdw:
    bash scripts/warehouse/install_impala_fdw.sh

# Start product stack in background (postgres · aeron · engine · …)
# Used by scripts/systemd_start.sh (Signals lattice peer unit).
up:
    devenv up -d

# Stop this project's process-compose only (does not kill sibling GPU leases)
down:
    devenv processes down 2>/dev/null || true

# Full clean restart — starts stack as background daemon
restart-clean:
    #!/usr/bin/env bash
    set -euo pipefail
    # Capture tool paths before stripping devenv environment.
    # devenv-tasks 2.0.0 deadlocks on tasks.db when devenv up -d
    # is called with inherited DEVENV_* vars.
    _devenv_dir="$(dirname "$(command -v devenv)")"
    _nix_dir="$(dirname "$(command -v nix)")"
    _git_dir="$(dirname "$(command -v git)")"
    exec env -i \
      HOME="$HOME" \
      USER="$USER" \
      TERM="${TERM:-dumb}" \
      XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-}" \
      PATH="$_devenv_dir:$_nix_dir:$_git_dir:/usr/bin:/bin:/usr/sbin:/sbin" \
      XAI_API_KEY="${XAI_API_KEY:-}" \
      ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
      CEREBRAS_API_KEY="${CEREBRAS_API_KEY:-}" \
      CLOUDFLARE_API_TOKEN="${CLOUDFLARE_API_TOKEN:-}" \
      CLOUDFLARE_ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-}" \
      BRAVE_API_KEY="${BRAVE_API_KEY:-}" \
      XAI_MANAGEMENT_KEY="${XAI_MANAGEMENT_KEY:-}" \
      CF_R2_ACCESS_KEY_ID="${CF_R2_ACCESS_KEY_ID:-}" \
      CF_R2_SECRET_ACCESS_KEY="${CF_R2_SECRET_ACCESS_KEY:-}" \
      CF_R2_BUCKET="${CF_R2_BUCKET:-}" \
      CF_R2_PUBLIC_URL="${CF_R2_PUBLIC_URL:-}" \
      X_CLIENT_ID="${X_CLIENT_ID:-}" \
      X_CLIENT_SECRET="${X_CLIENT_SECRET:-}" \
      bash "$(pwd)/scripts/restart-clean.sh"

# ─── gRPC / Proto ────────────────────────────────────────────────

# Regenerate gRPC Python stubs from proto definitions
proto-generate:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  PROTO GENERATE - Regenerating gRPC Python stubs             ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""

    PROTO_DIR="src/gaius/engine/proto"
    OUT_DIR="src/gaius/engine/generated"

    echo "Source:  $PROTO_DIR/gaius_service.proto"
    echo "Output:  $OUT_DIR/"
    echo ""

    # Generate Python stubs with type hints
    # --pyi_out: protobuf message type stubs
    # --mypy_grpc_out: gRPC service type stubs (requires mypy-protobuf)
    python -m grpc_tools.protoc \
      -I="$PROTO_DIR" \
      --python_out="$OUT_DIR" \
      --pyi_out="$OUT_DIR" \
      --grpc_python_out="$OUT_DIR" \
      --mypy_grpc_out="$OUT_DIR" \
      "$PROTO_DIR/gaius_service.proto"

    echo "✓ Proto stubs generated (including gRPC type stubs)"

    # Fix absolute import to relative import in grpc files
    # grpc_tools.protoc generates: import gaius_service_pb2 as gaius__service__pb2
    # We need:                     from . import gaius_service_pb2 as gaius__service__pb2
    sed -i 's/^import gaius_service_pb2/from . import gaius_service_pb2/' \
      "$OUT_DIR/gaius_service_pb2_grpc.py"

    # Also fix the .pyi stub file
    sed -i 's/^import gaius_service_pb2/from . import gaius_service_pb2/' \
      "$OUT_DIR/gaius_service_pb2_grpc.pyi"

    echo "✓ Fixed relative imports in gaius_service_pb2_grpc.py and .pyi"

    # Add async stub alias for grpc.aio compatibility
    # The .pyi declares GaiusServiceAsyncStub for type checking, but we need the runtime alias
    # With grpc.aio, the same stub class works with async channels
    echo "" >> "$OUT_DIR/gaius_service_pb2_grpc.py"
    echo "# Async stub alias - same class works with grpc.aio.Channel" >> "$OUT_DIR/gaius_service_pb2_grpc.py"
    echo "# Type hints in .pyi declare this as a subclass for type checking" >> "$OUT_DIR/gaius_service_pb2_grpc.py"
    echo "GaiusServiceAsyncStub = GaiusServiceStub" >> "$OUT_DIR/gaius_service_pb2_grpc.py"

    echo "✓ Added GaiusServiceAsyncStub alias for grpc.aio"
    echo ""

    # zndx.engine.v1 (signals-protocol) — lattice federation face
    ZNDX_PROTO="external/signals-protocol/proto"
    if [[ -f "$ZNDX_PROTO/zndx/engine/v1/engine.proto" ]]; then
      echo "Source:  $ZNDX_PROTO/zndx/engine/v1/engine.proto"
      python -m grpc_tools.protoc \
        -I="$ZNDX_PROTO" \
        --python_out="$OUT_DIR" \
        --grpc_python_out="$OUT_DIR" \
        "$ZNDX_PROTO/zndx/engine/v1/engine.proto"
      sed -i 's/^from zndx\.engine\.v1 import engine_pb2 as /from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as /' \
        "$OUT_DIR/zndx/engine/v1/engine_pb2_grpc.py"
      mkdir -p "$OUT_DIR/zndx/engine/v1"
      echo "✓ Generated zndx.engine.v1 bindings"
      if [[ -f "$ZNDX_PROTO/zndx/scheduler/v1/scheduler.proto" ]]; then
        echo "Source:  $ZNDX_PROTO/zndx/scheduler/v1/scheduler.proto"
        python -m grpc_tools.protoc \
          -I="$ZNDX_PROTO" \
          --python_out="$OUT_DIR" \
          --grpc_python_out="$OUT_DIR" \
          "$ZNDX_PROTO/zndx/scheduler/v1/scheduler.proto"
        # scheduler.proto imports engine.proto (WorkloadRequirements) — rewrite the
        # cross-file import in the message module to the nested package path too.
        sed -i 's/^from zndx\.engine\.v1 import engine_pb2 as /from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as /' \
          "$OUT_DIR/zndx/scheduler/v1/scheduler_pb2.py"
        sed -i 's/^from zndx\.scheduler\.v1 import scheduler_pb2 as /from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as /' \
          "$OUT_DIR/zndx/scheduler/v1/scheduler_pb2_grpc.py"
        mkdir -p "$OUT_DIR/zndx/scheduler/v1"
        printf '%s\n' '"""Generated bindings for zndx.scheduler.v1 (signals-protocol)."""' \
          'from . import scheduler_pb2, scheduler_pb2_grpc' \
          '__all__ = ["scheduler_pb2", "scheduler_pb2_grpc"]' \
          > "$OUT_DIR/zndx/scheduler/v1/__init__.py"
        echo "✓ Generated zndx.scheduler.v1 bindings"
      fi
      # zndx.supervision.v1 — the supervision grammar + the engine-hosted
      # EngineSupervision stream (2026-09-04). Before this arm the committed stubs
      # were produced out of band and no staleness check covered them.
      if [[ -f "$ZNDX_PROTO/zndx/supervision/v1/supervision.proto" ]]; then
        echo "Source:  $ZNDX_PROTO/zndx/supervision/v1/supervision.proto"
        python -m grpc_tools.protoc \
          -I="$ZNDX_PROTO" \
          --python_out="$OUT_DIR" \
          --grpc_python_out="$OUT_DIR" \
          "$ZNDX_PROTO/zndx/supervision/v1/supervision.proto"
        sed -i 's/^from zndx\.supervision\.v1 import supervision_pb2 as /from gaius.engine.generated.zndx.supervision.v1 import supervision_pb2 as /' \
          "$OUT_DIR/zndx/supervision/v1/supervision_pb2_grpc.py"
        mkdir -p "$OUT_DIR/zndx/supervision/v1"
        printf '%s\n' '"""Generated bindings for zndx.supervision.v1 (signals-protocol)."""' \
          'from . import supervision_pb2, supervision_pb2_grpc' \
          '__all__ = ["supervision_pb2", "supervision_pb2_grpc"]' \
          > "$OUT_DIR/zndx/supervision/v1/__init__.py"
        echo "✓ Generated zndx.supervision.v1 bindings"
      fi
    else
      echo "⚠ signals-protocol proto not found at $ZNDX_PROTO — skip zndx bindings"
    fi

    echo ""
    echo "Done! Regenerated files:"
    ls -la "$OUT_DIR"/gaius_service_pb2*.py "$OUT_DIR"/gaius_service_pb2*.pyi 2>/dev/null || ls -la "$OUT_DIR"/gaius_service_pb2*

# ─── GPU ─────────────────────────────────────────────────────────

# Resume GPU workloads after a deferred (unclean-reboot) boot; clears the defer marker
resume-gpu:
    bash scripts/gpu-resume.sh

# Install + enable the reboot/liveness hardening systemd units (idempotent).
# crash-guard (unclean-boot GPU defer) + thinking-ready (baseline GPU workload
# watchdog) + engine-ready (out-of-band :50051 liveness → complete recycle).
# Does NOT arm the kernel-panic sysctl (60-crash-recovery.conf) — that reboots the
# box on a hard hang and is a separate, deliberate step (see echo below).
reboot-hardening-install:
    #!/usr/bin/env bash
    set -euo pipefail
    UNITS="crash-guard.service gaius-thinking-ready.service gaius-engine-ready.service nautilus-tick.service nautilus-tick.timer"
    echo "Installing hardening units: $UNITS"
    for u in $UNITS; do
      sudo install -m 0644 "$(pwd)/scripts/systemd/$u" "/etc/systemd/system/$u"
    done
    sudo systemctl daemon-reload
    # crash-guard is a boot/shutdown oneshot (WantedBy=multi-user.target).
    # engine-ready + thinking-ready are continuous watchdogs WantedBy=gaius.service
    # (run whenever the engine unit runs). --now starts the continuous ones against
    # the currently-running engine immediately.
    sudo systemctl enable crash-guard.service >/dev/null
    sudo systemctl enable --now gaius-engine-ready.service gaius-thinking-ready.service
    # nautilus-tick.timer: hourly hh:03 second hand for the resident Nautilus's
    # Backlog fill (idempotent on the epoch hour; fails loudly when the resident is down).
    sudo systemctl enable --now nautilus-tick.timer
    echo "✓ Installed + enabled. Verify:"
    echo "    systemctl status gaius-engine-ready.service --no-pager"
    echo "    journalctl -u gaius-engine-ready.service -n 20 --no-pager"
    echo "    systemctl list-timers nautilus-tick.timer --no-pager"

# Build the resident Nautilus supervisor (external/nautilus) in release mode.
# The devenv process builds on demand too; this is the explicit form.
nautilus-build:
    #!/usr/bin/env bash
    set -euo pipefail
    cargo build --release --manifest-path "$(pwd)/external/nautilus/Cargo.toml"
    "$(pwd)/external/nautilus/target/release/nautilus" validate "$(pwd)/config/supervision/gaius.textproto" --quiet | tail -1

# Resident Nautilus faces (loopback :50061): status, the Operations Backlog, a forced tick.
nautilus-status:
    @"$(pwd)/external/nautilus/target/release/nautilus" status --target 127.0.0.1:50061

backlog *ARGS:
    @"$(pwd)/external/nautilus/target/release/nautilus" backlog --target 127.0.0.1:50061 {{ARGS}}
    echo "Kernel-panic-on-hang backstop is NOT armed. To arm (reboots on hard hang):"
    echo "    sudo install -m 0644 scripts/systemd/60-crash-recovery.conf /etc/sysctl.d/ && sudo sysctl --system"

# Kill stale vLLM processes, reclaim unheld /dev/shm offload maps, show GPU memory
gpu-cleanup:
    #!/usr/bin/env bash
    set -euo pipefail
    source "$(pwd)/scripts/lib/process-helpers.sh"
    source "$(pwd)/scripts/lib/gpu-helpers.sh"
    banner "GPU CLEANUP - Killing stale vLLM processes"
    gpu_cleanup

# Kill ALL inference processes (nuclear option)
gpu-deep-cleanup:
    #!/usr/bin/env bash
    set -euo pipefail
    source "$(pwd)/scripts/lib/gpu-helpers.sh"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  DEEP CLEANUP - Killing ALL inference processes              ║"
    echo "║  (sparing live cross-project lease holders)                  ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""

    # 1. Kill vLLM processes by name pattern (includes workers and engine).
    # Sibling engines' vLLM matches these patterns too — lease-spared kills only.
    echo "Killing vLLM processes..."
    _kill_unleased $(pgrep -f "vllm serve|vllm\.entrypoints|VLLM::" 2>/dev/null || true)

    # 2. Kill ray processes (vLLM uses ray internally) — same sparing
    echo "Killing ray processes..."
    _kill_unleased $(pgrep -f "ray::|raylet|gcs_server" 2>/dev/null || true)

    # 3. Kill gaius engine/MCP processes (gaius-only patterns)
    echo "Killing gaius processes..."
    pkill -9 -f "gaius.engine.server" 2>/dev/null || true
    pkill -9 -f "gaius.mcp_server" 2>/dev/null || true

    # 4. Kill optillm (gunicorn on port 8000; gaius-only tool)
    echo "Killing optillm/gunicorn..."
    pkill -9 -f "gunicorn.*optillm" 2>/dev/null || true
    pkill -9 -f "optillm" 2>/dev/null || true
    # Anything left on port 8000 — lease-spared (a sibling vLLM may bind it)
    _kill_unleased $(fuser 8000/tcp 2>/dev/null || true)

    # 5. Kill any GPU processes via nvidia-smi (catches orphaned processes)
    echo "Killing GPU processes via nvidia-smi..."
    VLLM_PIDS=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | tr '\n' ' ')
    if [ -n "${VLLM_PIDS// /}" ]; then
      _kill_unleased $VLLM_PIDS
    else
      echo "  No GPU processes found"
    fi

    # 6. Second pass - some processes may have respawned or been missed
    sleep 1
    REMAINING=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -v "^$" | wc -l || true)
    if [ "$REMAINING" -gt 0 ]; then
      echo "Second pass - $REMAINING GPU processes still present..."
      _kill_unleased $(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null || true)
    fi

    sleep 2

    # Verification
    echo ""
    echo "=== Verification ==="
    echo ""
    echo "Remaining vLLM/ray processes:"
    ps aux | grep -E 'vllm|ray::|VLLM::' | grep -v grep || echo "  ✓ None"
    echo ""
    echo "Ports 8000, 808x-809x:"
    ss -tlnp 2>/dev/null | grep -E ':8000|808[0-9]|809[0-9]' || echo "  ✓ All clear"
    echo ""
    echo "GPU processes:"
    nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv 2>/dev/null | tail -n +2 || echo "  (nvidia-smi not available)"
    GPU_PROCS=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -v "^$" | wc -l || true)
    if [ "$GPU_PROCS" -eq 0 ]; then
      echo "  ✓ All GPUs clear"
    else
      echo "  ⚠ $GPU_PROCS processes still on GPU"
    fi
    echo ""
    echo "GPU Memory:"
    nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv 2>/dev/null || echo "  (nvidia-smi not available)"
    echo ""

# ─── Web UI (Keiretsu / Signals-shaped) ──────────────────────────

# Rebuild stale product artifacts (proto stubs if proto changed, then gaius-ui).
# cargo is incremental; proto-generate runs only when .proto is newer than stubs.
# Does not uv sync, docs-build, or thirdparty. systemctl restart gaius still required.
rebuild:
    #!/usr/bin/env bash
    set -euo pipefail
    ROOT="{{justfile_directory()}}"
    src_newer_than() {
      local dest="$1"; shift
      [[ -f "$dest" ]] || return 0
      local dest_m src
      dest_m=$(stat -c %Y "$dest")
      for src in "$@"; do
        [[ -f "$src" ]] || continue
        if (( $(stat -c %Y "$src") > dest_m )); then
          return 0
        fi
      done
      return 1
    }
    if src_newer_than \
         "$ROOT/src/gaius/engine/generated/gaius_service_pb2.py" \
         "$ROOT/src/gaius/engine/proto/gaius_service.proto" \
      || src_newer_than \
         "$ROOT/src/gaius/engine/generated/zndx/engine/v1/engine_pb2.py" \
         "$ROOT/external/signals-protocol/proto/zndx/engine/v1/engine.proto"; then
      echo "rebuild: proto sources newer than stubs"
      just proto-generate
    else
      echo "rebuild: proto stubs up to date"
    fi
    echo "rebuild: cargo (incremental) gaius-ui"
    cargo build --release -p gaius-ui \
      --manifest-path "$ROOT/components/gaius-ui/Cargo.toml"

alias ui-rebuild := rebuild

# Axum board + cognition + Ghostty terminal (0.0.0.0:9890)
ui:
    #!/usr/bin/env bash
    set -euo pipefail
    export GAIUS_UI_BIND="${GAIUS_UI_BIND:-0.0.0.0:9890}"
    export GAIUS_BOARD_JSON="${GAIUS_BOARD_JSON:-$PWD/build/dev/.board.json}"
    exec "{{justfile_directory()}}/scripts/processes/gaius-ui.sh"

# ─── Docs ────────────────────────────────────────────────────────

# Build mdbook documentation
docs-build:
    mdbook build docs/current

# Build and open mdbook documentation
docs-open:
    mdbook build docs/current --open

# ─── Third-party ─────────────────────────────────────────────────

# Download third-party dependencies
thirdparty-download:
    cd thirdparty && ./download-thirdparty.sh

# Build all third-party components
thirdparty-build:
    cd thirdparty && ./build-thirdparty.sh

# Build LuxCore from source (GPU rendering)
thirdparty-luxcore:
    cd thirdparty && ./build-thirdparty.sh --component luxcore

# ─── Testing / Debug ─────────────────────────────────────────────

# First-run check: MCP server imports (not a CI gate)
mcp-test:
    PYTHONPATH="" .devenv/state/venv/bin/python -c "from gaius.mcp_server import create_server; print('MCP server OK')"

# Regenerate recursive_glass.blend template
viz-template:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Generating recursive_glass.blend template..."
    TEMPLATE_DIR="src/gaius/viz/templates"
    mkdir -p "$TEMPLATE_DIR"
    blender --background --python src/gaius/viz/scripts/create_template.py -- \
      --output "$TEMPLATE_DIR/recursive_glass.blend"
    echo "✓ Template saved to $TEMPLATE_DIR/recursive_glass.blend"

# Full teardown — stop everything, free GPUs, tear down K8s
teardown:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  TEARDOWN — Stopping all Gaius services and freeing GPUs    ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""

    # ── Phase 1: Stop devenv processes ──────────────────────────────
    echo "Phase 1: Stopping devenv processes..."
    devenv processes down 2>/dev/null || true
    echo "  ✓ devenv processes stopped"
    echo ""

    # ── Phase 2: Kill GPU processes ─────────────────────────────────
    echo "Phase 2: Cleaning GPU processes..."

    # vLLM processes
    pkill -9 -f "vllm serve" 2>/dev/null || true
    pkill -9 -f "vllm.entrypoints" 2>/dev/null || true
    pkill -9 -f "VLLM::" 2>/dev/null || true

    # Ray (vLLM internal)
    pkill -9 -f "ray::" 2>/dev/null || true
    pkill -9 -f "raylet" 2>/dev/null || true
    pkill -9 -f "gcs_server" 2>/dev/null || true

    # Gaius engine/MCP
    pkill -9 -f "gaius.engine.server" 2>/dev/null || true
    pkill -9 -f "gaius.mcp_server" 2>/dev/null || true

    # optillm
    pkill -9 -f "gunicorn.*optillm" 2>/dev/null || true
    pkill -9 -f "optillm" 2>/dev/null || true
    fuser -k 8000/tcp 2>/dev/null || true

    # Sweep any remaining GPU processes
    if command -v nvidia-smi &>/dev/null; then
      PIDS=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | tr -s ' \n' ' ')
      if [ -n "${PIDS// /}" ]; then
        for pid in $PIDS; do
          [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
        done
        sleep 1
      fi
    fi

    echo "  ✓ GPU processes cleaned"
    echo ""

    # ── Phase 3: Tear down K8s resources (if RKE2 present) ─────────
    KUBECONFIG_PATH="$HOME/.config/kube/rke2.yaml"
    if [ -f "$KUBECONFIG_PATH" ]; then
      export KUBECONFIG="$KUBECONFIG_PATH"

      if kubectl cluster-info &>/dev/null; then
        echo "Phase 3: Tearing down K8s resources..."

        # Kill port-forwards first
        pkill -f "kubectl.*port-forward" 2>/dev/null || true
        echo "  ✓ Port-forwards killed"

        # Tilt teardown (removes Helm releases + K8s objects it manages)
        if command -v tilt &>/dev/null && [ -f "infra/tilt/Tiltfile" ]; then
          echo "  Running tilt down..."
          (cd infra/tilt && tilt down) || true
          echo "  ✓ Tilt resources removed"
        fi

        # Delete devenv NodePort services (may already be gone from tilt down)
        kubectl delete -f infra/k8s/devenv-services.yaml --ignore-not-found 2>/dev/null || true
        echo "  ✓ DevEnv K8s services removed"

        # Clean up any lingering Metaflow pods
        kubectl delete pods -l app.kubernetes.io/name=metaflow-service --ignore-not-found --grace-period=5 2>/dev/null || true
        kubectl delete pods -l app.kubernetes.io/name=metaflow-ui --ignore-not-found --grace-period=5 2>/dev/null || true
        kubectl delete pods -l app.kubernetes.io/name=metaflow-ui-static --ignore-not-found --grace-period=5 2>/dev/null || true
        echo "  ✓ Metaflow pods cleaned"
        echo ""
      else
        echo "Phase 3: K8s cluster not reachable, skipping"
        echo ""
      fi
    else
      echo "Phase 3: No RKE2 kubeconfig found, skipping K8s teardown"
      echo ""
    fi

    # ── Verification ────────────────────────────────────────────────
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  Verification                                               ║"
    echo "╠══════════════════════════════════════════════════════════════╣"

    # GPU status
    if command -v nvidia-smi &>/dev/null; then
      GPU_PROCS=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -cv "^$" || true)
      if [ "$GPU_PROCS" -eq 0 ]; then
        echo "║  GPUs:      ✓ All clear                                    ║"
      else
        echo "║  GPUs:      ⚠ $GPU_PROCS process(es) remaining                          ║"
      fi
    else
      echo "║  GPUs:      - nvidia-smi not available                     ║"
    fi

    # Ports
    BUSY_PORTS=$(ss -tlnp 2>/dev/null | grep -cE ':8000|:808[0-9]|:809[0-9]|:50051|:9080|:3000' || true)
    if [ "$BUSY_PORTS" -eq 0 ]; then
      echo "║  Ports:     ✓ All clear                                    ║"
    else
      echo "║  Ports:     ⚠ $BUSY_PORTS port(s) still bound                            ║"
    fi

    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "System is clear. GPUs and K8s resources are free."

# ─── Kubernetes ──────────────────────────────────────────────────

# Sync RKE2 kubeconfig to user-readable location
kubeconfig-sync:
    sudo bash "$(pwd)/scripts/lib/kubeconfig-sync.sh"

# Install systemd drop-in for automatic kubeconfig sync on RKE2 restart
kubeconfig-install-systemd:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Installing kubeconfig-sync systemd drop-in..."
    sudo mkdir -p /etc/systemd/system/rke2-server.service.d
    sudo cp "$(pwd)/infra/systemd/rke2-kubeconfig-sync.conf" \
         /etc/systemd/system/rke2-server.service.d/kubeconfig-sync.conf
    sudo systemctl daemon-reload
    echo "✓ Drop-in installed. Verify:"
    echo "  systemctl cat rke2-server | grep ExecStartPost"

# Clean orphaned CNI IP allocations
k8s-cleanup:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  K8S CLEANUP - Cleaning orphaned CNI IP allocations         ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""

    export KUBECONFIG=/home/rch/.config/kube/rke2.yaml
    CNI_DIR="/var/lib/cni/networks/k8s-pod-network"

    # Get active pod IPs
    echo "Fetching active pod IPs..."
    ACTIVE_IPS=$(/var/lib/rancher/rke2/bin/kubectl get pods -A \
      -o jsonpath='{range .items[?(@.status.podIP)]}{.status.podIP}{"\n"}{end}' 2>/dev/null \
      | grep "10.42" | sort -u)

    echo "Active IPs:"
    echo "$ACTIVE_IPS" | sed 's/^/  /'
    echo ""

    # Count orphaned IPs
    TOTAL=$(ls -1 $CNI_DIR/10.42.0.* 2>/dev/null | wc -l)
    ACTIVE=$(echo "$ACTIVE_IPS" | wc -l)
    ORPHANED=$((TOTAL - ACTIVE))

    echo "CNI IPAM status:"
    echo "  Total allocated: $TOTAL"
    echo "  Active pods:     $ACTIVE"
    echo "  Orphaned:        $ORPHANED"
    echo ""

    if [ $ORPHANED -gt 0 ]; then
      echo "Cleaning up orphaned IP allocations..."

      # Backup active IPs
      mkdir -p /tmp/cni-backup
      rm -f /tmp/cni-backup/*
      echo "$ACTIVE_IPS" | while read ip; do
        if [ -f "$CNI_DIR/$ip" ]; then
          sudo cp "$CNI_DIR/$ip" /tmp/cni-backup/
        fi
      done
      sudo cp "$CNI_DIR/last_reserved_ip.0" /tmp/cni-backup/ 2>/dev/null || true
      sudo cp "$CNI_DIR/lock" /tmp/cni-backup/ 2>/dev/null || true

      # Delete all IP files
      sudo rm -f $CNI_DIR/10.42.0.*

      # Restore active IPs
      sudo cp /tmp/cni-backup/* $CNI_DIR/

      echo "✓ Cleaned up $ORPHANED orphaned IP allocations"

      # Restart Canal to refresh IPAM
      echo ""
      echo "Restarting Canal CNI to refresh IPAM..."
      /var/lib/rancher/rke2/bin/kubectl rollout restart ds/rke2-canal -n kube-system

      echo "✓ Canal restarted"
    else
      echo "✓ No orphaned IPs to clean up"
    fi

# Throughput: local vLLM thinking lane vs the Cerebras API on the same model
# (Qwen3.8-27B), from HX llm.generations. Read-only; never `uv run` beside the engine.
throughput days="7":
    .devenv/state/venv/bin/python scripts/throughput_report.py --days {{days}}

# Engine restart under policy (memory: gaius-controlled-restart-window). controlled = wait
# for no publish slot, pause enqueuers, drain, restart, verify; free = a primary objective is
# unmet so nothing is protected: restart now, verify. Add --objective NAME to verify it live.
restart-window mode="controlled" *args="":
    bash scripts/restart_window.sh --mode {{mode}} {{args}}
