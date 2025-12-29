{ pkgs, lib, config, inputs, ... }:

{

  dotenv.enable = true;
  cachix.enable = false;

  env.PATH_CONF = "conf";

  # Suppress gRPC fork warnings - these occur when subprocess.Popen() is used
  # while gRPC threads are active (e.g., starting vLLM during auto-init).
  # The warnings are harmless but spam the TUI display.
  env.GRPC_ENABLE_FORK_SUPPORT = 0;
  env.GRPC_VERBOSITY = "ERROR";

  # JVM memory for DeepOnto (BERTSubs subsumption inference)
  # This must be set BEFORE importing deeponto.onto to avoid interactive prompt
  env.JVM_MEMORY = "4g";

  # Library paths for Python C extensions and CUDA
  # Use project-local symlinks to NVIDIA drivers (avoids glibc conflicts with Nix)
  env.LD_LIBRARY_PATH = lib.concatStringsSep ":" [
    (lib.makeLibraryPath [
      pkgs.zlib
      pkgs.stdenv.cc.cc.lib  # libstdc++
    ])
    # NVIDIA drivers (symlinked to .devenv/nvidia-libs to avoid system glibc conflicts)
    "${config.devenv.root}/.devenv/nvidia-libs"
    # CUDA toolkit paths (if available)
    "/usr/local/cuda/lib64"
    "/usr/local/cuda/extras/CUPTI/lib64"
  ];

  # Override MinIO data directory to use RAID storage
  env.MINIO_DATA_DIR = lib.mkForce "/raid/minio/gaius";

  # Qdrant configuration via environment variables
  env.QDRANT__STORAGE__STORAGE_PATH = "/raid/qdrant/gaius";
  env.QDRANT__SERVICE__HTTP_PORT = "6339";  # Non-default to avoid conflicts
  env.QDRANT__SERVICE__GRPC_PORT = "6340";

  # MinIO/S3 credentials for Metaflow (must override ~/.aws/credentials)
  env.AWS_ACCESS_KEY_ID = "minioadmin";
  env.AWS_SECRET_ACCESS_KEY = "minioadmin";

  # Project-specific Metaflow config (instead of ~/.metaflowconfig)
  env.METAFLOW_HOME = "${config.devenv.root}/.metaflow";

  # Kubernetes configuration for RKE2
  # For non-root access, copy the kubeconfig:
  #   sudo cp /etc/rancher/rke2/rke2.yaml ~/.config/kube/rke2.yaml
  #   sudo chown $USER:$USER ~/.config/kube/rke2.yaml
  #   chmod 600 ~/.config/kube/rke2.yaml
  enterShell = ''
    export KUBECONFIG="$HOME/.config/kube/rke2.yaml"
  '';

  # https://devenv.sh/packages/
  packages = with pkgs; [
    aeron
    awscli2
    cmake
    conftest
    d2
    dbmate
    git
    gh
    graphviz
    grpcurl
    imagemagick
    jq
    metabase
    mdbook
    mdbook-d2
    mdbook-katex
    mdbook-mermaid
    nifi
    open-policy-agent
    opentofu
    protobuf
    presenterm
    qdrant
    tilt          # K8s development environment for Metaflow
    wrangler
    zlib  # Required for numpy C extensions

    # Browser automation for dataset generation (selenium + chromedriver)
    chromium
    chromedriver

    # Gaius Engine dependencies
    aeron-cpp      # Aeron C++ library and aeronmd media driver
    flatbuffers    # FlatBuffers compiler for schema generation
  ];

  services.minio = {
    enable = true;
    buckets = ["zndx-gaius" "metaflow-artifacts"];
    listenAddress = "0.0.0.0:9010";   # All interfaces for K8s access
    consoleAddress = "0.0.0.0:9011";
  };

  services.postgres = {
    enable = true;
    package = pkgs.postgresql_16;
    extensions = ext: [
      ext.pg_cron  # Scheduled tasks
      ext.age      # Apache AGE - Graph database extension for lineage
    ];
    initialDatabases = [
      { name = "zndx_gaius"; }
      { name = "metaflow"; }
    ];
    port = 5438;
    listen_addresses = "*";  # Enable TCP from K8s pods and local clients
    settings = {
      shared_preload_libraries = "pg_cron,age";
      "cron.database_name" = "zndx_gaius";
    };
    initialScript = ''
      CREATE EXTENSION IF NOT EXISTS pg_cron;
      -- AGE extension is created per-database in migrations
    '';
  };

  # Qdrant as a custom process (not a native devenv service)
  processes.qdrant = {
    exec = ''
      mkdir -p /raid/qdrant/gaius
      ${pkgs.qdrant}/bin/qdrant
    '';
  };

  # ============================================================================
  # OpenTelemetry Collector - Receives telemetry from all Gaius components
  # ============================================================================
  services.opentelemetry-collector = {
    enable = true;
    package = pkgs.opentelemetry-collector-contrib;  # Use contrib for prometheus exporter
    settings = {
      receivers = {
        otlp = {
          protocols = {
            grpc.endpoint = "0.0.0.0:4317";
            http.endpoint = "0.0.0.0:4318";
          };
        };
      };
      processors = {
        batch = {
          timeout = "5s";
          send_batch_size = 1000;
        };
      };
      exporters = {
        prometheus = {
          endpoint = "0.0.0.0:8889";
          namespace = "gaius";
          resource_to_telemetry_conversion.enabled = true;
        };
        debug.verbosity = "basic";
        # Forward traces to NiFi ListenOTLP for flow visualization
        # NiFi receives OTel data on port 4319 via ListenOTLP processor
        otlphttp = {
          endpoint = "http://localhost:4319";
          tls.insecure = true;
        };
      };
      service = {
        pipelines = {
          traces = {
            receivers = ["otlp"];
            processors = ["batch"];
            exporters = ["debug" "otlphttp"];  # Forward to NiFi
          };
          metrics = {
            receivers = ["otlp"];
            processors = ["batch"];
            exporters = ["prometheus"];
          };
        };
      };
    };
  };

  # ============================================================================
  # Prometheus - Metrics storage and querying
  # ============================================================================
  services.prometheus = {
    enable = true;
    port = 9090;
    storage.retentionTime = "15d";
    scrapeConfigs = [
      {
        job_name = "otel-collector";
        scrape_interval = "1s";  # 1s scraping for real-time ObservePanel
        static_configs = [{
          targets = ["localhost:8889"];
        }];
      }
    ];
  };

  languages.python = {
    enable = true;
    package = pkgs.python312;
    uv.enable = true;
    uv.sync.enable = true;
    venv.enable = true;
  };

  # Java for building Cloudera parcel validator (thirdparty/cm_ext)
  languages.java = {
    enable = true;
    jdk.package = pkgs.jdk11;  # Java 11 for cm_ext compatibility
    maven.enable = true;
  };

  # JavaScript/Node.js for claude-code-acp adapter
  # Required for ACP integration with Claude Code
  languages.javascript = {
    enable = true;
    npm = {
      enable = true;
      install.enable = true;  # Enable declarative npm package installation
    };
  };

  languages.typescript = {
    enable=true;
  };

  tasks = {
    "docs:build".exec = "mdbook build docs";
    "docs:open".exec = "mdbook build docs --open";

    # Third-party build tasks
    "thirdparty:download".exec = "cd thirdparty && ./download-thirdparty.sh";
    "thirdparty:build".exec = "cd thirdparty && ./build-thirdparty.sh";

    # Proto generation task - regenerates gRPC stubs and fixes imports
    "proto:generate".exec = ''
      echo "╔══════════════════════════════════════════════════════════════╗"
      echo "║  PROTO GENERATE - Regenerating gRPC Python stubs             ║"
      echo "╚══════════════════════════════════════════════════════════════╝"
      echo ""

      PROTO_DIR="src/gaius/engine/proto"
      OUT_DIR="src/gaius/engine/generated"

      echo "Source:  $PROTO_DIR/gaius_service.proto"
      echo "Output:  $OUT_DIR/"
      echo ""

      # Generate Python stubs
      python -m grpc_tools.protoc \
        -I="$PROTO_DIR" \
        --python_out="$OUT_DIR" \
        --pyi_out="$OUT_DIR" \
        --grpc_python_out="$OUT_DIR" \
        "$PROTO_DIR/gaius_service.proto"

      echo "✓ Proto stubs generated"

      # Fix absolute import to relative import in grpc file
      # grpc_tools.protoc generates: import gaius_service_pb2 as gaius__service__pb2
      # We need:                     from . import gaius_service_pb2 as gaius__service__pb2
      sed -i 's/^import gaius_service_pb2/from . import gaius_service_pb2/' \
        "$OUT_DIR/gaius_service_pb2_grpc.py"

      echo "✓ Fixed relative imports in gaius_service_pb2_grpc.py"
      echo ""
      echo "Done! Regenerated files:"
      ls -la "$OUT_DIR"/gaius_service_pb2*.py
    '';

    # MCP server tasks
    "mcp:test".exec = ''
      # Test that MCP server can start (useful for debugging)
      PYTHONPATH="" .devenv/state/venv/bin/python -c "from gaius.mcp_server import create_server; print('MCP server OK')"
    '';

    # GPU cleanup task - kills stale vLLM processes and frees GPU memory
    "gpu:cleanup".exec = ''
      echo "╔══════════════════════════════════════════════════════════════╗"
      echo "║  GPU CLEANUP - Killing stale vLLM processes                  ║"
      echo "╚══════════════════════════════════════════════════════════════╝"
      echo ""

      # Find and kill any stale vLLM processes
      VLLM_PIDS=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | tr '\n' ' ')
      if [ -n "$VLLM_PIDS" ]; then
        echo "Found GPU processes: $VLLM_PIDS"
        for pid in $VLLM_PIDS; do
          if [ -n "$pid" ]; then
            echo "  Killing PID $pid..."
            kill -9 "$pid" 2>/dev/null || true
          fi
        done
        sleep 2
        echo "✓ GPU processes terminated"
      else
        echo "✓ No stale GPU processes found"
      fi

      # Also kill any orphaned Python vllm processes
      pkill -9 -f "vllm serve" 2>/dev/null || true
      pkill -9 -f "gaius.engine.server" 2>/dev/null || true

      # Show GPU memory status
      echo ""
      echo "GPU Memory Status:"
      nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader 2>/dev/null || echo "  (nvidia-smi not available)"
      echo ""
    '';

    # Deep cleanup - kills ALL inference-related processes including orphaned ones
    "gpu:deep-cleanup".exec = ''
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
    '';
  };

  # MCP server as an optional process (for debugging - Claude Code manages its own)
  processes.gaius-mcp = {
    exec = ''
      # Clear PYTHONPATH to avoid Nix store conflicts
      export PYTHONPATH=""
      exec .devenv/state/venv/bin/python -m gaius.mcp_server
    '';
    # Not started by default - use `devenv up gaius-mcp` to start manually
    process-compose.disabled = true;
  };

  # ============================================================================
  # Gaius Engine processes (disable with DISABLE_ENGINE=true in .env)
  # ============================================================================

  # Aeron Media Driver (C++ native) - must start first
  processes.aeron-driver = {
    exec = ''
      if [ "''${DISABLE_ENGINE:-false}" == "true" ]; then
        echo "Aeron Media Driver disabled (DISABLE_ENGINE=true)"
        sleep infinity
      fi

      echo "╔══════════════════════════════════════════════════════════════╗"
      echo "║  AERON MEDIA DRIVER - Ultra-Low-Latency IPC Transport        ║"
      echo "╚══════════════════════════════════════════════════════════════╝"
      echo ""

      # Clean up stale Aeron directories
      AERON_DIR="/dev/shm/gaius-aeron"
      if [ -d "$AERON_DIR" ]; then
        echo "Cleaning up stale Aeron directory: $AERON_DIR"
        rm -rf "$AERON_DIR"
      fi

      echo "Starting Aeron Media Driver (C++ native)..."
      echo "  IPC Channel: aeron:ipc"
      echo "  Shared Memory: $AERON_DIR"
      echo ""

      # Set Aeron directory and run native driver
      export AERON_DIR="$AERON_DIR"
      exec aeronmd
    '';
    # Auto-start by default (use DISABLE_ENGINE=true to opt out)
  };

  # Gaius Engine - the central daemon
  # NOTE: Engine manages optillm/vLLM processes dynamically, not devenv
  processes.gaius-engine = {
    exec = ''
      if [ "''${DISABLE_ENGINE:-false}" == "true" ]; then
        echo "Gaius Engine disabled (DISABLE_ENGINE=true)"
        sleep infinity
      fi

      echo "╔══════════════════════════════════════════════════════════════╗"
      echo "║  GAIUS ENGINE - Centralized Inference & Evolution Daemon     ║"
      echo "╚══════════════════════════════════════════════════════════════╝"
      echo ""

      # ========================================================================
      # GPU CLEANUP - Ensure clean start by killing any stale vLLM processes
      # ========================================================================
      echo "Cleaning up stale GPU processes..."

      # Find and kill any processes using GPU memory
      VLLM_PIDS=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | tr '\n' ' ')
      if [ -n "$VLLM_PIDS" ]; then
        echo "  Found GPU processes: $VLLM_PIDS"
        for pid in $VLLM_PIDS; do
          if [ -n "$pid" ]; then
            echo "    Killing PID $pid..."
            kill -9 "$pid" 2>/dev/null || true
          fi
        done
        sleep 2
        echo "  ✓ GPU processes terminated"
      else
        echo "  ✓ No stale GPU processes found"
      fi

      # Also kill any orphaned Python vllm/engine processes (not using GPU yet)
      pkill -9 -f "vllm serve" 2>/dev/null || true
      pkill -9 -f "gaius.engine.server" 2>/dev/null || true

      # Show GPU memory status
      echo ""
      echo "GPU Memory Status:"
      nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader 2>/dev/null | sed 's/^/  /' || echo "  (nvidia-smi not available)"
      echo ""

      # ========================================================================
      # WAIT FOR AERON
      # ========================================================================
      AERON_DIR="/dev/shm/gaius-aeron"
      echo "Waiting for Aeron media driver..."
      for i in $(seq 1 30); do
        if [ -f "$AERON_DIR/cnc.dat" ]; then
          echo "✓ Aeron media driver ready"
          break
        fi
        if [ $i -eq 30 ]; then
          echo "ERROR: Aeron media driver not ready after 30s"
          exit 1
        fi
        sleep 1
      done

      # Enable OpenTelemetry tracing if configured
      export OTEL_SERVICE_NAME="gaius-engine"
      export OTEL_EXPORTER_OTLP_ENDPOINT="''${OTEL_ENDPOINT:-http://localhost:4317}"

      # Set API keys for inference backends
      export OPTILLM_API_KEY="''${OPTILLM_API_KEY:-gaius-local-key}"
      export OPENAI_API_KEY="''${OPTILLM_API_KEY:-gaius-local-key}"

      echo ""
      echo "Starting gaius-engine (manages optillm/vLLM dynamically)..."
      export PYTHONPATH=""
      exec .devenv/state/venv/bin/python -m gaius.engine --config config/agents.conf -v
    '';
    # Auto-start by default, depends on aeron-driver
    process-compose = {
      depends_on.aeron-driver.condition = "process_started";
    };
  };

  # optillm server - standalone for debugging (engine normally manages this)
  processes.optillm = {
    exec = ''
      echo "╔══════════════════════════════════════════════════════════════╗"
      echo "║  OPTILLM - Standalone Mode (for debugging)                   ║"
      echo "╚══════════════════════════════════════════════════════════════╝"
      echo ""
      echo "NOTE: Normally gaius-engine manages optillm. Use this only for debugging."
      echo ""

      export OPTILLM_API_KEY="''${OPTILLM_API_KEY:-gaius-local-key}"
      export OPENAI_API_KEY="''${OPTILLM_API_KEY:-gaius-local-key}"

      echo "Starting optillm on port 8000..."
      export PYTHONPATH=""
      exec .devenv/state/venv/bin/python -m optillm --host 0.0.0.0 --port 8000
    '';
    # Disabled by default - engine manages optillm dynamically
    process-compose.disabled = true;
  };

  # ============================================================================
  # Metaflow Database Setup - Prepare database for metadata service
  # ============================================================================
  #
  # The Metaflow metadata service runs via K8s/Tilt (see metaflow-ui process).
  # This process only sets up the PostgreSQL database and user.

  processes.metaflow-db-setup = {
    exec = ''
      echo "╔══════════════════════════════════════════════════════════════╗"
      echo "║  METAFLOW DATABASE SETUP                                     ║"
      echo "╚══════════════════════════════════════════════════════════════╝"
      echo ""

      # Wait for postgres to be ready
      echo "Waiting for PostgreSQL..."
      for i in $(seq 1 30); do
        if pg_isready -h 127.0.0.1 -p 5438 -U gaius >/dev/null 2>&1; then
          echo "✓ PostgreSQL ready"
          break
        fi
        if [ $i -eq 30 ]; then
          echo "ERROR: PostgreSQL not ready after 30s"
          exit 1
        fi
        sleep 1
      done

      # Create metaflow user and database if they don't exist
      # Use $USER (superuser) for initial setup since gaius doesn't have CREATEROLE
      echo "Ensuring metaflow user and database exist..."
      psql -h 127.0.0.1 -p 5438 -U $USER -d zndx_gaius -tc \
        "SELECT 1 FROM pg_roles WHERE rolname = 'metaflow'" | \
        grep -q 1 || \
        psql -h 127.0.0.1 -p 5438 -U $USER -d zndx_gaius -c "CREATE USER metaflow WITH PASSWORD 'metaflow'"

      psql -h 127.0.0.1 -p 5438 -U $USER -d zndx_gaius -tc \
        "SELECT 1 FROM pg_database WHERE datname = 'metaflow'" | \
        grep -q 1 || \
        psql -h 127.0.0.1 -p 5438 -U $USER -d zndx_gaius -c "CREATE DATABASE metaflow OWNER metaflow"

      # Grant permissions
      psql -h 127.0.0.1 -p 5438 -U $USER -d metaflow -c "GRANT ALL PRIVILEGES ON DATABASE metaflow TO metaflow" 2>/dev/null || true
      echo "✓ metaflow user and database ready"

      # Ensure metaflow-artifacts bucket exists in MinIO
      echo "Ensuring metaflow-artifacts bucket exists..."
      mc alias set local http://localhost:9010 minioadmin minioadmin 2>/dev/null || true
      mc mb --ignore-existing local/metaflow-artifacts 2>/dev/null || true
      echo "✓ MinIO bucket ready"

      echo ""
      echo "Metaflow database setup complete."
      echo "To start the full Metaflow stack (service + UI), run:"
      echo "  devenv processes up metaflow-ui"
      echo ""
      echo "Or start Tilt manually:"
      echo "  cd infra/tilt && tilt up"
    '';
    process-compose = {
      depends_on.postgres.condition = "process_healthy";
      # This is a one-shot setup task
      availability.restart = "no";
    };
  };

  # ============================================================================
  # Metaflow UI - Web dashboard via Tilt on K8s
  # ============================================================================

  processes.metaflow-ui = {
    exec = ''
      if [ "''${DISABLE_METAFLOW_UI:-false}" == "true" ]; then
        echo "Metaflow UI disabled (DISABLE_METAFLOW_UI=true)"
        sleep infinity
      fi

      echo "╔══════════════════════════════════════════════════════════════╗"
      echo "║  METAFLOW UI - Web Dashboard via Tilt                        ║"
      echo "╚══════════════════════════════════════════════════════════════╝"
      echo ""

      # Check for kubectl
      if ! command -v kubectl &> /dev/null; then
        echo "ERROR: kubectl not found. Install RKE2 or configure KUBECONFIG."
        exit 1
      fi

      # Check K8s connectivity
      echo "Checking Kubernetes connectivity..."
      if ! kubectl cluster-info &> /dev/null; then
        echo "ERROR: Cannot connect to Kubernetes cluster."
        echo "Ensure RKE2 is running: systemctl status rke2-server"
        exit 1
      fi
      echo "✓ Kubernetes cluster accessible"

      # Apply NodePort services for devenv
      echo "Applying NodePort services..."
      kubectl apply -f infra/k8s/devenv-services.yaml
      echo "✓ NodePort services applied"

      echo ""
      echo "Starting Tilt for Metaflow UI..."
      echo "  Metaflow UI:      http://localhost:3000"
      echo "  Argo Workflows:   http://localhost:2746"
      echo ""
      cd infra/tilt
      exec tilt up --stream
    '';
    process-compose = {
      depends_on = {
        postgres.condition = "process_healthy";
        metaflow-db-setup.condition = "process_completed_successfully";
      };
      # Enabled - Metaflow UI is a core platform component
      disabled = false;
    };
  };

  # ============================================================================
  # Metaflow Port Forwards - External access from laptops
  # ============================================================================
  #
  # Tilt's port-forwards only bind to localhost. This process creates
  # additional port-forwards bound to 0.0.0.0 for external access.

  processes.metaflow-port-forwards = {
    exec = ''
      echo "╔══════════════════════════════════════════════════════════════╗"
      echo "║  METAFLOW PORT FORWARDS - External Access                    ║"
      echo "╚══════════════════════════════════════════════════════════════╝"
      echo ""

      # Wait for Kubernetes services to be created by Tilt
      # This may take a minute or two on first startup
      echo "Waiting for Metaflow K8s services to be ready..."
      echo "(This may take 1-2 minutes on first startup)"
      echo ""

      MAX_WAIT=180
      WAITED=0
      while ! kubectl get svc metaflow-ui-static &>/dev/null; do
        sleep 5
        WAITED=$((WAITED + 5))
        if [ $WAITED -ge $MAX_WAIT ]; then
          echo "ERROR: Metaflow services not ready after ''${MAX_WAIT}s"
          echo "Check metaflow-ui process logs or run: kubectl get svc"
          exit 1
        fi
        echo "  Waiting for services... (''${WAITED}s)"
      done
      echo "✓ metaflow-ui-static service discovered"

      # Wait for endpoints to be ready (pods running)
      echo "Waiting for pods to be ready..."
      kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=metaflow-ui-static --timeout=120s 2>/dev/null || true
      echo "✓ Pods ready"

      # Kill any existing port-forwards on these ports
      fuser -k 3000/tcp 2>/dev/null || true
      fuser -k 8083/tcp 2>/dev/null || true
      fuser -k 8180/tcp 2>/dev/null || true
      sleep 1

      echo ""
      echo "Starting port-forwards on 0.0.0.0 for external access..."
      echo "  Metaflow UI:        http://192.168.1.55:3000"
      echo "  Metaflow UI API:    http://192.168.1.55:8083"
      echo "  Metaflow Service:   http://192.168.1.55:8180"
      echo ""

      # Run port-forwards in parallel, restarting on failure
      while true; do
        kubectl port-forward --address 0.0.0.0 svc/metaflow-ui-static 3000:3000 &
        PF1=$!
        kubectl port-forward --address 0.0.0.0 svc/metaflow-ui 8083:8083 &
        PF2=$!
        kubectl port-forward --address 0.0.0.0 svc/metaflow-service 8180:8080 &
        PF3=$!

        # Wait for any to exit
        wait -n $PF1 $PF2 $PF3 2>/dev/null || true
        echo "Port-forward exited, restarting in 5s..."
        kill $PF1 $PF2 $PF3 2>/dev/null || true
        sleep 5
      done
    '';
    process-compose = {
      depends_on = {
        metaflow-ui.condition = "process_started";
      };
      availability = {
        restart = "always";
      };
      # Enabled by default for external access
      disabled = false;
    };
  };

  # ============================================================================
  # Metabase - Business Intelligence Dashboard
  # ============================================================================
  #
  # Provides analytics dashboards for agent metrics, evolution tracking,
  # KB topology, and system health visualization.
  #
  # Access: http://tinybox.dev.vista.zndx.org:3100
  # Initial setup: Create admin account on first launch

  processes.metabase = {
    exec = ''
      if [ "''${DISABLE_METABASE:-false}" == "true" ]; then
        echo "Metabase disabled (DISABLE_METABASE=true)"
        sleep infinity
      fi

      echo "╔══════════════════════════════════════════════════════════════╗"
      echo "║  METABASE - Business Intelligence Dashboard                  ║"
      echo "╚══════════════════════════════════════════════════════════════╝"
      echo ""

      # Wait for PostgreSQL to be ready
      echo "Waiting for PostgreSQL..."
      for i in $(seq 1 30); do
        if pg_isready -h 127.0.0.1 -p 5438 -U postgres >/dev/null 2>&1; then
          echo "✓ PostgreSQL ready"
          break
        fi
        if [ $i -eq 30 ]; then
          echo "ERROR: PostgreSQL not ready after 30s"
          exit 1
        fi
        sleep 1
      done

      # Metabase data directory
      METABASE_DATA_DIR="${config.devenv.root}/.devenv/state/metabase"
      mkdir -p "$METABASE_DATA_DIR"

      echo ""
      echo "Starting Metabase on port 3100..."
      echo "  URL:        http://0.0.0.0:3100"
      echo "  External:   http://tinybox.dev.vista.zndx.org:3100"
      echo "  Data dir:   $METABASE_DATA_DIR"
      echo ""

      # Metabase configuration via environment variables
      export MB_JETTY_HOST="0.0.0.0"
      export MB_JETTY_PORT="3100"

      # Use PostgreSQL for Metabase application database (not H2)
      export MB_DB_TYPE="postgres"
      export MB_DB_HOST="127.0.0.1"
      export MB_DB_PORT="5438"
      export MB_DB_DBNAME="zndx_gaius"
      export MB_DB_USER="$USER"
      export MB_DB_PASS=""

      # Metabase stores its own metadata in 'metabase_*' tables
      # This is separate from our 'meta' schema for analytics

      exec ${pkgs.metabase}/bin/metabase
    '';
    process-compose = {
      depends_on.postgres.condition = "process_healthy";
      # Disabled by default - enable with: devenv processes up metabase
      disabled = false;
    };
  };

  # ============================================================================
  # Apache NiFi - Data Flow Visualization
  # ============================================================================
  #
  # Visualizes Metaflow pipeline steps as NiFi flows for monitoring and
  # situational awareness. MetaAgent projects flows onto the NiFi canvas.
  #
  # Access: http://tinybox.dev.vista.zndx.org:8450/nifi
  # Note: First startup may take 1-2 minutes to initialize.

  processes.nifi = {
    exec = ''
      if [ "''${DISABLE_NIFI:-false}" == "true" ]; then
        echo "NiFi disabled (DISABLE_NIFI=true)"
        sleep infinity
      fi

      echo "╔══════════════════════════════════════════════════════════════╗"
      echo "║  APACHE NIFI - Data Flow Visualization                       ║"
      echo "╚══════════════════════════════════════════════════════════════╝"
      echo ""

      # NiFi requires a writable home directory with specific structure
      NIFI_HOME="${config.devenv.root}/.devenv/state/nifi"
      NIFI_PACKAGE="${pkgs.nifi}"

      mkdir -p "$NIFI_HOME"/{conf,logs,run,database_repository,flowfile_repository,content_repository,provenance_repository,state,work}

      # Symlink lib directory from Nix store (read-only, contains JARs)
      if [ ! -L "$NIFI_HOME/lib" ]; then
        ln -sf "$NIFI_PACKAGE/lib" "$NIFI_HOME/lib"
      fi

      # Copy default config files if not present (always refresh on startup for dev)
      if [ ! -f "$NIFI_HOME/conf/bootstrap.conf" ] || [ ! -f "$NIFI_HOME/conf/nifi.properties.initialized" ]; then
        echo "Initializing NiFi configuration..."

        # Copy from Nix store and make writable (Nix store files are read-only)
        rm -rf "$NIFI_HOME/conf"/* 2>/dev/null || true
        cp -r "$NIFI_PACKAGE"/share/nifi/conf/* "$NIFI_HOME/conf/" 2>/dev/null || true
        chmod -R u+w "$NIFI_HOME/conf/"

        # Update bootstrap.conf to use absolute paths
        cat > "$NIFI_HOME/conf/bootstrap.conf" << BOOTSTRAP_EOF
# NiFi Bootstrap Configuration for Gaius
java=java
run.as=
preserve.environment=false

# Use absolute paths for lib and conf
lib.dir=$NIFI_HOME/lib
conf.dir=$NIFI_HOME/conf

graceful.shutdown.seconds=20
java.arg.1=-Dorg.apache.jasper.compiler.disablejsr199=true
java.arg.2=-Xms512m
java.arg.3=-Xmx1g
java.arg.4=-Djava.net.preferIPv4Stack=true
java.arg.5=-Dsun.net.http.allowRestrictedHeaders=true
java.arg.6=-Djava.protocol.handler.pkgs=sun.net.www.protocol
java.arg.14=-Djava.awt.headless=true
java.arg.15=-Djava.security.egd=file:/dev/urandom
java.arg.16=-Djavax.security.auth.useSubjectCredsOnly=true
java.arg.17=-Dzookeeper.admin.enableServer=false
nifi.bootstrap.sensitive.key=
notification.services.file=$NIFI_HOME/conf/bootstrap-notification-services.xml
notification.max.attempts=5
java.arg.curator.supress.excessive.logs=-Dcurator-log-only-first-connection-issue-as-error-level=true
nifi.bootstrap.listen.port=0
BOOTSTRAP_EOF

        # Modify the default nifi.properties for our environment
        # Use sed to update specific properties rather than replacing the whole file
        PROPS="$NIFI_HOME/conf/nifi.properties"

        # Web server - bind to all interfaces on port 8450 (HTTP only, clear HTTPS)
        sed -i 's|^nifi.web.http.host=.*|nifi.web.http.host=0.0.0.0|' "$PROPS"
        sed -i 's|^nifi.web.http.port=.*|nifi.web.http.port=8450|' "$PROPS"
        # Clear HTTPS port - NiFi requires HTTP OR HTTPS, not both
        sed -i 's|^nifi.web.https.host=.*|nifi.web.https.host=|' "$PROPS"
        sed -i 's|^nifi.web.https.port=.*|nifi.web.https.port=|' "$PROPS"

        # Clear TLS/security properties for HTTP-only mode
        # These point to non-existent keystore/truststore files by default
        sed -i 's|^nifi.security.keystore=.*|nifi.security.keystore=|' "$PROPS"
        sed -i 's|^nifi.security.keystoreType=.*|nifi.security.keystoreType=|' "$PROPS"
        sed -i 's|^nifi.security.keystorePasswd=.*|nifi.security.keystorePasswd=|' "$PROPS"
        sed -i 's|^nifi.security.keyPasswd=.*|nifi.security.keyPasswd=|' "$PROPS"
        sed -i 's|^nifi.security.truststore=.*|nifi.security.truststore=|' "$PROPS"
        sed -i 's|^nifi.security.truststoreType=.*|nifi.security.truststoreType=|' "$PROPS"
        sed -i 's|^nifi.security.truststorePasswd=.*|nifi.security.truststorePasswd=|' "$PROPS"

        # Disable remote input secure mode (Site-to-Site) - requires HTTPS if true
        sed -i 's|^nifi.remote.input.secure=.*|nifi.remote.input.secure=false|' "$PROPS"

        # Set sensitive properties key for encryption
        sed -i 's|^nifi.sensitive.props.key=.*|nifi.sensitive.props.key=gaius-dev-key-12345|' "$PROPS"

        # Convert relative paths to absolute paths
        sed -i "s|^\(nifi.flow.configuration.file=\).*|\1$NIFI_HOME/conf/flow.json.gz|" "$PROPS"
        sed -i "s|^\(nifi.flow.configuration.json.file=\).*|\1$NIFI_HOME/conf/flow.json.gz|" "$PROPS"
        sed -i "s|^\(nifi.flow.configuration.archive.dir=\).*|\1$NIFI_HOME/conf/archive/|" "$PROPS"
        sed -i "s|^\(nifi.database.directory=\).*|\1$NIFI_HOME/database_repository|" "$PROPS"
        sed -i "s|^\(nifi.flowfile.repository.directory=\).*|\1$NIFI_HOME/flowfile_repository|" "$PROPS"
        sed -i "s|^\(nifi.content.repository.directory.default=\).*|\1$NIFI_HOME/content_repository|" "$PROPS"
        sed -i "s|^\(nifi.provenance.repository.directory.default=\).*|\1$NIFI_HOME/provenance_repository|" "$PROPS"
        sed -i "s|^\(nifi.state.management.configuration.file=\).*|\1$NIFI_HOME/conf/state-management.xml|" "$PROPS"
        sed -i "s|^\(nifi.state.management.embedded.zookeeper.properties=\).*|\1$NIFI_HOME/conf/zookeeper.properties|" "$PROPS"
        sed -i "s|^\(nifi.authorizer.configuration.file=\).*|\1$NIFI_HOME/conf/authorizers.xml|" "$PROPS"
        sed -i "s|^\(nifi.login.identity.provider.configuration.file=\).*|\1$NIFI_HOME/conf/login-identity-providers.xml|" "$PROPS"
        sed -i "s|^\(nifi.templates.directory=\).*|\1$NIFI_HOME/conf/templates|" "$PROPS"
        sed -i "s|^\(nifi.nar.library.directory=\).*|\1$NIFI_HOME/lib|" "$PROPS"
        sed -i "s|^\(nifi.nar.library.autoload.directory=\).*|\1$NIFI_HOME/extensions|" "$PROPS"
        sed -i "s|^\(nifi.nar.working.directory=\).*|\1$NIFI_HOME/work/nar/|" "$PROPS"
        sed -i "s|^\(nifi.documentation.working.directory=\).*|\1$NIFI_HOME/work/docs/components|" "$PROPS"
        sed -i "s|^\(nifi.status.repository.questdb.persist.location=\).*|\1$NIFI_HOME/status_repository|" "$PROPS"

        # Update state-management.xml with absolute path
        if [ -f "$NIFI_HOME/conf/state-management.xml" ]; then
          sed -i "s|<property name=\"Directory\">./state/local</property>|<property name=\"Directory\">$NIFI_HOME/state/local</property>|g" "$NIFI_HOME/conf/state-management.xml"
        fi

        # Ensure all conf files are writable (NiFi needs to update them at runtime)
        chmod -R u+w "$NIFI_HOME/conf/"

        # Mark as initialized
        touch "$NIFI_HOME/conf/nifi.properties.initialized"
      fi

      # Create extensions directory for user NARs
      mkdir -p "$NIFI_HOME/extensions"
      mkdir -p "$NIFI_HOME/work/nar"
      mkdir -p "$NIFI_HOME/conf/archive"
      mkdir -p "$NIFI_HOME/state/local"

      echo ""
      echo "Starting NiFi on port 8450..."
      echo "  URL:        http://0.0.0.0:8450/nifi"
      echo "  External:   http://tinybox.dev.vista.zndx.org:8450/nifi"
      echo "  Home:       $NIFI_HOME"
      echo ""
      echo "Note: First startup may take 1-2 minutes to initialize."
      echo "      Check $NIFI_HOME/logs/nifi-app.log for single-user credentials."
      echo ""

      # Critical: Tell nifi-env.sh to use OUR environment variables
      export NIFI_OVERRIDE_NIFIENV="true"
      export NIFI_HOME="$NIFI_HOME"
      export NIFI_LOG_DIR="$NIFI_HOME/logs"
      export NIFI_PID_DIR="$NIFI_HOME/run"

      cd "$NIFI_HOME"

      # Run NiFi in foreground mode
      exec ${pkgs.nifi}/bin/nifi.sh run
    '';
    process-compose = {
      # NiFi is independent of other services
      # Disabled by default - enable with: devenv processes up nifi
      disabled = false;
    };
  };

  # ============================================================================
  # Gaius Fetch Worker - Content gathering daemon
  # ============================================================================

  processes.gaius-worker = {
    exec = ''
      if [ "''${DISABLE_WORKER:-false}" == "true" ]; then
        echo "Gaius Worker disabled (DISABLE_WORKER=true)"
        sleep infinity
      fi

      echo "╔══════════════════════════════════════════════════════════════╗"
      echo "║  GAIUS WORKER - Content Gathering Daemon                     ║"
      echo "╚══════════════════════════════════════════════════════════════╝"
      echo ""

      # Wait for postgres to be ready
      echo "Waiting for PostgreSQL..."
      for i in $(seq 1 30); do
        if pg_isready -h 127.0.0.1 -p 5438 -U postgres >/dev/null 2>&1; then
          echo "✓ PostgreSQL ready"
          break
        fi
        if [ $i -eq 30 ]; then
          echo "ERROR: PostgreSQL not ready after 30s"
          exit 1
        fi
        sleep 1
      done

      echo ""
      echo "Starting gaius-worker daemon (pool-size=2, poll-interval=60)..."
      export PYTHONPATH=""
      exec .devenv/state/venv/bin/python -m gaius.workers.cli --pool-size 2 --poll-interval 60 -v
    '';
    # Auto-start by default, depends on postgres
    process-compose = {
      depends_on.postgres.condition = "process_healthy";
    };
  };

  # ============================================================================
  # Tasks - Run with: devenv tasks run <task-name>
  # ============================================================================

  # Clean restart of devenv - kills all stale processes and starts fresh
  # Usage: devenv tasks run restart:clean
  tasks."restart:clean" = {
    exec = ''
      echo "╔══════════════════════════════════════════════════════════════╗"
      echo "║  CLEAN RESTART - Full cleanup and fresh start                ║"
      echo "╚══════════════════════════════════════════════════════════════╝"
      echo ""

      START_TIME=$(date +%s)

      # Step 1: Stop devenv processes
      echo "Step 1/7: Stopping devenv processes..."
      devenv processes down 2>/dev/null || true
      sleep 2
      echo "  ✓ devenv processes stopped"

      # Step 2: Kill process-compose
      echo "Step 2/7: Killing process-compose..."
      pkill -9 -f process-compose 2>/dev/null || true
      sleep 1
      echo "  ✓ process-compose killed"

      # Step 3: Kill stale service processes
      echo "Step 3/7: Killing stale service processes..."
      # MinIO
      pkill -9 -f "minio server" 2>/dev/null && echo "  - Killed minio" || true
      # Qdrant
      pkill -9 -f "qdrant" 2>/dev/null && echo "  - Killed qdrant" || true
      # Gaius engine
      pkill -9 -f "gaius.engine" 2>/dev/null && echo "  - Killed gaius.engine" || true
      # Gaius worker
      pkill -9 -f "gaius.workers" 2>/dev/null && echo "  - Killed gaius.workers" || true
      # Aeron media driver
      pkill -9 -f "aeronmd" 2>/dev/null && echo "  - Killed aeronmd" || true
      # NiFi
      pkill -9 -f "nifi" 2>/dev/null && echo "  - Killed nifi" || true
      # Prometheus
      pkill -9 -f "prometheus.*gaius" 2>/dev/null && echo "  - Killed prometheus" || true
      # OpenTelemetry collector
      pkill -9 -f "otelcol" 2>/dev/null && echo "  - Killed otelcol" || true
      # Metabase
      pkill -9 -f "metabase" 2>/dev/null && echo "  - Killed metabase" || true
      sleep 1
      echo "  ✓ Stale services killed"

      # Step 4: Free ports (in case processes didn't release them)
      echo "Step 4/7: Freeing ports..."
      fuser -k 9010/tcp 2>/dev/null && echo "  - Freed 9010 (minio)" || true
      fuser -k 9011/tcp 2>/dev/null && echo "  - Freed 9011 (minio console)" || true
      fuser -k 6339/tcp 2>/dev/null && echo "  - Freed 6339 (qdrant http)" || true
      fuser -k 6340/tcp 2>/dev/null && echo "  - Freed 6340 (qdrant grpc)" || true
      fuser -k 50051/tcp 2>/dev/null && echo "  - Freed 50051 (grpc)" || true
      fuser -k 8450/tcp 2>/dev/null && echo "  - Freed 8450 (nifi)" || true
      fuser -k 3100/tcp 2>/dev/null && echo "  - Freed 3100 (metabase)" || true
      echo "  ✓ Ports freed"

      # Step 5: Clean up stale sockets
      echo "Step 5/7: Cleaning stale sockets..."
      rm -rf /run/user/$(id -u)/devenv-*/ 2>/dev/null || true
      echo "  ✓ Stale sockets removed"

      # Step 6: Remove stale postgres lock
      echo "Step 6/7: Removing stale postgres lock..."
      POSTGRES_PID_FILE="${config.devenv.root}/.devenv/state/postgres/postmaster.pid"
      if [ -f "$POSTGRES_PID_FILE" ]; then
        rm -f "$POSTGRES_PID_FILE"
        echo "  ✓ Postgres lock file removed"
      else
        echo "  ✓ No stale postgres lock"
      fi

      # Step 7: Start fresh
      echo "Step 7/7: Starting devenv..."
      devenv up -d
      echo ""

      # Wait for engine with retry loop
      echo "╔══════════════════════════════════════════════════════════════╗"
      echo "║  Waiting for gRPC engine on port 50051...                    ║"
      echo "╚══════════════════════════════════════════════════════════════╝"
      echo ""

      MAX_CYCLES=60
      CYCLE=0
      while [ $CYCLE -lt $MAX_CYCLES ]; do
        CYCLE=$((CYCLE + 1))
        ELAPSED=$(($(date +%s) - START_TIME))

        if nc -zv localhost 50051 2>/dev/null; then
          echo ""
          echo "╔══════════════════════════════════════════════════════════════╗"
          echo "║  ✓ ENGINE READY                                              ║"
          echo "╠══════════════════════════════════════════════════════════════╣"
          printf "║  Elapsed: %3ds | Cycles: %2d                                  ║\n" "$ELAPSED" "$CYCLE"
          echo "╚══════════════════════════════════════════════════════════════╝"
          echo ""
          echo "You can now test with:"
          echo "  uv run gaius-cli --cmd \"/health\" --format json"
          exit 0
        fi

        printf "\r  Waiting... [%3ds elapsed, cycle %2d/%d]" "$ELAPSED" "$CYCLE" "$MAX_CYCLES"
        sleep 2
      done

      echo ""
      echo "╔══════════════════════════════════════════════════════════════╗"
      echo "║  ✗ ENGINE FAILED TO START                                    ║"
      echo "╠══════════════════════════════════════════════════════════════╣"
      echo "║  Check logs: tail -f .devenv/processes.log                   ║"
      echo "╚══════════════════════════════════════════════════════════════╝"
      exit 1
    '';
  };

  # Clean up orphaned Kubernetes CNI IP allocations
  # Usage: devenv tasks run k8s:cleanup
  tasks."k8s:cleanup" = {
    exec = ''
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
    '';
  };
}

