# Guru Meditation Codes

Complete catalog of error codes used across the Gaius platform.

## Format

**`#<COMPONENT>.<SEQUENCE>.<MNEMONIC>`**

## Catalog

### DS — DatasetService

| Code | Description | Fix |
|------|-------------|-----|
| `#DS.00000001.SVCNOTINIT` | DatasetService not initialized | `/health fix dataset` |

### NF — NiFi

| Code | Description | Fix |
|------|-------------|-----|
| `#NF.00000001.UNREACHABLE` | NiFi not reachable | `/health fix nifi` |

### EN — Engine

| Code | Description | Fix |
|------|-------------|-----|
| `#EN.00001.GRPC_BIND` | gRPC port bind failure | Check port 50051 |
| `#EN.00002.VLLM_START` | vLLM startup failure | `/health fix endpoints` |
| `#EN.00003.GPU_OOM` | GPU out of memory | `just gpu-cleanup` |
| `#EN.00004.ORPHAN_PROC` | Orphan vLLM process | `just gpu-cleanup` |

### EP — Endpoints/Inference

| Code | Description | Fix |
|------|-------------|-----|
| `#EP.00000001.GPUOOM` | GPU out of memory during inference | `/health fix endpoints` |

### GR — gRPC

| Code | Description | Fix |
|------|-------------|-----|
| `#GR.00000001.CONNFAIL` | gRPC connection failed | Check engine status |

### ACP — Agent Client Protocol

| Code | Description | Fix |
|------|-------------|-----|
| `#ACP.00000001.CONNFAIL` | ACP connection failed | Check Claude Code |
| `#ACP.00000002.TIMEOUT` | ACP connection timeout | Retry |
| `#ACP.SEC.00000002.NOTALLOWED` | Repo not in allowlist | Update acp.conf |
| `#ACP.SEC.00000003.NOTPRIVATE` | Repo not private | Make repo private |

### ACF — Article Curation Flow

| Code | Description | Fix |
|------|-------------|-----|
| `#ACF.00000013.NOHINTS` | Empty keywords in article frontmatter | Add keywords/news_queries |

### XB — X Bookmarks

| Code | Description | Fix |
|------|-------------|-----|
| `#XB.00000001.NOTOKEN` | No auth token | Complete OAuth flow |
| `#XB.00000011.NOFOLDER` | Folders API unavailable (403) | Upgrade API tier |

### HL — Health

| Code | Description | Fix |
|------|-------------|-----|
| `#HL.00001.GRPC_DOWN` | gRPC connection down | `just restart-clean` |
| `#HL.00002.GPU_OOM` | GPU memory exhausted | `just gpu-cleanup` |

> **Note**: This is a representative subset. Guru codes are assigned as new failure modes are identified. See `CLAUDE.md` for the full format specification.
