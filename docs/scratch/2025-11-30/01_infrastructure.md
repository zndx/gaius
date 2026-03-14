# Infrastructure Configuration

## Service Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         devenv services                          │
├──────────────┬──────────────┬──────────────┬───────────────────┤
│  PostgreSQL  │    MinIO     │    Qdrant    │   optillm/vLLM    │
│    :5444     │ :9010/:9011  │ :6339/:6340  │   :8080/:8088     │
├──────────────┼──────────────┼──────────────┼───────────────────┤
│ Admin DB     │ Object Store │ Vector DB    │ Local LLM         │
│ pg_cron      │ RAID storage │ Embeddings   │ Qwen3-Coder-30B   │
│ profiles     │ attachments  │ semantic     │ 6x RTX 4090       │
└──────────────┴──────────────┴──────────────┴───────────────────┘
```

## Port Allocations

| Service    | Port(s)       | Purpose                    |
|------------|---------------|----------------------------|
| PostgreSQL | 5444          | Admin DB (non-default)     |
| MinIO API  | 9010          | S3-compatible object store |
| MinIO Console | 9011       | Web UI                     |
| Qdrant HTTP | 6339         | REST API                   |
| Qdrant gRPC | 6340         | High-perf gRPC API         |
| optillm    | 8080          | Inference proxy            |
| vLLM       | 8088          | GPU inference backend      |

## Storage Paths

```
/raid/minio/gaius/     # MinIO object storage (RAID)
/raid/qdrant/gaius/    # Qdrant vector storage (RAID)
build/dev/             # KB markdown files (git-ignored)
.devenv/state/postgres # PostgreSQL data
```

## PostgreSQL Extensions

- **pg_cron**: Scheduled background tasks
  - Arxiv feed updates
  - News aggregation
  - Embedding refresh
  - KB maintenance

## Configuration (devenv.nix)

```nix
services.postgres = {
  enable = true;
  package = pkgs.postgresql_16;
  extensions = ext: [ ext.pg_cron ];
  port = 5444;
  settings = {
    shared_preload_libraries = "pg_cron";
    "cron.database_name" = "zndx_gaius";
  };
};

services.minio = {
  enable = true;
  buckets = ["zndx-gaius"];
  listenAddress = "127.0.0.1:9010";
  consoleAddress = "127.0.0.1:9011";
};

# Qdrant via custom process + env vars
env.QDRANT__STORAGE__STORAGE_PATH = "/raid/qdrant/gaius";
env.QDRANT__SERVICE__HTTP_PORT = "6339";
env.QDRANT__SERVICE__GRPC_PORT = "6340";
```
