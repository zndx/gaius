# Devstral-Small-2-24B-Instruct: Long-context instruct model
# Model specs: 24B params, 40 layers, 32 attention heads, GQA (8 KV heads)
# Max position embeddings: 393216 (384K native via YaRN RoPE)
# Quantization: FP8 (~24GB weights vs 48GB for BF16)
# Multimodal: Has Pixtral vision encoder (but can be used text-only)
# Valid TP sizes: 1, 2, 4, 8 (32 heads, 131072 vocab - all divide evenly)
#
# Memory analysis (TP=4):
#   - ~6GB weights per GPU (24GB FP8 / 4)
#   - Available KV cache memory: 14.57 GiB per GPU
#   - GPU KV cache size: 381,888 tokens (~373K max achievable)
#   - 256K context fits easily with headroom
#
# Usage: Capability-based scheduler evicts other endpoints when 'instruct' needed
# Config: TP=4, 256K context, optimal for multi-turn instruction following
# Note: --enforce-eager skips CUDA graph compilation for fast startup

python -m vllm.entrypoints.openai.api_server \
  --model mistralai/Devstral-Small-2-24B-Instruct-2512 \
  --max-model-len 262144 \
  --tensor-parallel-size 4 \
  --gpu-memory-utilization 0.95 \
  --swap-space 8 \
  --max-num-seqs 32 \
  --dtype auto \
  --disable-custom-all-reduce \
  --enforce-eager \
  --host 0.0.0.0 \
  --port $OPENAI_API_PORT
