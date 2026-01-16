# Testing Guidelines

This document captures the testing philosophy and criteria for the Gaius test suite.

## Core Principle: Real Services Over Mocks

**Only mock services or capabilities that cannot be made available in CI workflows.**

The goal is to test against real infrastructure whenever possible. Mocking should be
the exception, not the rule. Real service tests catch integration issues that mocks
hide.

## Service Availability Matrix

| Service | CI Available | Local (devenv) | Mocking Strategy |
|---------|--------------|----------------|------------------|
| PostgreSQL | ✅ Yes | ✅ Yes | Never mock - use real database |
| Qdrant | ✅ Yes | ✅ Yes | Never mock - use real vector store |
| MinIO | ✅ Yes | ✅ Yes | Never mock - use real S3-compatible storage |
| gRPC Engine | ✅ Yes | ✅ Yes | Never mock - start real engine |
| LLM Inference | ✅ Yes | ✅ Yes | Use llama.cpp with tiny models (see below) |
| GPUs (nvidia-smi) | ❌ No | ✅ Yes | Model as integers, mock pynvml |
| NiFi | ⚠️ Heavy | ✅ Yes | Use testcontainers or skip |
| Selenium/Chrome | ⚠️ Heavy | ✅ Yes | Use testcontainers or skip |

### Legend
- ✅ Yes: Service is trivially available via devenv/containers
- ❌ No: Hardware dependency, cannot be provided in CI
- ⚠️ Heavy: Possible but resource-intensive; consider skip markers

### LLM Inference in CI

**LLM inference IS available in GitHub Actions** via llama.cpp CPU inference. The llama.cpp
project itself runs inference tests on GitHub's 4 vCPU runners using tiny models.

