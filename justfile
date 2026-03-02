# Gaius operational tasks
# Usage: just <recipe>    (from devenv shell or any shell with just+devenv)
# List:  just --list

set positional-arguments

# ─── Stack Management ────────────────────────────────────────────

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
    echo "Done! Regenerated files:"
    ls -la "$OUT_DIR"/gaius_service_pb2*.py "$OUT_DIR"/gaius_service_pb2*.pyi 2>/dev/null || ls -la "$OUT_DIR"/gaius_service_pb2*

# ─── GPU ─────────────────────────────────────────────────────────

# Kill stale vLLM processes and show GPU memory
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
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  DEEP CLEANUP - Killing ALL inference processes              ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""

    # 1. Kill vLLM processes by name pattern (includes workers and engine)
    echo "Killing vLLM processes..."
    pkill -9 -f "vllm serve" 2>/dev/null || true
    pkill -9 -f "vllm.entrypoints" 2>/dev/null || true
    # Kill vLLM worker processes (show as "VLLM::Worker_TP0" etc in nvidia-smi)
    pkill -9 -f "VLLM::" 2>/dev/null || true
    # Kill by process name pattern for workers that renamed themselves
    pgrep -f "VLLM::Worker" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
    pgrep -f "VLLM::EngineCore" 2>/dev/null | xargs -r kill -9 2>/dev/null || true

    # 2. Kill ray processes (vLLM uses ray internally)
    echo "Killing ray processes..."
    pkill -9 -f "ray::" 2>/dev/null || true
    pkill -9 -f "raylet" 2>/dev/null || true
    pkill -9 -f "gcs_server" 2>/dev/null || true

    # 3. Kill gaius engine/MCP processes
    echo "Killing gaius processes..."
    pkill -9 -f "gaius.engine.server" 2>/dev/null || true
    pkill -9 -f "gaius.mcp_server" 2>/dev/null || true

    # 4. Kill optillm (gunicorn on port 8000)
    echo "Killing optillm/gunicorn..."
    pkill -9 -f "gunicorn.*optillm" 2>/dev/null || true
    pkill -9 -f "optillm" 2>/dev/null || true
    # Kill anything on port 8000 (default vLLM/optillm port)
    fuser -k 8000/tcp 2>/dev/null || true

    # 5. Kill any GPU processes via nvidia-smi (catches orphaned processes)
    echo "Killing GPU processes via nvidia-smi..."
    VLLM_PIDS=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | tr '\n' ' ')
    if [ -n "$VLLM_PIDS" ]; then
      for pid in $VLLM_PIDS; do
        if [ -n "$pid" ] && [ "$pid" != " " ]; then
          PROC_NAME=$(ps -p "$pid" -o comm= 2>/dev/null || echo "unknown")
          echo "  Killing GPU process PID $pid ($PROC_NAME)..."
          kill -9 "$pid" 2>/dev/null || true
        fi
      done
    else
      echo "  No GPU processes found"
    fi

    # 6. Second pass - some processes may have respawned or been missed
    sleep 1
    REMAINING=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -v "^$" | wc -l)
    if [ "$REMAINING" -gt 0 ]; then
      echo "Second pass - killing $REMAINING remaining GPU processes..."
      nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | while read pid; do
        [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
      done
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
    GPU_PROCS=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -v "^$" | wc -l)
    if [ "$GPU_PROCS" -eq 0 ]; then
      echo "  ✓ All GPUs clear"
    else
      echo "  ⚠ $GPU_PROCS processes still on GPU"
    fi
    echo ""
    echo "GPU Memory:"
    nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv 2>/dev/null || echo "  (nvidia-smi not available)"
    echo ""

# ─── Docs ────────────────────────────────────────────────────────

# Build mdbook documentation
docs-build:
    mdbook build docs

# Build and open mdbook documentation
docs-open:
    mdbook build docs --open

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

# Smoke-test MCP server startup
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

# ─── Kubernetes ──────────────────────────────────────────────────

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
