# /dev/shm reclaim so thinking stays up

63G tmpfs was 100% full. Not sibling units — eight leftover
`vllm_offload_*.mmap` (8 GiB each) from `--kv-offloading-size 8`
after unclean vLLM stops, plus unheld `psm_*` rings.

## Now

- Unheld offload/psm unlinked. `/dev/shm` 8.1G used / 55G free
  (the live thinking mmap).
- thinking HEALTHY on `:8081`. Complete returned `pong`.
- Reclaim is durable: `gpu_cleanup` / `/health fix endpoints` /
  `require_shm_for_offload` before each vLLM start.
  Guru `#EP.00000007.SHMFULL`.
- Never touch PostgreSQL*, `gaius-aeron`, or mapped files.

MCP child bounced (`2236792` → `3275828`). This grok turn still
lists the pre-bounce tool catalog; a new Terminal grok (or the
next session handshake) sees `gaius__agenda_*`.
