# Host floors on the extract envelope

Signals YK shows continuous occupancy: one Running extract Application,
`federation.zndx.org/gpu=1` of parent 6, 16Mi / 10m. That row is the
evidence the survey lane is reserved.

YK cannot cap host disk or RAM. Observed 2026-08-15 (`dust` / `df` /
`/proc/meminfo`):

- `/` 916G, 36G free (96%) — Gaius KB+PG+local Metaflow is ~400M
- `/raid` 3.6T, 208G free (95%)
- MemAvailable ~82Gi of 128Gi
- all six 4090s already near-full with sibling engines

Floors in `assert_host_envelope`: `/` 32Gi, `/raid` 64Gi, RAM 8Gi.
Crossing them is `#YK.00000005.DISK` / `#YK.00000006.MEM`. The
Application stays (dashboard still shows the token); the host child
does not start. Ambient (`internal.compute`) skips the disk floor.
