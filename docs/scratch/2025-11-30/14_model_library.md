# Model Library Implementation

Built a comprehensive model library for agent-task-specific local inference with frontier model evaluation and Pareto-based optimization.

## Components Created

### 1. Model Registry (`models/registry.py`)
- **ModelSpec** dataclass with capabilities, task scores, and metadata
- **ModelCapability** enum: CHAT, REASONING, CODING, ORCHESTRATION, TEXT_EMBEDDING, VISION_EMBEDDING, etc.
- **TaskType** enum: REASONING, CODING, ORCHESTRATION, TEXT_EMBEDDING, VISION_EMBEDDING, SWARM_LEADER, etc.
- Pre-registered models:
  - **Qwen/QwQ-32B** - Primary reasoning model (chain-of-thought, analysis)
  - **Qwen/Qwen3-Coder-30B-A3B-Instruct** - Coding tasks
  - **nvidia/Orchestrator-8B** - Agent routing/planning
  - **nomic-ai/nomic-embed-text-v1** - Text embeddings (768-dim)
  - **nomic-ai/nomic-embed-vision-v1** - Vision embeddings (same 768-dim space!)
  - **grok-2-latest** - Frontier evaluation
  - **gpt-4o-mini** - Cost-effective evaluation

### 2. Nomic Embeddings (`models/embeddings.py`)
- **NomicEmbeddings** class with unified text+vision embedding
- Both models produce 768-dimensional vectors in the **same embedding space**
- Enables cross-modal retrieval (text-to-image, image-to-text)
- Methods: `embed_text()`, `embed_texts()`, `embed_image()`, `embed_images()`
- Uses sentence-transformers or raw transformers fallback
- Lazy model loading from HuggingFace Hub

### 3. xAI Evaluation (`models/evaluation.py`)
- **XAIEvaluator** using Grok-2 for frontier model assessment
- **EvaluationDimension** enum: ACCURACY, COHERENCE, RELEVANCE, COMPLETENESS, CLARITY, ACTIONABILITY, CREATIVITY, SAFETY
- **DimensionScore** and **EvaluationResult** dataclasses
- JSON response parsing with structured feedback
- Batch evaluation support

### 4. Agent Versioning (`models/versioning.py`)
- **AgentConfig** dataclass for agent configuration
- **AgentVersion** dataclass with metrics tracking (avg_score, best_score, eval_count)
- **VersionManager** class with PostgreSQL persistence
- Methods:
  - `save_version()` - Save new version with metrics
  - `get_active_version()` - Get current active config
  - `get_best_version()` - Get highest-performing version
  - `set_active_version()` - Rollback to previous version
  - `update_metrics()` - Update running averages after evaluation

### 5. Pareto Optimization (`models/optimization.py`)
- **OptimizationStrategy** enum: APO, GEPA, HYBRID
- **OptimizationObjective** enum: ACCURACY, COHERENCE, RELEVANCE, EFFICIENCY, CREATIVITY, SAFETY, CONSISTENCY
- Pareto utilities:
  - `is_dominated()` - Check if solution a is dominated by b
  - `compute_pareto_front()` - Get non-dominated solutions
  - `compute_pareto_ranks()` - Non-dominated sorting
  - `crowding_distance()` - Diversity preservation metric
- **AgentOptimizer** class:
  - APO (Automatic Prompt Optimization) - Mutation-based
  - GEPA (Gradient-free Efficient Pareto Agent) - Bootstrap-based
  - Local model evaluation + optional frontier calibration
- **ScheduledOptimizer** for periodic optimization runs

## Database Migration

Created `db/migrations/20251130000006_agent_versions.sql`:
- `agent_versions` table with config, metrics, parent chain
- `agent_evaluations` table for detailed evaluation history
- `optimization_runs` table for tracking GEPA/APO experiments
- Views: `active_agent_configs`, `agent_version_history`, `best_agent_versions`
- Unique constraint ensuring single active version per agent

## Test Suite

Created `tests/test_models.py` with 25 tests:
- Model registry and task routing
- Pareto optimization (domination, front computation, ranks, crowding distance)
- Agent versioning serialization
- Evaluation result structures
- Embedding result structures

All 25 tests passing.

## Key Design Decisions

1. **Unified Embedding Space**: Nomic text and vision models share the same 768-dim space, enabling cross-modal retrieval without separate indexes.

2. **GEPA over DSPy**: Chose Pareto-based GEPA optimization over DSPy's prescriptive approach to maintain flexibility in agent architecture.

3. **Version Control with Rollback**: Agent configs are versioned with performance tracking, enabling rollback to previously high-performing versions.

4. **Multi-Objective Optimization**: Pareto front preserves trade-offs between objectives (accuracy vs efficiency, creativity vs safety).

5. **HuggingFace Cache**: Using standard ~/.cache/huggingface/ for model weights rather than bundling in project.

## Usage Examples

```python
# Get model for task
from gaius.models import get_model_for_task, TaskType
model = get_model_for_task(TaskType.REASONING)

# Evaluate output
from gaius.models import evaluate_output, EvaluationDimension
result = await evaluate_output(
    agent_output="...",
    task_prompt="...",
    dimensions=[EvaluationDimension.ACCURACY, EvaluationDimension.COHERENCE],
)

# Version management
from gaius.models import get_version_manager, AgentConfig
manager = get_version_manager()
best = await manager.get_best_version("leader", metric="accuracy")
await manager.set_active_version("leader", best.version_id)

# Optimization
from gaius.models import optimize_agent, OptimizationStrategy, TaskExample
result = await optimize_agent(
    agent_id="leader",
    task_examples=[TaskExample(input_prompt="...", expected_output="...")],
    strategy=OptimizationStrategy.GEPA,
)
```
