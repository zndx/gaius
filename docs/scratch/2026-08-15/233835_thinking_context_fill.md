# Thinking 262k context fill (2026-08-15)

vLLM `cache_config_info`: `kv_cache_size_tokens=437419`, `num_gpu_blocks=569`,
`block_size=784`, `kv_cache_max_concurrency=1.67` at `max_model_len=262144`.
`--kv-offloading-size 8` reserved; offload byte counters stayed 0.

Needle-in-haystack (HEAD/TAIL unique codes) against `:8081`, thinking **off**
for the large fills so decode did not eat the window.

| User tokens | prompt_tokens | HTTP | needles | latency |
|------------:|--------------:|:----:|:-------:|--------:|
| 4k unique | 4010 | 200 | yes | 6.6s |
| 32k unique | 32010 | 200 | yes | 31.6s |
| 64k unique | 64011 | 200 | yes | 37.3s |
| 128k repeat-pad | 128011 | 200 | yes | 142.5s |
| 200k repeat-pad | 200011 | 200 | yes | 90.6s |
| 250k repeat-pad | 250011 | 200 | yes | 67.2s |
| 261k repeat-pad | 261011 | 200 | yes | 18.6s |

261k used ~64% of GPU KV (261k/437k). Endpoint still HEALTHY after.
Later fills got faster because `--enable-prefix-caching` + a repeating pad;
the first 128k paid the real prefill (~143s, eager). Not a unique-document
262k NIAH. Thinking-on at 250k+ not run (trace would compete with prefill).
One request at a time at this length (`max_concurrency≈1.67`).
