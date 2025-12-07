"""Gaius MCP Server.

Exposes full Gaius capabilities to Claude Code and other MCP clients:

**KB Operations**
- search_kb, read_kb, create_kb, update_kb, delete_kb, list_kb

**Inference**
- ask_local: Query local LLM via optillm
- ask_reasoning: Query reasoning model (QwQ-32B)

**Search**
- web_search: Brave API search
- research_topic: Search + synthesize to KB
- semantic_search: Vector similarity search

**Model Library**
- list_models: List available models
- get_model: Get model for specific task

**Embeddings**
- embed_text: Generate text embedding
- embed_texts: Batch text embeddings

**Evaluation**
- evaluate_output: Frontier model (xAI) evaluation

**Agent Versioning**
- list_agent_versions: Version history
- get_active_config: Current agent config
- rollback_agent: Rollback to previous version
- save_agent_version: Save new version

**Optimization**
- optimize_agent: Run APO/GEPA optimization

**Activity & Summary**
- log_activity: Record activity event
- get_daily_summary: Generate/retrieve daily summary
- get_activity_stats: Activity statistics

**Swarm**
- run_swarm: Execute swarm analysis

**Development**
- reload_modules: Hot-reload Python modules without restart

Usage:
    # Start the server
    uv run gaius-mcp

    # Configure in Claude Code's .mcp.json:
    {
      "mcpServers": {
        "gaius": {
          "command": "uv",
          "args": ["run", "gaius-mcp"],
          "env": {
            "BRAVE_API_KEY": "...",
            "XAI_API_KEY": "..."
          }
        }
      }
    }
"""

import json
import os
from datetime import datetime
from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    FastMCP = None

# KB root (relative to cwd or absolute)
KB_ROOT = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
ALLOWED_DIRS = ("archive", "current", "scratch")

# Engine proxy cache (gRPC client)
_engine_client = None
_engine_connected = False

# Module-level geometry cache for MCP context
_mcp_curvatures: list[float] | None = None
_mcp_tda_features = None  # TDAFeatures | None


async def _get_engine_client():
    """Get gRPC engine client if available.

    Uses the gRPC client by default for production use.
    Set GAIUS_DISABLE_ENGINE=true to skip engine connection.

    Returns None if engine not available.
    """
    global _engine_client, _engine_connected

    # Allow disabling engine connection
    if os.environ.get("GAIUS_DISABLE_ENGINE", "").lower() == "true":
        return None

    if _engine_client is not None:
        return _engine_client if _engine_connected else None

    try:
        from .client.grpc_client import GrpcEngineClient

        _engine_client = GrpcEngineClient()
        _engine_connected = await _engine_client.connect()

        if _engine_connected:
            return _engine_client
        else:
            return None
    except Exception:
        return None


async def _ensure_geometry_computed() -> tuple[list[float] | None, object]:
    """Lazily compute and cache TDA/geometry features for MCP context.

    Returns:
        (curvatures, tda_features) tuple
    """
    global _mcp_curvatures, _mcp_tda_features

    # Return cached if available
    if _mcp_curvatures is not None or _mcp_tda_features is not None:
        return _mcp_curvatures, _mcp_tda_features

    try:
        import asyncio
        import concurrent.futures
        import numpy as np
        from .core.projection import get_grid_manager
        from .core.geometry import GeometryComputer
        from .core.tda import get_tda_manager

        grid_data = get_grid_manager().get_grid_data()

        if grid_data.raw_embeddings is None or len(grid_data.raw_embeddings) < 15:
            return None, None

        # Compute TDA features (for h0/h1/h2 counts, entropy)
        tda_manager = get_tda_manager()
        grid_coords = np.array([(p.x, p.y) for p in grid_data.points])
        _mcp_tda_features = tda_manager.compute_features(
            grid_data.raw_embeddings, grid_coords
        )

        # Compute geometry features (for actual Ricci curvatures)
        gc = GeometryComputer(k_neighbors=min(15, len(grid_data.raw_embeddings) - 1))

        # Run geometry in thread pool to avoid blocking event loop
        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            geom_features = await loop.run_in_executor(
                pool,
                lambda: asyncio.run(gc.compute_features(grid_data.raw_embeddings, grid_coords))
            )

        if geom_features is not None:
            _mcp_curvatures = [float(k) for k in geom_features.curvatures]

        return _mcp_curvatures, _mcp_tda_features

    except Exception as e:
        import sys
        print(f"Geometry computation error: {e}", file=sys.stderr)
        return None, None


def ensure_mcp():
    """Raise helpful error if MCP not installed."""
    if not MCP_AVAILABLE:
        raise ImportError("mcp package required. Install with: uv sync --extra mcp")


def get_kb_root() -> Path:
    """Get the KB root directory."""
    root = KB_ROOT
    if not root.is_absolute():
        root = Path.cwd() / root
    return root


def validate_kb_path(path: str) -> Path:
    """Validate that a path is within the allowed KB structure.

    Args:
        path: Relative path like "current/topics/kudu.md"

    Returns:
        Absolute path to the file

    Raises:
        ValueError: If path is outside allowed directories
    """
    kb_root = get_kb_root()

    # Handle both relative and absolute paths
    p = Path(path)
    if p.is_absolute():
        # Check if it's under kb_root
        try:
            p.relative_to(kb_root)
            full_path = p
        except ValueError:
            raise ValueError(f"Path {path} is outside KB root {kb_root}")
    else:
        full_path = kb_root / p

    # Ensure the path is in an allowed directory
    parts = full_path.relative_to(kb_root).parts
    if not parts or parts[0] not in ALLOWED_DIRS:
        raise ValueError(
            f"Path must be under one of: {', '.join(ALLOWED_DIRS)}. Got: {path}"
        )

    return full_path


