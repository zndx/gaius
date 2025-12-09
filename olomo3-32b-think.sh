python -m vllm.entrypoints.openai.api_server \
  --model allenai/Olmo-3-32B-Think \
  --max-model-len 32768 \
  --tensor-parallel-size 2 \
  --gpu-memory-utilization 0.9 \
  --swap-space 4 \
  --max-num-seqs 128 \
  --dtype auto \
  --host 0.0.0.0 \
  --port $OPENAI_API_PORT

# --rope-scaling "{\"factor\": 4.0,\"original_max_position_embeddings\": 32768,\"type\": \"yarn\"}"

