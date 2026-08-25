# Restart: 10 Hz strip + Kumo after empty landing

`sudo systemctl restart gaius.service` at 03:12Z. Engine/UI/thinking recycled. Signals target left up (Kudu ingest survived).

## Why the landing went blank

1. **DCGM `:9400` died.** `federation-system/dcgm-exporter` evicted under kubelet `DiskPressure` (`nodefs.available<10Gi`; `/` was 7–14 GiB free, 100% used). HardwareDriver then `present=False` → packed 0 → black 10 Hz gpu-n. Kumo `_record_hardware` stopped, so watts histograms went empty.
2. **Thinking was `STARTING` then rebound `:8080`.** `VllmDriver` still scraped `:8081`, so kv/run/gen-tps stayed absent. Controller now writes `GAIUS_THINKING_PORT` / `GAIUS_VLLM_METRICS_URL` (needs the *next* engine process to take effect).
3. **Idle paint.** `clip01(signed_power)` zeros occupancy below `_IDLE_W`. JS now maps signed power to `[0,1]` occupancy. Cache-bust `discover.js?v=0.3.25-idle-occ`.
4. **Kumo hist bars were salience-only.** With salience 0 and watts ~450, bars looked empty. Bars now fall back to watts.

## After restart (03:27Z)

- `thinking` **HEALTHY** on `:8080` (2 in-flight, ~110–127 W on GPUs 0–3).
- `SIGNALS_WAREHOUSE_DSN=postgresql://signals@127.0.0.1:5455/signals` on the engine. 1h waterfall `driver=warehouse`, 23k nonzero.
- 60s gpu-n last packed `1.24–2.00`, util transients live. Discover last bucket watts ~447, util ~83%, `watts_live=true` (473 W).
- Host `:9400` is an nvidia-smi scrape in DCGM names while the DaemonSet stays evicted. Replace with `dcgm-exporter` once disk is above 10 GiB.

## Not done

- Engine still has the pre-reload `VllmDriver` (`:8081`). kv/run/gen-tps on the 10 Hz strip stay 0 until gaius-engine recycles *without* needing another full `gaius.service` if process-compose can restart just the engine (that will bounce thinking).
- Root disk still ~100%. Do not `systemctl restart signals.target` until nodefs > 10 GiB or DCGM will evict again.