def create_server() -> "FastMCP":
    """Create and configure the MCP server."""
    ensure_mcp()

    server = FastMCP("gaius")

    # --- KB Operations (via storage abstraction) ---

    @server.tool()
    async def search_kb(query: str, max_results: int = 10) -> str:
        """Search the Gaius knowledge base.

        Searches file names and content for the query string.

        Args:
            query: Search query
            max_results: Maximum number of results to return
        """
        from .storage.kb_ops import search_kb as _search_kb

        results = await _search_kb(query, max_results)
        return json.dumps({
            "results": [
                {"path": r.path, "match": r.match_type, "preview": r.preview}
                for r in results
            ],
            "total": len(results),
        }, indent=2)

    @server.tool()
    async def read_kb(path: str) -> str:
        """Read a KB entry by path.

        Args:
            path: Relative path like "current/topics/kudu.md"
        """
        from .storage.kb_ops import read_kb as _read_kb

        entry = await _read_kb(path)
        if entry is None:
            return json.dumps({"error": f"File not found: {path}"})

        return json.dumps({
            "path": entry.path,
            "content": entry.content,
            "size": entry.size,
            "modified": entry.modified,
        }, indent=2)

    @server.tool()
    async def create_kb(path: str, content: str) -> str:
        """Create a new KB entry.

        Args:
            path: Relative path like "current/topics/new_topic.md"
            content: Markdown content for the entry
        """
        from .storage.kb_ops import create_kb as _create_kb

        # Ensure .md extension
        if not path.endswith(".md"):
            path = path + ".md"

        result = await _create_kb(path, content)

        if "error" in result:
            return json.dumps(result)

        # Log activity
        try:
            from .core.activity import get_activity_tracker, ActivityType

            tracker = get_activity_tracker()
            await tracker.log_event(
                event_type=ActivityType.KB_CREATE,
                details={"path": path, "size": len(content)},
            )
        except Exception:
            pass  # Don't fail on logging errors

        return json.dumps({
            "created": result["path"],
            "size": result["size"],
        }, indent=2)

    @server.tool()
    async def update_kb(path: str, content: str) -> str:
        """Update an existing KB entry.

        Args:
            path: Relative path to the entry
            content: New markdown content
        """
        from .storage.kb_ops import update_kb as _update_kb

        result = await _update_kb(path, content)

        if "error" in result:
            return json.dumps(result)

        # Log activity
        try:
            from .core.activity import get_activity_tracker, ActivityType

            tracker = get_activity_tracker()
            await tracker.log_event(
                event_type=ActivityType.KB_UPDATE,
                details={"path": path, "old_size": result["old_size"], "new_size": result["new_size"]},
            )
        except Exception:
            pass  # Don't fail on logging errors

        return json.dumps({
            "updated": path,
            "old_size": result["old_size"],
            "new_size": result["new_size"],
        }, indent=2)

    @server.tool()
    async def delete_kb(path: str) -> str:
        """Delete a KB entry.

        Args:
            path: Relative path to delete
        """
        from .storage.kb_ops import delete_kb as _delete_kb

        result = await _delete_kb(path)

        if "error" in result:
            return json.dumps(result)

        return json.dumps({"deleted": path}, indent=2)

    @server.tool()
    async def list_kb(directory: str = "") -> str:
        """List KB entries in a directory.

        Args:
            directory: Subdirectory to list (default: list all allowed dirs)
        """
        from .storage.kb_ops import list_kb as _list_kb

        result = await _list_kb(directory)

        if "error" in result:
            return json.dumps(result)

        return json.dumps({
            "entries": result["entries"],
            "total": len(result["entries"]),
        }, indent=2)

    # --- Inference Operations ---

    @server.tool()
    async def ask_local(
        question: str,
        technique: str = "",
        max_tokens: int = 2048,
    ) -> str:
        """Query local LLM via optillm.

        Args:
            question: The question or prompt
            technique: optillm technique (cot_reflection, bon, moa, etc.) - empty for passthrough
            max_tokens: Maximum tokens to generate
        """
        try:
            from .inference import get_client, Message

            client = get_client()
            result = await client.complete(
                messages=[Message(role="user", content=question)],
                technique=technique or None,
                max_tokens=max_tokens,
            )

            return json.dumps(
                {
                    "response": result.content,
                    "model": result.model,
                    "technique": result.technique,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Search Operations ---

    @server.tool()
    async def web_search(query: str, count: int = 5) -> str:
        """Search the web via Brave API.

        Args:
            query: Search query
            count: Number of results (max 20)
        """
        try:
            from .inference import get_search

            search = get_search()
            results = await search.search(query, count=count)

            return json.dumps(
                {
                    "results": [
                        {
                            "title": r.title,
                            "url": r.url,
                            "snippet": r.snippet,
                            "published": r.published,
                        }
                        for r in results
                    ],
                    "total": len(results),
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def research_topic(
        topic: str,
        domain: str = "",
        save_to_kb: bool = True,
    ) -> str:
        """Research a topic using web search and local LLM, optionally saving to KB.

        Args:
            topic: Topic to research
            domain: Domain context (e.g., "Apache Kudu", "pension")
            save_to_kb: Whether to save the result to the KB
        """
        try:
            from .inference import get_client, get_search, Message

            # Search for information
            search = get_search()
            results = await search.search_for_kb(topic, domain or "general", count=5)

            if not results:
                return json.dumps({"error": "No search results found"}, indent=2)

            # Format sources for synthesis
            sources_text = "\n".join(
                f"- [{r['title']}]({r['source']}): {r['summary']}" for r in results
            )

            # Synthesize with local LLM
            client = get_client()
            synthesis_prompt = f"""Topic: {topic}
Domain: {domain or 'general'}

Sources:
{sources_text}

Create a structured markdown note with:
1. Key points and facts
2. Implications or applications
3. Related concepts (as wiki-links using [[concept]] syntax)

Be concise but thorough."""

            synthesis = await client.complete(
                messages=[
                    Message(
                        role="system",
                        content=f"You are a research assistant specializing in {domain or 'general topics'}.",
                    ),
                    Message(role="user", content=synthesis_prompt),
                ],
                technique="cot_reflection",  # Use reflection for better synthesis
                max_tokens=2048,
            )

            # Create KB entry if requested
            kb_path = None
            if save_to_kb:
                today = datetime.now().strftime("%Y-%m-%d")
                timestamp = datetime.now().strftime("%H%M%S")
                safe_topic = topic.replace(" ", "_").replace("/", "-")[:50]
                kb_path = f"scratch/{today}/{timestamp}_{safe_topic}.md"

                content = f"""# {topic}

Created: {datetime.now().isoformat()}
Domain: {domain or 'general'}

---

{synthesis.content}

---

## Sources

{sources_text}
"""
                full_path = validate_kb_path(kb_path)
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content)

            return json.dumps(
                {
                    "topic": topic,
                    "domain": domain,
                    "synthesis": synthesis.content,
                    "sources": results,
                    "kb_path": kb_path,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Model Registry Operations ---

    @server.tool()
    async def list_models(capability: str = "") -> str:
        """List available models in the registry.

        Args:
            capability: Filter by capability (reasoning, coding, text_embedding, etc.)
        """
        try:
            from .models import get_model_registry, ModelCapability

            registry = get_model_registry()

            if capability:
                cap = ModelCapability[capability.upper()]
                models = registry.list_by_capability(cap)
            else:
                models = registry.list_models()

            return json.dumps(
                {
                    "models": [
                        {
                            "model_id": m.model_id,
                            "name": m.name,
                            "provider": m.provider,
                            "capabilities": [c.name for c in m.capabilities],
                            "context_length": m.context_length,
                            "description": m.description,
                        }
                        for m in models
                    ],
                    "total": len(models),
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def get_model(task: str) -> str:
        """Get the best model for a specific task.

        Args:
            task: Task type (reasoning, coding, orchestration, text_embedding, vision_embedding, etc.)
        """
        try:
            from .models import get_model_for_task, TaskType

            task_type = TaskType[task.upper()]
            model = get_model_for_task(task_type)

            return json.dumps(
                {
                    "model_id": model.model_id,
                    "name": model.name,
                    "provider": model.provider,
                    "capabilities": [c.name for c in model.capabilities],
                    "context_length": model.context_length,
                    "default_temperature": model.default_temperature,
                    "description": model.description,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def ask_reasoning(
        question: str,
        system_prompt: str = "",
        max_tokens: int = 4096,
    ) -> str:
        """Query the reasoning model for complex analysis.

        Uses chain-of-thought reasoning for math, logic, and analysis tasks.
        Falls back to default model if preferred reasoning model unavailable.

        Args:
            question: The question or prompt
            system_prompt: Optional system prompt
            max_tokens: Maximum tokens to generate
        """
        try:
            from .inference import get_client, Message
            from .models import get_model_for_task, TaskType

            # Get preferred reasoning model (may not be deployed)
            model_spec = get_model_for_task(TaskType.REASONING)
            client = get_client()

            messages = []
            if system_prompt:
                messages.append(Message(role="system", content=system_prompt))
            messages.append(Message(role="user", content=question))

            # Try with preferred model, fallback to default on error
            try:
                result = await client.complete(
                    messages=messages,
                    model=model_spec.model_id if model_spec else None,
                    temperature=model_spec.default_temperature if model_spec else 0.6,
                    max_tokens=max_tokens,
                )
            except Exception:
                # Fallback: use default model (no override)
                result = await client.complete(
                    messages=messages,
                    temperature=0.6,
                    max_tokens=max_tokens,
                )

            return json.dumps(
                {
                    "response": result.content,
                    "model": result.model,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Embedding Operations ---

    @server.tool()
    async def embed_text(text: str) -> str:
        """Generate a text embedding using Nomic.

        Returns a 768-dimensional vector in the unified text+vision space.

        Args:
            text: Text to embed
        """
        try:
            from .models import get_embeddings

            embeddings = get_embeddings()
            result = await embeddings.embed_text(text)

            return json.dumps(
                {
                    "vector": result.to_list(),
                    "dimension": result.dim,
                    "model": result.model,
                    "latency_ms": result.latency_ms,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def embed_texts(texts: str) -> str:
        """Generate embeddings for multiple texts.

        Args:
            texts: JSON array of texts to embed
        """
        try:
            from .models import get_embeddings

            text_list = json.loads(texts)
            embeddings = get_embeddings()
            result = await embeddings.embed_texts(text_list)

            return json.dumps(
                {
                    "count": result.count,
                    "dimension": result.dim,
                    "model": result.model,
                    "latency_ms": result.latency_ms,
                    "vectors": result.vectors.tolist(),
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def semantic_search(query: str, collection: str = "kb", limit: int = 10) -> str:
        """Perform semantic similarity search.

        Args:
            query: Search query
            collection: Collection to search (kb, research, etc.)
            limit: Maximum results
        """
        try:
            from .search import get_vector_search

            search = get_vector_search()
            results = await search.search(query, collection=collection, limit=limit)

            return json.dumps(
                {
                    "results": [
                        {
                            "id": r.id,
                            "content": r.content[:500],
                            "score": r.score,
                            "metadata": r.metadata,
                        }
                        for r in results
                    ],
                    "total": len(results),
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Evaluation Operations ---

    @server.tool()
    async def evaluate_output(
        output: str,
        task_prompt: str,
        context: str = "",
        dimensions: str = "",
    ) -> str:
        """Evaluate agent output using frontier model (xAI Grok).

        Args:
            output: The agent output to evaluate
            task_prompt: Original task/prompt
            context: Additional context
            dimensions: Comma-separated dimensions (accuracy,coherence,relevance,completeness,clarity)
        """
        try:
            from .models import get_evaluator, EvaluationDimension

            evaluator = get_evaluator()

            dims = None
            if dimensions:
                dim_names = [d.strip().upper() for d in dimensions.split(",")]
                dims = [EvaluationDimension[d] for d in dim_names]

            result = await evaluator.evaluate(
                agent_output=output,
                task_prompt=task_prompt,
                context=context,
                dimensions=dims,
            )

            return json.dumps(result.to_dict(), indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Agent Versioning Operations ---

    @server.tool()
    async def list_agent_versions(agent_id: str, limit: int = 10) -> str:
        """List version history for an agent.

        Args:
            agent_id: Agent identifier (leader, worker, critic, etc.)
            limit: Maximum versions to return
        """
        try:
            from .models import get_version_manager

            manager = get_version_manager()
            versions = await manager.get_versions(agent_id, limit=limit)

            return json.dumps(
                {
                    "agent_id": agent_id,
                    "versions": [
                        {
                            "version_id": v.version_id,
                            "is_active": v.is_active,
                            "avg_score": v.avg_overall_score,
                            "eval_count": v.evaluation_count,
                            "created_at": v.created_at.isoformat(),
                            "change_notes": v.change_notes,
                        }
                        for v in versions
                    ],
                    "total": len(versions),
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def get_active_config(agent_id: str) -> str:
        """Get the active configuration for an agent.

        Args:
            agent_id: Agent identifier
        """
        try:
            from .models import get_version_manager

            manager = get_version_manager()
            version = await manager.get_active_version(agent_id)

            if version is None:
                return json.dumps({"error": f"No active version for {agent_id}"})

            return json.dumps(
                {
                    "version_id": version.version_id,
                    "agent_id": version.agent_id,
                    "config": version.config.to_dict(),
                    "metrics": version.metrics,
                    "avg_score": version.avg_overall_score,
                    "eval_count": version.evaluation_count,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def get_best_agent_version(agent_id: str, metric: str = "avg_overall_score") -> str:
        """Get the best performing version for an agent.

        Args:
            agent_id: Agent identifier
            metric: Metric to rank by (avg_overall_score, accuracy, coherence, etc.)
        """
        try:
            from .models import get_version_manager

            manager = get_version_manager()
            version = await manager.get_best_version(agent_id, metric=metric)

            if version is None:
                return json.dumps({"error": f"No versions with sufficient evaluations for {agent_id}"})

            return json.dumps(
                {
                    "version_id": version.version_id,
                    "agent_id": version.agent_id,
                    "config": version.config.to_dict(),
                    "metrics": version.metrics,
                    "avg_score": version.avg_overall_score,
                    "eval_count": version.evaluation_count,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def rollback_agent(agent_id: str, version_id: str) -> str:
        """Rollback an agent to a previous version.

        Args:
            agent_id: Agent identifier
            version_id: Version to activate
        """
        try:
            from .models import get_version_manager

            manager = get_version_manager()
            success = await manager.set_active_version(agent_id, version_id)

            return json.dumps(
                {
                    "success": success,
                    "agent_id": agent_id,
                    "activated_version": version_id,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def save_agent_version(
        agent_id: str,
        system_prompt: str,
        model: str = "",
        temperature: float = 0.7,
        change_notes: str = "",
    ) -> str:
        """Save a new agent version.

        Args:
            agent_id: Agent identifier
            system_prompt: System prompt for the agent
            model: Model to use (empty for default)
            temperature: Temperature setting
            change_notes: Description of changes
        """
        try:
            from .models import get_version_manager, AgentConfig

            manager = get_version_manager()

            config = AgentConfig(
                system_prompt=system_prompt,
                model=model or "Qwen/Qwen3-Coder-30B-A3B-Instruct",
                temperature=temperature,
            )

            version = await manager.save_version(
                agent_id=agent_id,
                config=config,
                change_notes=change_notes,
                set_active=True,
            )

            return json.dumps(
                {
                    "version_id": version.version_id,
                    "agent_id": version.agent_id,
                    "is_active": version.is_active,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Optimization Operations ---

    @server.tool()
    async def optimize_agent(
        agent_id: str,
        examples: str,
        strategy: str = "apo",
        num_candidates: int = 5,
        num_iterations: int = 3,
    ) -> str:
        """Run optimization on an agent using APO or GEPA.

        Args:
            agent_id: Agent to optimize
            examples: JSON array of task examples [{input_prompt, expected_output?, context?}]
            strategy: Optimization strategy (apo, gepa, hybrid)
            num_candidates: Candidates per iteration
            num_iterations: Maximum iterations
        """
        try:
            from .models import (
                get_optimizer,
                OptimizationStrategy,
                TaskExample,
            )

            strat = OptimizationStrategy[strategy.upper()]
            optimizer = get_optimizer(strat)

            example_list = json.loads(examples)
            task_examples = [
                TaskExample(
                    input_prompt=e["input_prompt"],
                    expected_output=e.get("expected_output"),
                    context=e.get("context", ""),
                )
                for e in example_list
            ]

            result = await optimizer.optimize(
                agent_id=agent_id,
                task_examples=task_examples,
                num_candidates=num_candidates,
                num_iterations=num_iterations,
            )

            return json.dumps(
                {
                    "success": result.success,
                    "new_version_id": result.new_version_id,
                    "improvement_percent": result.improvement_percent,
                    "baseline_score": result.baseline_score,
                    "best_score": result.best_candidate_score,
                    "iterations": result.iteration,
                    "total_evaluations": result.total_evaluations,
                    "latency_ms": result.latency_ms,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Activity & Summary Operations ---

    @server.tool()
    async def log_activity(
        event_type: str,
        domain: str = "",
        details: str = "{}",
    ) -> str:
        """Log an activity event.

        Args:
            event_type: Event type (query, domain_change, swarm_run, kb_create, command, etc.)
            domain: Domain context
            details: JSON object with event details
        """
        try:
            from .core.activity import get_activity_tracker, ActivityType

            tracker = get_activity_tracker()
            detail_dict = json.loads(details) if details else {}

            # Convert string to ActivityType enum
            try:
                activity_type = ActivityType(event_type)
            except ValueError:
                # For custom event types, default to COMMAND
                activity_type = ActivityType.COMMAND

            await tracker.log_event(
                event_type=activity_type,
                domain=domain or None,
                details=detail_dict,
            )

            return json.dumps({"logged": True, "event_type": event_type}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def get_activity_stats(days: int = 7) -> str:
        """Get activity statistics.

        Args:
            days: Number of days to analyze
        """
        try:
            from .core.activity import get_activity_tracker

            tracker = get_activity_tracker()
            stats = await tracker.get_stats(days=days)

            return json.dumps(stats, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def get_daily_summary(date: str = "") -> str:
        """Get or generate daily summary.

        Args:
            date: Date in YYYY-MM-DD format (empty for today)
        """
        try:
            from datetime import date as date_type
            from .agents.daily_summary import get_daily_summary_agent

            if date:
                summary_date = date_type.fromisoformat(date)
            else:
                summary_date = date_type.today()

            agent = get_daily_summary_agent()
            summary = await agent.generate_summary(summary_date)

            return json.dumps(
                {
                    "date": str(summary_date),
                    "content": summary.to_markdown(),
                    "overview": summary.overview,
                    "insights": summary.insights,
                    "tomorrow_focus": summary.tomorrow_focus,
                    "metrics": {
                        "queries": summary.total_queries,
                        "swarm_runs": summary.total_swarm_runs,
                        "kb_entries": summary.total_entries,
                        "tokens": summary.total_tokens,
                        "domains": summary.domains_active,
                    },
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Swarm Operations ---

    @server.tool()
    async def run_swarm(
        query: str,
        domain: str = "",
        num_agents: int = 7,
    ) -> str:
        """Run swarm analysis on a query.

        Args:
            query: The query or topic to analyze
            domain: Domain context (pension, kudu, etc.)
            num_agents: Number of specialist agents
        """
        try:
            from .agents.swarm import get_swarm_manager
            from .agents.roles import AgentRole

            # Select subset of roles based on num_agents
            all_roles = list(AgentRole)
            roles = all_roles[:num_agents] if num_agents < len(all_roles) else all_roles

            manager = get_swarm_manager(roles=roles)
            result = await manager.run_round(domain=domain or query, context=query)

            return json.dumps(
                {
                    "query": query,
                    "domain": domain or query,
                    "synthesis": result.consensus,
                    "perspectives": [
                        {
                            "agent": r.name,
                            "role": r.role.value,
                            "analysis": r.content[:500] + "..." if len(r.content) > 500 else r.content,
                            "tokens": r.tokens,
                            "succeeded": r.succeeded,
                        }
                        for r in result.responses
                    ],
                    "success_rate": result.success_rate,
                    "tokens_used": result.total_tokens,
                    "latency_ms": result.total_latency_ms,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Scheduler Operations ---

    @server.tool()
    async def scheduler_status() -> str:
        """Get scheduler status including endpoints, queue, and metrics.

        Returns comprehensive status of the inference scheduler.
        Uses gaius-engine if available (GAIUS_ENABLE_FALLBACKS=true), otherwise direct access.
        """
        try:
            # Try engine proxy first
            client = await _get_engine_client()
            if client:
                status = await client.call("Scheduler", "status", {})
                return json.dumps(status, indent=2, default=str)

            # Fall back to direct access
            from .inference.scheduler import get_scheduler_service

            service = get_scheduler_service()
            status = service.get_status()

            return json.dumps(status, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def scheduler_submit(
        prompt: str,
        model: str = "",
        priority: str = "normal",
        max_tokens: int = 1024,
    ) -> str:
        """Submit an inference job to the scheduler.

        Args:
            prompt: The prompt to send
            model: Model to use (empty for default)
            priority: Job priority (critical, high, normal, low)
            max_tokens: Maximum tokens to generate
        """
        try:
            from .inference.scheduler import (
                get_scheduler_service,
                Job,
                JobPriority,
            )

            # Parse priority
            priority_map = {
                "critical": JobPriority.CRITICAL,
                "high": JobPriority.HIGH,
                "normal": JobPriority.NORMAL,
                "low": JobPriority.LOW,
            }
            job_priority = priority_map.get(priority.lower(), JobPriority.NORMAL)

            service = get_scheduler_service()

            job = Job(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                priority=job_priority,
                estimated_tokens=max_tokens,
            )

            result = await service.submit(job)

            return json.dumps(
                {
                    "job_id": result.job_id,
                    "status": result.status.value,
                    "content": result.content,
                    "model": result.model,
                    "endpoint": result.endpoint,
                    "latency_ms": result.latency_ms,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "error": result.error,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def scheduler_submit_async(
        prompt: str,
        model: str = "",
        priority: str = "normal",
        max_tokens: int = 1024,
    ) -> str:
        """Submit a job for background execution (non-blocking).

        Args:
            prompt: The prompt to send
            model: Model to use (empty for default)
            priority: Job priority (critical, high, normal, low)
            max_tokens: Maximum tokens to generate

        Returns:
            Job ID for tracking
        """
        try:
            from .inference.scheduler import (
                get_scheduler_service,
                Job,
                JobPriority,
            )

            priority_map = {
                "critical": JobPriority.CRITICAL,
                "high": JobPriority.HIGH,
                "normal": JobPriority.NORMAL,
                "low": JobPriority.LOW,
            }
            job_priority = priority_map.get(priority.lower(), JobPriority.NORMAL)

            service = get_scheduler_service()

            job = Job(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                priority=job_priority,
                estimated_tokens=max_tokens,
            )

            job_id = await service.submit_async(job)

            return json.dumps(
                {
                    "job_id": job_id,
                    "status": "submitted",
                    "message": "Job submitted for background execution",
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def scheduler_get_result(job_id: str) -> str:
        """Get the result of a submitted job.

        Args:
            job_id: Job ID to retrieve
        """
        try:
            from .inference.scheduler import get_scheduler_service

            service = get_scheduler_service()
            result = service.get_result(job_id)

            if result is None:
                return json.dumps(
                    {"job_id": job_id, "status": "pending", "message": "Job still running"},
                    indent=2,
                )

            return json.dumps(
                {
                    "job_id": result.job_id,
                    "status": result.status.value,
                    "content": result.content,
                    "model": result.model,
                    "endpoint": result.endpoint,
                    "latency_ms": result.latency_ms,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "error": result.error,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def scheduler_run_swarm(
        domain: str,
        context: str = "",
        roles: str = "",
    ) -> str:
        """Run a swarm analysis with optimal scheduling.

        Args:
            domain: Domain to analyze
            context: Additional context
            roles: Comma-separated role names (empty for all)
        """
        try:
            from .inference.scheduler import get_scheduler_service
            from .agents.roles import AgentRole

            service = get_scheduler_service()

            # Parse roles
            role_list = None
            if roles:
                role_names = [r.strip() for r in roles.split(",")]
                role_list = []
                for name in role_names:
                    try:
                        role_list.append(AgentRole(name))
                    except ValueError:
                        pass

            results = await service.run_swarm(
                domain=domain,
                context=context,
                roles=role_list,
            )

            # Format results
            output = {
                "domain": domain,
                "agents": {},
                "summary": {
                    "total": len(results),
                    "completed": sum(1 for r in results.values() if r.status.value == "completed"),
                    "failed": sum(1 for r in results.values() if r.status.value == "failed"),
                },
            }

            for role_name, result in results.items():
                output["agents"][role_name] = {
                    "status": result.status.value,
                    "content": result.content[:500] + "..." if len(result.content) > 500 else result.content,
                    "model": result.model,
                    "endpoint": result.endpoint,
                    "latency_ms": result.latency_ms,
                    "error": result.error,
                }

            return json.dumps(output, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def scheduler_health_check() -> str:
        """Check health of all GPU endpoints."""
        try:
            from .inference.scheduler import get_scheduler_service

            service = get_scheduler_service()
            health = await service.health_check()

            return json.dumps(
                {
                    "endpoints": health,
                    "all_healthy": all(health.values()),
                    "healthy_count": sum(1 for v in health.values() if v),
                    "total_count": len(health),
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def scheduler_metrics() -> str:
        """Get scheduler performance metrics."""
        try:
            from .inference.scheduler import get_scheduler_service

            service = get_scheduler_service()
            metrics = service.get_metrics()

            return json.dumps(metrics, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- GPU Orchestrator Operations ---

    @server.tool()
    async def orchestrator_status() -> str:
        """Get GPU orchestrator status including all vLLM processes and GPU health.

        Returns comprehensive status of GPU resources, process health, and scheduling metrics.
        Uses gaius-engine if available (GAIUS_ENABLE_FALLBACKS=true), otherwise direct access.
        """
        try:
            # Try engine proxy first
            client = await _get_engine_client()
            if client:
                status = await client.call("Orchestrator", "status", {})
                return json.dumps(status, indent=2, default=str)

            # Fall back to direct access
            from .inference.orchestrator import get_orchestrator

            orchestrator = get_orchestrator()
            status = orchestrator.get_status()

            return json.dumps(status, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def orchestrator_clean_start(endpoints: str = "reasoning") -> str:
        """Clean start: kill stale processes and start from fresh.

        This is the recommended way to start Gaius for overnight evolution runs.
        Cleans up orphaned vLLM processes, frees GPU memory, then starts endpoints.

        Args:
            endpoints: Comma-separated endpoint names to start (default: reasoning)
        """
        try:
            from .inference.orchestrator import get_orchestrator

            orchestrator = get_orchestrator()

            endpoint_list = [e.strip() for e in endpoints.split(",") if e.strip()]
            results = await orchestrator.clean_start(endpoint_list or None)

            return json.dumps(results, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def orchestrator_start(endpoint: str = "") -> str:
        """Start vLLM endpoint(s).

        Args:
            endpoint: Endpoint name to start (empty string starts all configured endpoints)
        """
        try:
            from .inference.orchestrator import get_orchestrator

            orchestrator = get_orchestrator()

            if endpoint:
                success = await orchestrator.start_endpoint(endpoint)
                return json.dumps(
                    {
                        "endpoint": endpoint,
                        "started": success,
                        "status": orchestrator.get_endpoint_status(endpoint).status.value
                        if orchestrator.get_endpoint_status(endpoint) else "unknown",
                    },
                    indent=2,
                )
            else:
                results = await orchestrator.start_all()
                return json.dumps(
                    {
                        "action": "start_all",
                        "results": results,
                        "successful": sum(1 for v in results.values() if v),
                        "total": len(results),
                    },
                    indent=2,
                )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def orchestrator_stop(endpoint: str = "") -> str:
        """Stop vLLM endpoint(s).

        Args:
            endpoint: Endpoint name to stop (empty string stops all)
        """
        try:
            from .inference.orchestrator import get_orchestrator

            orchestrator = get_orchestrator()

            if endpoint:
                success = await orchestrator.stop_endpoint(endpoint)
                return json.dumps(
                    {"endpoint": endpoint, "stopped": success},
                    indent=2,
                )
            else:
                results = await orchestrator.stop_all()
                return json.dumps(
                    {
                        "action": "stop_all",
                        "results": results,
                        "stopped": sum(1 for v in results.values() if v),
                        "total": len(results),
                    },
                    indent=2,
                )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def orchestrator_restart(endpoint: str) -> str:
        """Restart a specific vLLM endpoint.

        Args:
            endpoint: Endpoint name to restart
        """
        try:
            from .inference.orchestrator import get_orchestrator

            orchestrator = get_orchestrator()
            success = await orchestrator.restart_endpoint(endpoint)

            proc = orchestrator.get_endpoint_status(endpoint)
            return json.dumps(
                {
                    "endpoint": endpoint,
                    "restarted": success,
                    "status": proc.status.value if proc else "unknown",
                    "pid": proc.pid if proc else None,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def orchestrator_logs(endpoint: str, lines: int = 50) -> str:
        """Get recent stdout/stderr logs from a vLLM endpoint.

        Args:
            endpoint: Endpoint name
            lines: Number of lines to return (default: 50)
        """
        try:
            from .inference.orchestrator import get_orchestrator

            orchestrator = get_orchestrator()
            logs = orchestrator.get_logs(endpoint, lines=lines)

            return json.dumps(
                {
                    "endpoint": endpoint,
                    "lines": len(logs),
                    "logs": logs,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def gpu_health() -> str:
        """Get detailed GPU health metrics (VRAM, temp, power, utilization).

        Uses pynvml for real-time GPU monitoring.
        Uses gaius-engine if available (GAIUS_ENABLE_FALLBACKS=true), otherwise direct access.
        """
        try:
            # Try engine proxy first
            client = await _get_engine_client()
            if client:
                health = await client.call("Health", "gpu_detailed", {})
                return json.dumps(health, indent=2, default=str)

            # Fall back to direct access
            from .inference.health import get_health_monitor

            monitor = get_health_monitor()

            # Try to reinitialize if not available (e.g., pynvml installed after startup)
            if not monitor.available:
                if monitor.reinitialize():
                    pass  # Successfully reinitialized

            summary = monitor.get_summary()

            return json.dumps(summary, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Cognition Operations ---
    # Background thinking and thought generation

    @server.tool()
    async def trigger_cognition(
        max_thoughts: int = 5,
        trigger_reason: str = "manual",
    ) -> str:
        """Run a cognition cycle to generate thoughts.

        Analyzes recent KB entries and activity to detect patterns,
        find connections, and generate curiosity-driven questions.

        Args:
            max_thoughts: Maximum thoughts to generate
            trigger_reason: Why cognition was triggered (manual, scheduled, content_threshold, session_start)
        """
        try:
            from .agents.cognition import get_cognition_agent

            agent = get_cognition_agent()
            result = await agent.think(
                max_thoughts=max_thoughts,
                trigger_reason=trigger_reason,
            )

            return json.dumps(
                {
                    "thoughts_generated": len(result.thoughts),
                    "thoughts": [t.to_dict() for t in result.thoughts],
                    "patterns_detected": result.patterns_detected,
                    "connections_found": result.connections_found,
                    "curiosities_generated": result.curiosities_generated,
                    "self_observations": result.self_observations,
                    "engine_audits": result.engine_audits,
                    "duration_ms": result.duration_ms,
                    "trigger_reason": result.trigger_reason,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def trigger_self_observation() -> str:
        """Trigger a self-observation cognition cycle.

        Generates SELF_OBSERVATION thoughts that analyze recent thought patterns,
        identify recurring themes, and reflect on the thinking process itself.
        This is the core of recursive self-awareness - thoughts about thoughts.
        """
        try:
            from .agents.cognition import get_cognition_agent, CognitionContext

            agent = get_cognition_agent()

            # Gather context focused on existing thoughts
            context = CognitionContext()
            context.active_thoughts = await agent.get_active_thoughts(limit=20)
            context.recent_kb_entries = await agent._get_recent_kb_entries()

            # Generate self-observations
            thoughts = await agent._observe_own_thoughts(context)

            # Save the thoughts
            for thought in thoughts:
                await agent._save_thought(thought)

            return json.dumps(
                {
                    "self_observations": len(thoughts),
                    "thoughts": [t.to_dict() for t in thoughts],
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def trigger_engine_audit() -> str:
        """Trigger an engine audit to generate ENGINE_AUDIT thoughts.

        Examines evolution cycles, GPU health, scheduler metrics, and other
        engine processes to detect anomalies and generate audit thoughts.
        """
        try:
            from .agents.cognition import get_cognition_agent, CognitionContext

            agent = get_cognition_agent()

            # Create minimal context for auditing
            context = CognitionContext()

            # Generate audit thoughts
            thoughts = await agent._audit_engine_health(context)

            # Save the thoughts
            for thought in thoughts:
                await agent._save_thought(thought)

            return json.dumps(
                {
                    "audit_thoughts": len(thoughts),
                    "thoughts": [t.to_dict() for t in thoughts],
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def get_thought_chain(thought_id: str = "") -> str:
        """Get the chain of thoughts leading to a specific thought.

        Traces predecessor relationships to show how thoughts evolved.

        Args:
            thought_id: UUID of the thought to trace (empty = latest thought)
        """
        try:
            import asyncpg
            from .core.config import get_config

            config = get_config()
            conn = await asyncpg.connect(config.database.url)

            try:
                # If no thought_id, get the latest thought with a chain
                if not thought_id:
                    thought_id = await conn.fetchval(
                        """
                        SELECT id FROM cognition_thoughts
                        WHERE thought_chain_id IS NOT NULL
                        ORDER BY created_at DESC LIMIT 1
                        """
                    )
                    if not thought_id:
                        return json.dumps({"error": "No thought chains found"}, indent=2)

                # Get all thoughts in the chain
                rows = await conn.fetch(
                    """
                    WITH RECURSIVE chain AS (
                        SELECT id, title, thought_type, generation, predecessor_id,
                               thought_chain_id, content, salience, created_at
                        FROM cognition_thoughts WHERE id = $1::uuid
                        UNION ALL
                        SELECT t.id, t.title, t.thought_type, t.generation, t.predecessor_id,
                               t.thought_chain_id, t.content, t.salience, t.created_at
                        FROM cognition_thoughts t
                        JOIN chain c ON t.id = c.predecessor_id
                    )
                    SELECT * FROM chain ORDER BY generation, created_at
                    """,
                    str(thought_id),
                )

                chain = [
                    {
                        "id": str(r["id"]),
                        "title": r["title"],
                        "type": r["thought_type"],
                        "generation": r["generation"],
                        "content_preview": r["content"][:200] if r["content"] else "",
                        "salience": r["salience"],
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]

                return json.dumps(
                    {
                        "chain_length": len(chain),
                        "chain": chain,
                    },
                    indent=2,
                )

            finally:
                await conn.close()

        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def get_recent_thoughts(limit: int = 10) -> str:
        """Get currently active thoughts from the cognition agent.

        Args:
            limit: Maximum number of thoughts to return
        """
        try:
            from .agents.cognition import get_cognition_agent

            agent = get_cognition_agent()
            thoughts = await agent.get_active_thoughts(limit=limit)

            return json.dumps(
                {
                    "count": len(thoughts),
                    "thoughts": [t.to_dict() for t in thoughts],
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def what_are_you_thinking(depth: str = "quick") -> str:
        """Get a synthesis of what Gaius is currently thinking about.

        Combines active thoughts, recent patterns, and a quick reflection
        into a coherent summary. This is the answer to "What have you been thinking about?"

        Args:
            depth: Reflection depth (quick, moderate, deep)
        """
        try:
            from .agents.cognition import get_cognition_agent
            from .agents.reflection import get_reflection_agent, ReflectionDepth

            cognition = get_cognition_agent()
            reflection = get_reflection_agent()

            # Get active thoughts
            thoughts = await cognition.get_active_thoughts(limit=5)

            # Get reflection based on depth
            depth_enum = ReflectionDepth(depth)
            result = await reflection.reflect(depth=depth_enum)

            # Build response
            thought_summaries = []
            for t in thoughts:
                thought_summaries.append({
                    "type": t.thought_type.value,
                    "title": t.title,
                    "summary": t.summary or t.content[:100],
                    "salience": t.salience,
                    "generation": t.generation,
                    "note_path": t.note_path,
                })

            return json.dumps(
                {
                    "active_thoughts": thought_summaries,
                    "synthesis": result.synthesis,
                    "questions": result.questions,
                    "confidence_notes": result.confidence_notes,
                    "recommendations": result.recommendations,
                    "domains_analyzed": result.domains_analyzed,
                    "depth": depth,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Session Operations ---
    # Session lifecycle and research thread management

    @server.tool()
    async def start_session(domain: str = "") -> str:
        """Start a new session and get handoff from previous.

        Args:
            domain: Initial domain context
        """
        try:
            from .core.session import get_session_manager

            manager = get_session_manager()
            session, handoff = await manager.start_session(domain=domain or None)

            return json.dumps(
                {
                    "session_id": session.id,
                    "started_at": session.started_at.isoformat(),
                    "handoff": {
                        "has_content": handoff.has_content(),
                        "time_since_last": str(handoff.time_since_last) if handoff.time_since_last else None,
                        "summary": handoff.summary,
                        "open_threads": [t.to_dict() for t in handoff.open_threads],
                    },
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def end_session(domain: str = "", generate_handoff: bool = True) -> str:
        """End the current session.

        Args:
            domain: Final domain context
            generate_handoff: Whether to generate LLM handoff summary
        """
        try:
            from .core.session import get_session_manager

            manager = get_session_manager()
            session = await manager.end_session(
                domain=domain or None,
                generate_handoff=generate_handoff,
            )

            if session is None:
                return json.dumps({"error": "No active session to end"}, indent=2)

            return json.dumps(
                {
                    "session_id": session.id,
                    "duration_seconds": session.duration_seconds,
                    "queries": session.queries,
                    "kb_entries": session.kb_entries,
                    "open_threads": len(session.open_threads),
                    "handoff_generated": session.handoff_generated,
                    "handoff_summary": session.handoff_summary,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def get_session_handoff() -> str:
        """Get handoff information from previous session.

        Returns context about what was being worked on, open threads,
        and a summary of the last session.
        """
        try:
            from .core.session import get_session_manager

            manager = get_session_manager()
            handoff = await manager.get_handoff()

            return json.dumps(
                {
                    "has_content": handoff.has_content(),
                    "time_since_last": str(handoff.time_since_last) if handoff.time_since_last else None,
                    "summary": handoff.summary,
                    "quick_context": handoff.quick_context,
                    "open_threads": [t.to_dict() for t in handoff.open_threads],
                    "previous_session": {
                        "id": handoff.previous_session.id if handoff.previous_session else None,
                        "duration_seconds": handoff.previous_session.duration_seconds if handoff.previous_session else None,
                        "queries": handoff.previous_session.queries if handoff.previous_session else 0,
                        "key_topics": handoff.previous_session.key_topics if handoff.previous_session else [],
                    },
                    "markdown": handoff.to_markdown(),
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def list_open_threads(limit: int = 10) -> str:
        """List active research threads.

        Args:
            limit: Maximum threads to return
        """
        try:
            from .core.session import get_session_manager

            manager = get_session_manager()
            threads = await manager.get_active_threads(limit=limit)

            return json.dumps(
                {
                    "count": len(threads),
                    "threads": [t.to_dict() for t in threads],
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def create_research_thread(
        topic: str,
        domain: str = "",
        initial_query: str = "",
        goal: str = "",
    ) -> str:
        """Create a new research thread.

        Args:
            topic: Thread topic
            domain: Domain context
            initial_query: The query that started this thread
            goal: Research goal
        """
        try:
            from .core.session import get_session_manager

            manager = get_session_manager()
            thread = await manager.create_thread(
                topic=topic,
                domain=domain or None,
                initial_query=initial_query,
                goal=goal,
            )

            return json.dumps(thread.to_dict(), indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Reflection Operations ---

    @server.tool()
    async def reflect(
        depth: str = "moderate",
        focus_domains: str = "",
        focus_topic: str = "",
    ) -> str:
        """Perform deep reflection on accumulated knowledge.

        Args:
            depth: How deep to reflect (quick, moderate, deep)
            focus_domains: Comma-separated list of domains to focus on
            focus_topic: Specific topic to focus on
        """
        try:
            from .agents.reflection import get_reflection_agent, ReflectionDepth

            agent = get_reflection_agent()

            domains = [d.strip() for d in focus_domains.split(",")] if focus_domains else None

            result = await agent.reflect(
                depth=ReflectionDepth(depth),
                focus_domains=domains,
                focus_topic=focus_topic or None,
            )

            return json.dumps(result.to_dict(), indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def quick_thought(topic: str) -> str:
        """Generate a quick thought on a specific topic.

        Args:
            topic: Topic to think about
        """
        try:
            from .agents.reflection import get_reflection_agent

            agent = get_reflection_agent()
            thought = await agent.quick_thought(topic)

            return json.dumps({"topic": topic, "thought": thought}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def compare_domains(domain1: str, domain2: str) -> str:
        """Compare two domains for patterns and connections.

        Args:
            domain1: First domain
            domain2: Second domain
        """
        try:
            from .agents.reflection import get_reflection_agent

            agent = get_reflection_agent()
            result = await agent.compare_domains(domain1, domain2)

            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def calibrate_understanding(topic: str) -> str:
        """Calibrate confidence in understanding of a topic.

        Args:
            topic: Topic to assess
        """
        try:
            from .agents.reflection import get_reflection_agent

            agent = get_reflection_agent()
            result = await agent.calibrate_understanding(topic)

            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- TDA Operations ---

    @server.tool()
    async def compute_tda(
        data: str,
        method: str = "persistent_homology",
    ) -> str:
        """Compute topological data analysis on embeddings.

        Args:
            data: JSON array of vectors or path to data file
            method: TDA method (persistent_homology, mapper, etc.)
        """
        try:
            from .tda import compute_persistence, TopologyResult

            if data.startswith("["):
                vectors = json.loads(data)
            else:
                # Load from file
                import numpy as np
                vectors = np.load(data).tolist()

            result = await compute_persistence(vectors)

            return json.dumps(
                {
                    "betti_numbers": result.betti_numbers,
                    "persistence_pairs": result.persistence_pairs,
                    "features": result.features,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Grid Explanation ---

    @server.tool()
    async def explain_grid_position(
        x: int = 9,
        y: int = 9,
        save: bool = False,
    ) -> str:
        """Explain a grid position using local LLM with differential geometry.

        Uses the local inference endpoint (nvidia/Orchestrator-8B) to generate
        an explanation of the semantic and topological significance of a position
        on the 19x19 UMAP projection grid.

        Args:
            x: X coordinate (0-18, default 9 = center)
            y: Y coordinate (0-18, default 9 = center)
            save: Whether to save the explanation to KB as a zettelkasten document
        """
        import asyncio
        import subprocess

        try:
            # Validate coordinates
            if not (0 <= x < 19 and 0 <= y < 19):
                return json.dumps({"error": f"Invalid coordinates: ({x}, {y}). Must be 0-18."})

            # Convert coordinates to Go notation
            col = chr(65 + x + (1 if x >= 8 else 0))  # Skip 'I'
            row = 19 - y
            position = f"{col}{row}"

            # Build CLI command
            cmd_args = position
            if save:
                cmd_args += " --save"

            # Run CLI via subprocess (completely isolated)
            cmd = ["uv", "run", "gaius-cli", "--cmd", f"/explain {cmd_args}", "--format", "json"]

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            )

            if result.returncode != 0:
                return json.dumps({"error": result.stderr}, indent=2)

            # Parse CLI JSON output
            import re
            # Find the JSON object in output (skip warnings)
            json_match = re.search(r'\{[\s\S]*\}', result.stdout)
            if json_match:
                return json_match.group(0)
            else:
                return json.dumps({"error": "No JSON output from CLI", "stdout": result.stdout})

        except subprocess.TimeoutExpired:
            return json.dumps({"error": "CLI timeout after 120s"})
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Evolution & Latent Operations ---

    @server.tool()
    async def evolution_status() -> str:
        """Get background evolution daemon status.

        Returns status of the Agent0-style self-improvement daemon,
        including cycles completed, improvement metrics, and next agent.
        Uses gaius-engine if available (GAIUS_ENABLE_FALLBACKS=true), otherwise direct access.
        """
        try:
            # Try engine proxy first
            client = await _get_engine_client()
            if client:
                status = await client.call("Evolution", "status", {})
                return json.dumps(status, indent=2, default=str)

            # Fall back to direct access
            from .agents.evolution import get_evolution_daemon

            daemon = get_evolution_daemon()
            status = daemon.get_status()

            return json.dumps(status, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def trigger_evolution(agent_id: str = "") -> str:
        """Manually trigger evolution cycle for an agent.

        Bypasses idle check and runs optimization immediately.

        Args:
            agent_id: Agent to optimize (empty for next in rotation)
        """
        try:
            from .agents.evolution import get_evolution_daemon

            daemon = get_evolution_daemon()
            result = await daemon.force_evolution_cycle(agent_id or None)

            return json.dumps(
                {
                    "success": result.success,
                    "agent_id": result.agent_id,
                    "improvement_percent": round(result.improvement_percent, 2),
                    "new_version_id": result.new_version_id,
                    "baseline_score": round(result.baseline_score, 3),
                    "best_score": round(result.best_score, 3),
                    "examples_used": result.examples_used,
                    "preempted": result.preempted,
                    "error": result.error,
                    "duration_ms": result.duration_ms,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def start_evolution_daemon() -> str:
        """Start the background evolution daemon.

        The daemon monitors GPU utilization and runs optimization
        cycles when resources are idle.
        """
        try:
            from .agents.evolution import get_evolution_daemon

            daemon = get_evolution_daemon()
            await daemon.start()

            return json.dumps(
                {
                    "status": "started",
                    "running": daemon.running,
                    "config": daemon.get_status()["config"],
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def stop_evolution_daemon() -> str:
        """Stop the background evolution daemon."""
        try:
            from .agents.evolution import get_evolution_daemon

            daemon = get_evolution_daemon()
            await daemon.stop()

            return json.dumps({"status": "stopped", "running": daemon.running}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def latent_memory_stats() -> str:
        """Get Qdrant latent memory statistics.

        Returns information about the latent working memory used
        for LatentMAS-style agent collaboration.
        """
        try:
            from .agents.latent import get_latent_memory

            memory = get_latent_memory()
            stats = await memory.get_stats()

            return json.dumps(stats, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def run_latent_swarm(
        query: str,
        domain: str = "",
        num_agents: int = 7,
    ) -> str:
        """Run swarm analysis with LatentMAS-style latent collaboration.

        Uses two-phase execution where agents share embeddings
        via Qdrant working memory instead of full text.
        Achieves 70-90% token reduction for cross-agent context.

        Args:
            query: The query or topic to analyze
            domain: Domain context (pension, kudu, etc.)
            num_agents: Number of specialist agents
        """
        try:
            from .agents.swarm import get_latent_swarm_manager
            from .agents.roles import SWARM_ROLES

            # Select subset of roles if requested
            roles = list(SWARM_ROLES.keys())[:num_agents]

            manager = get_latent_swarm_manager(roles=roles)
            result = await manager.run_round(domain=domain or query, context=query)

            # Format output
            perspectives = []
            for response in result.responses:
                perspectives.append({
                    "agent": response.name,
                    "role": response.role.value,
                    "analysis": response.content[:500] if response.succeeded else None,
                    "tokens": response.tokens,
                    "succeeded": response.succeeded,
                    "error": response.error,
                })

            return json.dumps(
                {
                    "query": query,
                    "domain": domain,
                    "synthesis": result.consensus,
                    "perspectives": perspectives,
                    "success_rate": round(result.success_rate, 3),
                    "tokens_used": result.total_tokens,
                    "latency_ms": result.total_latency_ms,
                    "latent_collaboration": True,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def clear_latent_memory(domain: str = "") -> str:
        """Clear latent working memory.

        Args:
            domain: Domain to clear (empty = clear all)
        """
        try:
            from .agents.latent import get_latent_memory

            memory = get_latent_memory()

            if domain:
                count = await memory.clear_domain(domain)
                return json.dumps({"cleared": count, "domain": domain}, indent=2)
            else:
                # Clear all by getting stats first
                stats = await memory.get_stats()
                # Clear each domain would require iterating, so just report
                return json.dumps(
                    {"message": "Use domain parameter to clear specific domain", "stats": stats},
                    indent=2,
                )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Evaluation & Tracking ---

    @server.tool()
    async def run_daily_evaluation(sample_size: int = 50) -> str:
        """Run comprehensive daily evaluation against held-out set.

        Evaluates all active agents against a sample of held-out queries
        that were not used for training. Generates a report and stores
        results in the database.

        Args:
            sample_size: Number of held-out queries to evaluate
        """
        try:
            from .agents.evolution import (
                get_daily_evaluator,
                get_report_generator,
            )

            evaluator = get_daily_evaluator()
            report_gen = get_report_generator()

            # Run evaluation
            summary = await evaluator.run_daily_evaluation(sample_size=sample_size)

            # Generate report
            report_path = report_gen.generate_daily_report(summary)

            return json.dumps(
                {
                    "eval_date": summary.eval_date.isoformat(),
                    "total_cycles": summary.total_cycles,
                    "successful_cycles": summary.successful_cycles,
                    "total_improvement_percent": round(summary.total_improvement_percent, 2),
                    "trend": summary.trend_direction,
                    "trend_confidence": summary.trend_confidence,
                    "agents_evaluated": len(summary.agent_summaries),
                    "held_out_results": summary.held_out_results,
                    "report_path": str(report_path),
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def get_held_out_stats() -> str:
        """Get statistics about the held-out query pool.

        Returns information about the queries available for
        objective evaluation.
        """
        try:
            from .agents.evolution import get_held_out_manager

            manager = get_held_out_manager()
            stats = await manager.get_stats()

            return json.dumps(stats, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def add_held_out_query(
        input_prompt: str,
        domain: str = "",
        category: str = "",
        expected_output: str = "",
    ) -> str:
        """Add a query to the held-out evaluation pool.

        Held-out queries are used for objective evaluation and
        never used for training.

        Args:
            input_prompt: The query/prompt to add
            domain: Domain classification (e.g., 'pension', 'kudu')
            category: Task category (e.g., 'reasoning', 'synthesis')
            expected_output: Optional gold standard output
        """
        try:
            from .agents.evolution import get_held_out_manager

            manager = get_held_out_manager()
            query_id = await manager.add_query(
                input_prompt=input_prompt,
                expected_output=expected_output if expected_output else None,
                domain=domain,
                category=category,
                source_type="manual",
            )

            if query_id:
                return json.dumps(
                    {"success": True, "query_id": query_id},
                    indent=2,
                )
            else:
                return json.dumps(
                    {"success": False, "reason": "duplicate or error"},
                    indent=2,
                )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def get_evolution_trend(days: int = 7) -> str:
        """Get evolution performance trend over recent days.

        Shows improvement trends, cycle counts, and score comparisons
        between training and held-out evaluations.

        Args:
            days: Number of days to analyze
        """
        try:
            from .storage.database import get_evolution_trend as _get_evolution_trend

            result = await _get_evolution_trend(days)

            if "error" in result:
                return json.dumps(result, indent=2)

            return json.dumps(
                {
                    "days_analyzed": result.get("days", days),
                    "daily_summaries": result.get("daily_summaries", []),
                    "score_comparisons": result.get("score_comparisons", []),
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- XAI Budget Monitoring ---

    @server.tool()
    async def get_xai_budget() -> str:
        """Get XAI evaluation budget status.

        Returns current usage against daily/weekly limits,
        remaining budget, and usage history.
        """
        try:
            from .models.tiered_evaluation import get_tiered_evaluator

            evaluator = get_tiered_evaluator()
            status = evaluator.get_budget_status()

            return json.dumps(status, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def reset_xai_budget(reset_daily: bool = True, reset_weekly: bool = False) -> str:
        """Reset XAI budget counters (use sparingly).

        Args:
            reset_daily: Reset daily usage counter
            reset_weekly: Reset weekly usage counter (requires confirmation)
        """
        try:
            from .models.tiered_evaluation import get_tiered_evaluator

            evaluator = get_tiered_evaluator()

            if reset_daily:
                evaluator.budget.daily_used = 0
            if reset_weekly:
                evaluator.budget.weekly_used = 0

            return json.dumps(
                {
                    "reset_daily": reset_daily,
                    "reset_weekly": reset_weekly,
                    "new_status": evaluator.get_budget_status(),
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def evaluate_with_xai(
        agent_output: str,
        task_prompt: str,
        context: str = "",
        force_xai: bool = False,
    ) -> str:
        """Evaluate agent output using tiered strategy.

        Uses local model by default, XAI only if budget allows
        and force_xai=True or for promotion decisions.

        Args:
            agent_output: The output to evaluate
            task_prompt: The original task/prompt
            context: Additional context
            force_xai: Force XAI evaluation (budget-permitting)
        """
        try:
            from .models.tiered_evaluation import get_tiered_evaluator

            evaluator = get_tiered_evaluator()

            tier = "xai" if force_xai else "auto"
            result = await evaluator.evaluate(
                agent_output=agent_output,
                task_prompt=task_prompt,
                context=context,
                use_tier=tier,
            )

            return json.dumps(
                {
                    "overall_score": result.overall_score,
                    "dimension_scores": result.dimension_scores,
                    "summary": result.summary,
                    "evaluator_model": result.evaluator_model,
                    "tier_used": "xai" if "grok" in result.evaluator_model else "local",
                    "budget_after": evaluator.get_budget_status(),
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def get_eval_comparison() -> str:
        """Get local vs XAI evaluation comparison stats.

        Shows how well the local model correlates with XAI
        evaluations, helping calibrate confidence in local evals.
        """
        try:
            from .storage.database import get_eval_comparison as _get_eval_comparison

            result = await _get_eval_comparison()

            if "error" in result:
                return json.dumps(result, indent=2)

            correlation = result.get("overall_correlation", 0)
            return json.dumps(
                {
                    "total_agents": result.get("total_agents", 0),
                    "comparisons": result.get("comparisons", []),
                    "overall_correlation": round(correlation, 3),
                    "interpretation": (
                        "Strong alignment"
                        if correlation > 0.8
                        else "Moderate alignment"
                        if correlation > 0.5
                        else "Weak alignment - consider more XAI spot checks"
                    ),
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Development Tools ---

    @server.tool()
    async def reload_modules(modules: str = "") -> str:
        """Hot-reload Python modules for development.

        Reloads specified modules (or common ones) without restarting
        the MCP server. Useful for testing code changes immediately.

        Args:
            modules: Comma-separated module names to reload.
                     Empty = reload common modules (kb_ops, factory, etc.)

        Note: This clears cached singletons and reloads module code.
        Some state may be lost. Use during development only.
        """
        import importlib
        import sys

        reloaded = []
        errors = []

        # Default modules to reload if none specified
        default_modules = [
            "gaius.storage.kb_ops",
            "gaius.storage.factory",
            "gaius.storage.filesystem",
            "gaius.storage.grid_state",
            "gaius.core.cache",
            "gaius.agents.cognition",
            "gaius.agents.reflection",
            "gaius.core.session",
        ]

        # Parse requested modules
        if modules.strip():
            target_modules = [m.strip() for m in modules.split(",")]
        else:
            target_modules = default_modules

        # Reset storage singleton first
        try:
            from .storage.factory import reset_storage
            reset_storage()
            reloaded.append("storage_singleton_reset")
        except Exception as e:
            errors.append(f"reset_storage: {e}")

        # Reload each module
        for mod_name in target_modules:
            # Ensure full module path
            if not mod_name.startswith("gaius."):
                mod_name = f"gaius.{mod_name}"

            if mod_name in sys.modules:
                try:
                    module = sys.modules[mod_name]
                    importlib.reload(module)
                    reloaded.append(mod_name)
                except Exception as e:
                    errors.append(f"{mod_name}: {e}")
            else:
                # Module not yet imported, just note it
                errors.append(f"{mod_name}: not loaded")

        return json.dumps(
            {
                "reloaded": reloaded,
                "errors": errors if errors else None,
                "hint": "Changes should take effect on next tool call",
            },
            indent=2,
        )

    # --- Grid State History ---

    @server.tool()
    async def list_grid_snapshots(kb_root: str = "build/dev", limit: int = 10) -> str:
        """List grid state snapshots with history.

        Shows previous grid projections stored in Postgres,
        allowing you to see how the KB evolved over time.

        Args:
            kb_root: KB root directory
            limit: Maximum snapshots to return
        """
        try:
            from .storage.grid_state import list_snapshots

            snapshots = await list_snapshots(kb_root, limit)

            return json.dumps(
                {
                    "kb_root": kb_root,
                    "total": len(snapshots),
                    "snapshots": [
                        {
                            "id": s.id,
                            "created_at": s.created_at.isoformat(),
                            "n_documents": s.n_documents,
                            "coverage": round(s.coverage, 3),
                            "h0_count": s.h0_count,
                            "h1_count": s.h1_count,
                            "h2_count": s.h2_count,
                            "entropy": round(s.entropy, 3),
                            "is_current": s.is_current,
                            "embedding_model": s.embedding_model,
                            "projection_method": s.projection_method,
                        }
                        for s in snapshots
                    ],
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def get_grid_stats(kb_root: str = "build/dev") -> str:
        """Get current grid state statistics.

        Returns information about the current grid projection
        including document count, TDA features, and coverage.

        Args:
            kb_root: KB root directory
        """
        try:
            from .storage.grid_state import load_current_grid_state

            grid_data, tda_features, metadata = await load_current_grid_state(kb_root)

            if grid_data is None:
                return json.dumps({
                    "error": "No grid state found",
                    "hint": "Run /init in the TUI to create initial state",
                })

            return json.dumps(
                {
                    "snapshot_id": metadata.get("snapshot_id") if metadata else None,
                    "created_at": metadata.get("created_at") if metadata else None,
                    "n_documents": grid_data.n_documents,
                    "coverage": round(grid_data.coverage, 3),
                    "method": grid_data.method,
                    "tda": {
                        "h0_count": tda_features.h0_count,
                        "h1_count": tda_features.h1_count,
                        "h2_count": tda_features.h2_count,
                        "entropy": round(tda_features.entropy, 3),
                        "h1_cycles": len(tda_features.h1_cycles),
                        "h2_voids": len(tda_features.h2_voids),
                    },
                    "embedding_model": metadata.get("embedding_model") if metadata else None,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- KB Resources ---
    # Expose KB entries as MCP resources for direct browsing

    def _register_kb_resources():
        """Register all KB entries as resources."""
        kb_root = get_kb_root()

        for allowed_dir in ALLOWED_DIRS:
            dir_path = kb_root / allowed_dir
            if not dir_path.exists():
                continue

            for md_file in dir_path.rglob("*.md"):
                rel_path = md_file.relative_to(kb_root)
                uri = f"gaius://kb/{rel_path}"

                # Create a closure to capture the path
                def make_reader(file_path: Path):
                    @server.resource(
                        uri=f"gaius://kb/{file_path.relative_to(kb_root)}",
                        name=file_path.name,
                        description=f"KB entry: {file_path.relative_to(kb_root)}",
                        mime_type="text/markdown",
                    )
                    def read_resource() -> str:
                        if file_path.exists():
                            return file_path.read_text()
                        return f"# Not Found\n\nFile not found: {file_path}"

                    return read_resource

                make_reader(md_file)

    # Register existing KB resources
    _register_kb_resources()

    return server


def main():
    """Entry point for gaius-mcp command."""
    ensure_mcp()
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
