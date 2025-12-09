# optillm + vLLM Validation

## Test Script Created

`scripts/test_optillm_vllm.py` - validates the full integration.

## Available Models (in ~/.cache/huggingface/hub/)

- `Qwen/Qwen2.5-Coder-32B-Instruct` - 32B, needs tensor parallel
- `Qwen/Qwen2.5-Coder-32B` - base model
- `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B` - reasoning distilled

## Quick Start

```bash
# Terminal 1: Start vLLM
vllm serve Qwen/Qwen2.5-Coder-32B-Instruct \
  --tensor-parallel-size 4 \
  --max-model-len 8192 \
  --port 8000

# Terminal 2: Start optillm
pip install optillm
export OPENAI_API_KEY="sk-dummy"
export OPTILLM_BASE_URL="http://localhost:8000/v1"
optillm --port 8080

# Terminal 3: Run test
uv run python scripts/test_optillm_vllm.py
```

## Techniques to Test

- `cot_reflection` - Chain-of-Thought with Reflection
- `bon` - Best of N
- `moa` - Mixture of Agents (needs more GPU memory)
- `mcts` - Monte Carlo Tree Search
- `plansearch` - Plan-based search

## Dependencies Added

```toml
[project.optional-dependencies]
inference = [
    "openai>=1.0.0",
    "httpx>=0.25.0",
]
```

Install: `uv sync --extra inference`
