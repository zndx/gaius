{ pkgs, lib, config, inputs, ... }:

{

  dotenv.enable = true;
  cachix.enable = false;

  env.PATH_CONF = "conf";

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

  # https://devenv.sh/packages/
  packages = with pkgs; [
    aeron
    cmake
    conftest
    d2
    dbmate
    git
    gh
    imagemagick
    jq
    mdbook
    mdbook-d2
    mdbook-katex
    mdbook-mermaid
    opentofu
    protobuf
    presenterm
    qdrant
    wrangler
    zlib  # Required for numpy C extensions

    # Gaius Engine dependencies
    aeron-cpp      # Aeron C++ library and aeronmd media driver
    flatbuffers    # FlatBuffers compiler for schema generation
  ];

  services.minio = {
    enable = true;
    buckets = ["zndx-gaius"];
    listenAddress = "127.0.0.1:9010";   # Non-default to avoid conflicts
    consoleAddress = "127.0.0.1:9011";
  };

  services.postgres = {
    enable = true;
    package = pkgs.postgresql_16;
    extensions = ext: [
      ext.pg_cron  # Scheduled tasks
      ext.age      # Apache AGE - Graph database extension for lineage
    ];
    initialDatabases = [{
      name = "zndx_gaius";
    }];
    port = 5438;
    listen_addresses = "127.0.0.1";  # Enable TCP for dbmate/asyncpg
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
}

