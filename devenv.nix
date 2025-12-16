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
    imagemagick
    jq
    mdbook
    mdbook-d2
    mdbook-katex
    mdbook-mermaid
    open-policy-agent
    opentofu
    protobuf
    presenterm
    qdrant
    tilt          # K8s development environment for Metaflow
    wrangler
    zlib  # Required for numpy C extensions

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
      };
      service = {
        pipelines = {
          traces = {
            receivers = ["otlp"];
            processors = ["batch"];
            exporters = ["debug"];
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

  tasks = {
    "docs:build".exec = "mdbook build docs";
    "docs:open".exec = "mdbook build docs --open";

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

      # Wait for services to be ready
      echo "Waiting for Metaflow services to be ready..."
      until kubectl get svc metaflow-ui-static &>/dev/null; do
        sleep 2
      done
      echo "✓ Services discovered"

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

