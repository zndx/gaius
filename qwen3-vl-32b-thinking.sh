python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen3-VL-32B-Thinking \
  --max-model-len 32768 \
  --tensor-parallel-size 4 \
  --gpu-memory-utilization 0.9 \
  --swap-space 4 \
  --max-num-seqs 8 \
  --dtype auto \
  --host 0.0.0.0 \
  --port $OPENAI_API_PORT

# --rope-scaling "{\"factor\": 4.0,\"original_max_position_embeddings\": 32768,\"type\": \"yarn\"}"