**Recommended approach:**
- Use [llama.cpp](https://github.com/ggml-org/llama.cpp) for CPU-based inference
- Use tiny models like `tinyllamas/stories260K.gguf` (~260KB) for fast CI tests
- Quality is not the goal - testing the inference pipeline is

**Reference:** llama.cpp's own [server tests](https://github.com/ggml-org/llama.cpp/tree/master/tools/server/tests)
run actual inference on GitHub runners, proving this approach works.

**Key insight:** When testing inference integration, we care that:
1. Requests are properly formatted and routed
2. Responses are correctly parsed and processed
3. Metrics are recorded accurately
4. Error handling works

We do NOT need production-quality model outputs for these tests.

## Test Categories

### 1. Pure Algorithmic Tests (No Services)

Tests that exercise logic without any service dependencies. These are the most
valuable tests - fast, deterministic, and test the actual algorithms.

**Examples:**
- `tests/engine/test_makespan_scheduler.py` - CP-SAT solver logic (GPUs as integers)
- `tests/engine/test_reconciliation_fsm.py` - State machine transitions
- `tests/engine/test_allocations.py` - Allocation state and process tracking
- `tests/engine/test_scheduler_types.py` - Priority queue, budget management

**Guidelines:**
- Model hardware resources as integers/enums, not actual hardware
- Test state transitions, not I/O operations
- Use `@dataclass` objects as pure data, test their methods
- No mocking needed - these are pure functions

### 2. Database Integration Tests

Tests that require PostgreSQL. Use the real database via devenv.

**Setup:**
```python
import pytest
from gaius.workers.db import get_db_pool

@pytest.fixture
async def db_pool():
    """Get real database connection pool."""
    pool = await get_db_pool()
    yield pool
    await pool.close()
```

**Guidelines:**
- Use transactions and rollback for test isolation
- Run `dbmate up` before test suite (in CI setup)
- Never mock database queries

### 3. gRPC Engine Tests

Tests that require the Gaius engine running. Start the real engine.

**Setup:**
```python
import pytest
from gaius.client.grpc_client import GaiusClient

@pytest.fixture
async def engine_client():
    """Connect to running engine."""
    client = GaiusClient()
    await client.connect()
    yield client
    await client.close()
```

**Guidelines:**
- Ensure engine is running before tests (`devenv processes up`)
- Test actual gRPC request/response cycles
- Use `pytest.mark.engine` for tests requiring engine

### 4. Inference Integration Tests

Tests involving LLM inference use real inference via llama.cpp on CPU.

**CI Model Registry:**

The model registry includes CI test models that map to production model families:

```python
from gaius.models import get_ci_model, CI_QWEN_TINY

# Get CI equivalent for a production model
ci_model = get_ci_model("Qwen/QwQ-32B")  # Returns CI_QWEN_TINY

# Or use directly
print(ci_model.llamacpp_config.download_command())
# huggingface-cli download Qwen/Qwen2.5-0.5B-Instruct-GGUF qwen2.5-0.5b-instruct-q4_k_m.gguf --local-dir ./models

print(ci_model.llamacpp_config.serve_command("./models"))
# llama-server -m ./models/qwen2.5-0.5b-instruct-q4_k_m.gguf --port 8080 -c 512 -n 64 -t 4
```

| Production Model | CI Equivalent | Family | Size |
|------------------|---------------|--------|------|
| Qwen/QwQ-32B | CI_QWEN_TINY | Qwen2.5-0.5B | ~400MB |
| Qwen/Qwen3-8B | CI_QWEN_TINY | Qwen2.5-0.5B | ~400MB |
| allenai/Olmo-3-32B-Think | CI_OLMO_TINY | OLMo-2-1B | ~600MB |
| zai-org/GLM-4.6V-Flash | CI_GLM_SMALL | glm-edge-4b | ~2.5GB |
| mistralai/Mistral-7B | CI_MISTRAL_TINY | Mistral-7B Q2_K | ~2.5GB |

**Setup for CI:**
```python
import pytest
import subprocess
import time
from gaius.models import get_ci_model, CI_QWEN_TINY

@pytest.fixture(scope="session")
def llama_server(tmp_path_factory):
    """Start llama.cpp server with CI model for testing."""
    model = CI_QWEN_TINY
    cfg = model.llamacpp_config
    model_dir = tmp_path_factory.mktemp("models")

    # Download model
    subprocess.run(cfg.download_command(str(model_dir)).split(), check=True)

    # Start server
    cmd = cfg.serve_command(str(model_dir)).split()
    proc = subprocess.Popen(cmd)
    time.sleep(3)  # Wait for startup

    yield f"http://localhost:{cfg.port}"
    proc.terminate()
```

**What to test with real inference:**
- Request routing and formatting
- Response parsing and validation
- Token counting and metrics
- Error handling (timeouts, malformed responses)
- Queue management under load

**What still needs mocking:**
- `pynvml` calls - GPU memory/utilization readings (hardware-specific)
- GPU allocation state - Model as integers

**Guidelines:**
- Use CI models from the registry (same message format as production)
- Set short timeouts and small context sizes for speed
- Focus on pipeline correctness, not output quality

## Markers

Use pytest markers to categorize tests by their dependencies:

```python
# pyproject.toml
[tool.pytest.ini_options]
markers = [
    "engine: tests requiring gRPC engine",
    "gpu: tests requiring GPU hardware",
    "nifi: tests requiring NiFi",
    "slow: tests taking > 10 seconds",
]
```

**Usage:**
```python
@pytest.mark.engine
async def test_scheduler_submit():
    """Test requires running engine."""
    ...

@pytest.mark.gpu
def test_vllm_endpoint_health():
    """Test requires GPU hardware."""
    ...
```

**Running subsets:**
```bash
# Run only pure algorithmic tests (fast, no services)
uv run pytest tests/engine/ -m "not engine and not gpu"

# Run with engine (requires devenv processes up)
uv run pytest -m engine

# Skip GPU tests in CI
uv run pytest -m "not gpu"
```

## CI Configuration

Recommended GitHub Actions setup:

```yaml
# .github/workflows/test.yml
services:
  postgres:
    image: postgres:16
    env:
      POSTGRES_DB: zndx_gaius
      POSTGRES_PASSWORD: postgres
    ports:
      - 5438:5432

  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - 6339:6333

steps:
  - name: Install llama.cpp
    run: |
      # Build llama.cpp for CPU inference testing
      git clone https://github.com/ggml-org/llama.cpp.git
      cd llama.cpp && cmake -B build && cmake --build build -t llama-server
      echo "$PWD/build/bin" >> $GITHUB_PATH

  - name: Download tiny test model
    run: |
      huggingface-cli download ggml-org/tinyllamas stories260K.gguf \
        --local-dir ./models

  - name: Run migrations
    run: dbmate up

  - name: Start engine
    run: |
      uv run python -m gaius.engine.server &
      sleep 10  # Wait for startup

  - name: Run tests
    run: uv run pytest -m "not gpu" --cov
```

**Note:** The `gpu` marker is now only for tests that require actual GPU hardware
(nvidia-smi, pynvml). Inference tests run on CPU via llama.cpp.

## Anti-Patterns

### ❌ DON'T: Mock what you can run

```python
# BAD: Mocking postgres when it's available
@patch('gaius.workers.db.get_db_pool')
def test_activity_logging(mock_pool):
    mock_pool.return_value.fetchrow.return_value = {...}
```

### ✅ DO: Use real services

```python
# GOOD: Real database connection
async def test_activity_logging(db_pool):
    await log_activity(db_pool, event_type="test")
    row = await db_pool.fetchrow("SELECT * FROM activity_log LIMIT 1")
    assert row["event_type"] == "test"
```

### ❌ DON'T: Test fallbacks for hard requirements

```python
# BAD: Testing what happens when OR-Tools is missing
def test_ortools_missing():
    with patch('ortools.sat.python.cp_model', None):
        # This violates fail-fast
```

### ✅ DO: Skip if requirement unavailable

```python
# GOOD: Skip entire module if requirement missing
pytestmark = pytest.mark.skipif(
    not ORTOOLS_AVAILABLE,
    reason="OR-Tools not installed (uv sync --extra scheduler)"
)
```

## Coverage Goals

| Module Category | Target | Rationale |
|-----------------|--------|-----------|
| Pure algorithmic (scheduling, FSM) | 95%+ | Critical path, fully testable |
| Dataclasses and types | 100% | Simple, no dependencies |
| Service methods (sync) | 80%+ | Test with real services |
| Service methods (async I/O) | 60%+ | May need integration tests |
| Error paths | 70%+ | Test failure modes explicitly |

## File Organization

```
tests/
├── README.md              # This file
├── conftest.py            # Shared fixtures
├── engine/                # Engine component tests
│   ├── test_allocations.py
│   ├── test_reconciliation_fsm.py
│   ├── test_scheduler_types.py
│   ├── test_makespan_scheduler.py
│   └── test_scheduling_types.py
├── agents/                # Agent logic tests
├── acp/                   # ACP security tests
└── widgets/               # TUI widget tests
```

## Running Tests

```bash
# All tests (requires devenv processes)
uv run pytest

# Fast tests only (pure algorithmic)
uv run pytest tests/engine/ -m "not engine and not gpu"

# With coverage
uv run pytest --cov=gaius --cov-report=term-missing

# Specific module
uv run pytest tests/engine/test_allocations.py -v

# Watch mode during development
uv run pytest-watch tests/engine/
```
