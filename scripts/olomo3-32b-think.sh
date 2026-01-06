# OLMo3-32B-Think: Optimized for full 64K context window
# Model specs: 32B params, 64 layers, 40 attention heads, GQA (8 KV heads)
# Max position embeddings: 65536 (native 64K context)
# Memory: ~64GB weights (BF16) + ~17GB KV cache per 64K sequence
# Constraints: TP must divide both heads (40) and vocab (100288)
# Valid TP sizes: 1, 2, 4, 8 (using 4 for balance)
# Config: TP=4, 4 GPUs, ~2.5GB headroom per GPU at full context
# Note: --enforce-eager skips CUDA graph compilation (15+ min startup otherwise)

python -m vllm.entrypoints.openai.api_server \
  --model allenai/Olmo-3-32B-Think \
  --max-model-len 65536 \
  --tensor-parallel-size 4 \
  --gpu-memory-utilization 0.95 \
  --swap-space 8 \
  --max-num-seqs 16 \
  --dtype bfloat16 \
  --disable-custom-all-reduce \
  --enforce-eager \
  --host 0.0.0.0 \
  --port $OPENAI_API_PORT
