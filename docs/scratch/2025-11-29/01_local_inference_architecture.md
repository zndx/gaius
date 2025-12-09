# Local Inference Architecture Brainstorm

## Hardware Context

6x NVIDIA RTX 4090 (24GB each = 144GB total VRAM)

Potential GPU allocation strategies:

```
Strategy A: Tensor Parallel Large Model
┌─────────────────────────────────────────┐
│ GPUs 0-3: Qwen2.5-72B (tensor parallel) │
│ GPUs 4-5: Embeddings + small fast model │
└─────────────────────────────────────────┘

Strategy B: Multi-Model Concurrent
┌─────────────────────────────────────────┐
│ GPUs 0-1: Architect (Qwen2.5-32B)       │
│ GPUs 2-3: Coder (DeepSeek-Coder-33B)    │
│ GPU 4: Embeddings (nomic-embed-text)    │
│ GPU 5: Fast model (Qwen2.5-7B critic)   │
└─────────────────────────────────────────┘

Strategy C: optillm Mixture of Agents
┌─────────────────────────────────────────┐
│ GPUs 0-1: Model A (Qwen2.5-32B)         │
│ GPUs 2-3: Model B (DeepSeek-33B)        │
│ GPUs 4-5: Model C (Mistral-22B)         │
│ optillm aggregates outputs              │
└─────────────────────────────────────────┘
```

## Software Stack

### Current Experience
- **vLLM**: Daily driver, production-ready, good TP support
- **llama.cpp**: Laptop inference, efficient quantization
- **PyTorch Lightning + FSDP**: Training/fine-tuning
- **mergekit**: Model merging experiments
- **Kserve**: Production serving at work

### To Explore
- **optillm**: Inference optimization layer (MoA, BoN, speculative decoding)
- **LiteLLM**: Unified API across providers
- **Brave API**: Agentic search for KB population

## optillm Integration Points

optillm provides optimization techniques that sit between client and LLM:

1. **Mixture of Agents (MoA)** - Multiple models propose, one aggregates
2. **Best of N** - Sample N completions, select best
3. **Speculative Decoding** - Draft model + verify with large model
4. **Chain of Thought** - Automatic reasoning enhancement
5. **Memory/Context** - Sliding window, compression

### Potential Contribution Ideas

1. **Visual debugging dashboard** - Gaius TUI showing MoA voting, token flows
2. **Spatial optimization selection** - Use grid position to select optimization strategy
3. **Embedding-guided routing** - Route queries based on semantic similarity to model strengths
4. **Benchmark harness** - Compare optimization strategies on same prompts

## Architecture Proposal

```
┌──────────────────────────────────────────────────────────────────┐
│                           Gaius TUI                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────────┐│
│  │ MainGrid │ │ LinkGraph│ │ FileTree │ │    ContentPanel      ││
│  │  19×19   │ │          │ │ /agents/ │ │  (streaming output)  ││
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────────┬───────────┘│
└───────┼────────────┼────────────┼───────────────────┼────────────┘
        │            │            │                   │
        └────────────┴────────────┴───────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │   gaius.inference │
                    │   (router layer)  │
                    └─────────┬─────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
       ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
       │   optillm   │ │  LiteLLM    │ │   Direct    │
       │   (local)   │ │  (unified)  │ │   (Brave)   │
       └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
              │               │               │
              ▼               ▼               ▼
       ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
       │    vLLM     │ │ Remote APIs │ │  Brave API  │
       │  (6x4090)   │ │ (fallback)  │ │  (search)   │
       └─────────────┘ └─────────────┘ └─────────────┘
```

## Workflow Modes

### 1. Offline Mode (default)
- All inference local via vLLM
- Embeddings local
- Brave search disabled
- optillm optimizations active

### 2. Hybrid Mode
- Local-first with remote fallback
- Brave search for KB population
- Claude/GPT for frontier tasks only

### 3. Research Mode
- Multiple optimization strategies compared
- Logging/metrics for analysis
- A/B testing different approaches

## Integration with Gaius Concepts

### Grid as Optimization Space
- X-axis: speed ←→ quality
- Y-axis: cost ←→ capability
- Each position maps to an optimization config
- "Tenuki" = jump to optimal strategy for current task

### Agents as Files
```
/agents/
├── architect     # Planning, decomposition (optillm: cot_reflection)
├── coder         # Code generation (optillm: best_of_n)
├── critic        # Review, validation (optillm: pvg)
├── researcher    # Brave search + synthesis
└── embedder      # Always local, powers grid
```

### Slash Commands
```
/ask <query>      # Route to best available model
/plan <task>      # Architect agent with CoT
/code <spec>      # Coder agent with BoN
/search <query>   # Brave API → KB
/offline          # Toggle offline mode
/compare          # Run same prompt through multiple strategies
```

## Next Steps

1. [ ] Set up optillm locally, connect to vLLM backend
2. [ ] Create `src/gaius/inference/` module with router
3. [ ] Add Brave API integration for search
4. [ ] Implement `/ask` command as proof of concept
5. [ ] Design metrics/logging for optimization comparison
6. [ ] Identify contribution opportunity for optillm project

## Open Questions

- Best way to manage multiple vLLM instances? (supervisor, systemd, k8s?)
- optillm as proxy vs library integration?
- How to surface optimization choices to user without overwhelming?
- What would be genuinely useful contribution to optillm?
