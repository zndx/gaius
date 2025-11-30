{ pkgs, lib, config, inputs, ... }:

{

  dotenv.enable = true;
  cachix.enable = false;

  env.PATH_CONF = "conf";

  # Override MinIO data directory to use RAID storage
  env.MINIO_DATA_DIR = lib.mkForce "/raid/minio/gaius";

  # Qdrant configuration via environment variables
  env.QDRANT__STORAGE__STORAGE_PATH = "/raid/qdrant/gaius";
  env.QDRANT__SERVICE__HTTP_PORT = "6339";  # Non-default to avoid conflicts
  env.QDRANT__SERVICE__GRPC_PORT = "6340";

  # https://devenv.sh/packages/
  packages = with pkgs; [
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
    presenterm
    qdrant
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
    extensions = ext: [ ext.pg_cron ];
    initialDatabases = [{
      name = "zndx_gaius";
    }];
    port = 5438;
    listen_addresses = "127.0.0.1";  # Enable TCP for dbmate/asyncpg
    settings = {
      shared_preload_libraries = "pg_cron";
      "cron.database_name" = "zndx_gaius";
    };
    initialScript = ''
      CREATE EXTENSION IF NOT EXISTS pg_cron;
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
  };
}

