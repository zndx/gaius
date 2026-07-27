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

  # Library paths for CUDA and NVIDIA drivers.
  # NOTE: Nix Python's RUNPATH already includes Nix glibc + libstdc++ from the store.
  # Do NOT add pkgs.stdenv.cc.cc.lib here — it leaks Nix libstdc++ (glibc 2.42) to
  # host binaries (apt-get, pip-installed ELFs) via LD_LIBRARY_PATH, causing
  # "GLIBC_2.38 not found" crashes on hosts with older glibc (e.g., Ubuntu 22.04).
  env.LD_LIBRARY_PATH = lib.concatStringsSep ":" [
    # NVIDIA drivers (symlinked to .devenv/nvidia-libs to avoid system glibc conflicts)
    "${config.devenv.root}/.devenv/nvidia-libs"
    # CUDA toolkit paths (if available)
    "/usr/local/cuda/lib64"
    "/usr/local/cuda/extras/CUPTI/lib64"
  ];

  # Pkg-config paths for LuxCore build-from-source.
  # devenv's pkg-config wrapper doesn't automatically include .dev outputs
  # of packages added to the packages list. We merge all .dev outputs into a
  # single buildEnv so conan's opengl/system and xorg/system recipes can find
  # libraries via pkg-config.
  env.LUXCORE_NIX_PKGCONFIG = let
    luxcore-syslibs = pkgs.buildEnv {
      name = "luxcore-syslibs-pkgconfig";
      paths = with pkgs; [
        libGL.dev
        libdrm.dev
        xorg.libX11.dev
        xorg.libxcb.dev
        xorg.libXext.dev
        xorg.libXrender.dev
        xorg.libXrandr.dev
        xorg.libXfixes.dev
        xorg.libXinerama.dev
        xorg.libXcursor.dev
        xorg.libXi.dev
        xorg.libXxf86vm.dev
        xorg.libICE.dev
        xorg.libSM.dev
        xorg.libXau.dev
        xorg.libXdmcp.dev
        xorg.libXt.dev
        xorg.xcbutil.dev
        xorg.xcbutilwm.dev
        xorg.xcbutilimage.dev
        xorg.xcbutilkeysyms.dev
        xorg.xcbutilrenderutil.dev
        xorg.xcbutilcursor.dev
        xorg.libxshmfence.dev
        xorg.libXScrnSaver    # single-output (no .dev)
        xorg.libfontenc       # single-output (no .dev) — fontenc.pc
        xorg.libXaw.dev       # xaw7.pc
        xorg.libXdamage.dev
        xorg.libXcomposite.dev
        xorg.libXtst          # single-output (no .dev) — xtst.pc
        xorg.libXres.dev
        xorg.libxkbfile.dev
        xorg.libXmu.dev       # xmu.pc + xmuu.pc
        xorg.libXpm.dev
        xorg.libXv.dev
        libxkbcommon.dev
        util-linux.dev  # uuid.pc
      ];
      pathsToLink = [ "/lib/pkgconfig" "/share/pkgconfig" ];
    };
  in "${luxcore-syslibs}/lib/pkgconfig";

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
  # The root-owned /etc/rancher/rke2/rke2.yaml is unreadable by non-root users.
  # Copy it once:
  #   sudo cp /etc/rancher/rke2/rke2.yaml ~/.config/kube/rke2.yaml
  #   sudo chown $USER:$USER ~/.config/kube/rke2.yaml
  #   chmod 600 ~/.config/kube/rke2.yaml
  #
  # enterShell sets KUBECONFIG for interactive use. Process scripts set it
  # unconditionally from $HOME (env.KUBECONFIG can't use shell vars, and
  # builtins.getEnv "HOME" is empty in daemon mode).
  enterShell = ''
    export KUBECONFIG="$HOME/.config/kube/rke2.yaml"
    export METAFLOW_SERVICE_URL="http://localhost:30180"
  '';

  # https://devenv.sh/packages/
  packages = with pkgs; [
    just
    aeron
    awscli2
    inputs.blender-bin.packages.${pkgs.system}.default  # Pre-built Blender with GPU (OptiX/CUDA)
    cmake
    conan
    conftest
    d2
    dbmate
    git
    gh
    graphviz
    grpcurl
    imagemagick
    jq
    k9s
    kubectl
    metabase
    mdbook
    mdbook-d2
    mdbook-katex
    mdbook-mermaid
    nifi
    ninja
    open-policy-agent
    opentofu
    protobuf
    presenterm
    qdrant
    tilt          # K8s development environment for Metaflow
    tlaps         # TLA+ proof checker
    wrangler
    # Browser automation for dataset generation (selenium + chromedriver)
    chromium
    chromedriver

    # Gaius Engine dependencies
    aeron-cpp      # Aeron C++ library and aeronmd media driver
    flatbuffers    # FlatBuffers compiler for schema generation

    # LuxCore build-from-source dependencies (thirdparty/src/LuxCore)
    # Build with: just thirdparty-luxcore
    # Provides system libraries that conan's opengl/system and xorg/system
    # recipes would otherwise try to apt-get install.
    libGL          # OpenGL runtime + headers (GL/gl.h, gl.pc)
    libdrm         # DRM (Direct Rendering Manager)
    xorg.libX11    # X11 core
    xorg.libxcb    # XCB protocol library
    xorg.libXext   # X11 extensions
    xorg.libXrender
    xorg.libXrandr
    xorg.libXfixes
    xorg.libXinerama
    xorg.libXcursor
    xorg.libXi     # X Input
    xorg.libXxf86vm
    xorg.libICE
    xorg.libSM
    xorg.libXau
    xorg.libXdmcp
    xorg.libXt
    xorg.libfontenc
    xorg.xorgproto   # X11 protocol headers
    xorg.xcbutil      # xcb-util
    xorg.xcbutilwm    # xcb-ewmh, xcb-icccm
    xorg.xcbutilimage
    xorg.xcbutilkeysyms
    xorg.xcbutilrenderutil
    xorg.xcbutilcursor
    xorg.libxshmfence
    xorg.libXScrnSaver  # Xss
    xorg.libXaw        # Athena widgets (xaw7)
    xorg.libXdamage    # X Damage
    xorg.libXcomposite # X Composite
    xorg.libXtst       # X Test (xtst)
    xorg.libXres       # X Resource
    xorg.libxkbfile    # XKB file handling
    xorg.libXmu        # X Miscellaneous Utilities (xmu + xmuu)
    xorg.libXpm        # X Pixmap
    xorg.libXv         # X Video
    libxkbcommon   # XKB keyboard handling
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
    port = 5444;
    listen_addresses = "*";  # Enable TCP from K8s pods and local clients
    settings = {
      shared_preload_libraries = "pg_cron,age";
      "cron.database_name" = "zndx_gaius";
      log_destination = "stderr";
      logging_collector = "off";
      log_min_messages = "warning";
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
    # OR-Tools CP-SAT is required for the orchestrator's makespan scheduler
    # (capability-based BeginWorkload path fails with #SCH.00000001.NOORDEPS
    # without it) — sync the extra so the solver is always present.
    uv.sync.extras = [ "scheduler" ];
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

  # Operational tasks migrated to justfile (run with: just <recipe>)
  # See: just --list

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
      exec ${config.devenv.root}/scripts/processes/aeron-driver.sh
    '';
  };

  # Gaius Engine - the central daemon
  # NOTE: Engine manages optillm/vLLM processes dynamically, not devenv
  processes.gaius-engine = {
    exec = ''
      exec ${config.devenv.root}/scripts/processes/gaius-engine.sh
    '';
    process-compose = {
      depends_on.aeron-driver.condition = "process_started";
    };
  };

  # optillm is engine-managed — see gaius.engine.backends.optillm_controller
  # Removed standalone processes.optillm block (was disabled, caused confusion)

  # Metaflow Database Setup (one-shot: creates user/database + MinIO bucket)
  processes.metaflow-db-setup = {
    exec = ''
      exec ${config.devenv.root}/scripts/processes/metaflow-db-setup.sh
    '';
    process-compose = {
      depends_on.postgres.condition = "process_healthy";
      availability.restart = "no";
    };
  };

  # Metaflow Bootstrap (one-shot K8s deployment via tilt ci, idempotent)
  processes.metaflow-bootstrap = {
    exec = ''
      exec ${config.devenv.root}/scripts/processes/metaflow-bootstrap.sh
    '';
    process-compose = {
      depends_on = {
        postgres.condition = "process_healthy";
        metaflow-db-setup.condition = "process_completed_successfully";
      };
      availability.restart = "no";
    };
  };

  # Metaflow UI (opt-in: `devenv processes up metaflow-ui`)
  processes.metaflow-ui = {
    exec = ''
      exec ${config.devenv.root}/scripts/processes/metaflow-ui.sh
    '';
    process-compose = {
      depends_on = {
        postgres.condition = "process_healthy";
        metaflow-db-setup.condition = "process_completed_successfully";
      };
      disabled = true;
    };
  };

  # Metaflow Port Forwards (0.0.0.0 binds for external laptop access)
  processes.metaflow-port-forwards = {
    exec = ''
      exec ${config.devenv.root}/scripts/processes/metaflow-port-forwards.sh
    '';
    process-compose = {
      depends_on.postgres.condition = "process_healthy";
      availability.restart = "always";
      readiness_probe = {
        http_get = {
          host = "localhost";
          port = 30180;
          path = "/ping";
        };
        initial_delay_seconds = 10;
        period_seconds = 5;
        failure_threshold = 30;
      };
    };
  };

  # Metabase (BI dashboard — http://tinybox.dev.vista.zndx.org:3100)
  processes.metabase = {
    exec = ''
      export METABASE_PACKAGE="${pkgs.metabase}"
      export DEVENV_ROOT="${config.devenv.root}"
      exec ${config.devenv.root}/scripts/processes/metabase.sh
    '';
    process-compose = {
      depends_on.postgres.condition = "process_healthy";
      disabled = false;
    };
  };

  # Apache NiFi (data flow visualization — http://tinybox.dev.vista.zndx.org:8450/nifi)
  processes.nifi = {
    exec = ''
      export NIFI_PACKAGE="${pkgs.nifi}"
      export DEVENV_ROOT="${config.devenv.root}"
      exec ${config.devenv.root}/scripts/processes/nifi.sh
    '';
    process-compose.disabled = false;
  };

  # Gaius Fetch Worker (content gathering daemon)
  processes.gaius-worker = {
    exec = ''
      exec ${config.devenv.root}/scripts/processes/gaius-worker.sh
    '';
    process-compose = {
      depends_on.postgres.condition = "process_healthy";
    };
  };

}

