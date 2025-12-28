"""MCP client utilities for agent access to Gaius services.

Provides a simple async interface for agents to call MCP-style tools
without needing to know the underlying implementation (gRPC, direct call, etc).
"""

from typing import Any
import asyncio


async def call_mcp_tool(tool_name: str, params: dict[str, Any]) -> Any:
    """Call an MCP tool by name.

    This is a convenience wrapper that routes to the appropriate service.
    For now, it uses direct imports to avoid gRPC complexity during
    development.

    Args:
        tool_name: Name of the tool (e.g., "get_recent_thoughts", "gpu_health")
        params: Tool parameters as a dictionary.

    Returns:
        Tool result (type depends on the tool).

    Raises:
        RuntimeError: If tool is not available or call fails.
    """
    # Route to appropriate handler
    handlers = {
        "get_recent_thoughts": _get_recent_thoughts,
        "gpu_health": _gpu_health,
        "orchestrator_status": _orchestrator_status,
        "evolution_status": _evolution_status,
        "list_objectives": _list_objectives,
        "verification_history": _verification_history,
        "search_kb": _search_kb,
        "web_search": _web_search,
        "embed_text": _embed_text,
        "research_topic": _research_topic,
        "verify_objective": _verify_objective,
    }

    handler = handlers.get(tool_name)
    if handler is None:
        raise RuntimeError(f"Unknown MCP tool: {tool_name}")

    return await handler(params)


async def _get_recent_thoughts(params: dict) -> dict:
    """Get recent thoughts from cognition agent."""
    try:
        from ..agents.cognition import CognitionAgent
        from ..storage.kb_ops import get_kb_root

        kb_root = get_kb_root()
        agent = CognitionAgent(kb_root=kb_root)
        thoughts = await agent.get_active_thoughts(limit=params.get("limit", 10))

        return {
            "thoughts": [
                {
                    "id": str(t.id) if hasattr(t, "id") else "",
                    "thought_type": t.thought_type.value if hasattr(t.thought_type, "value") else str(t.thought_type),
                    "title": t.title,
                    "content": t.content,
                    "salience": t.salience,
                }
                for t in thoughts
            ]
        }
    except Exception as e:
        return {"thoughts": [], "error": str(e)}


async def _gpu_health(params: dict) -> dict:
    """Get GPU health status."""
    try:
        from ..health.gpu import get_gpu_health

        return await get_gpu_health()
    except ImportError:
        # Fallback - check nvidia-smi
        try:
            import subprocess

            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                gpus = []
                for line in result.stdout.strip().split("\n"):
                    if line:
                        gpus.append({"info": line.strip()})
                return {"gpus": gpus, "healthy": True}
            return {"gpus": [], "healthy": False}
        except Exception:
            return {"gpus": [], "healthy": False}
    except Exception as e:
        return {"gpus": [], "healthy": False, "error": str(e)}


async def _orchestrator_status(params: dict) -> dict:
    """Get orchestrator status via engine gRPC."""
    try:
        from ..client.engine_proxy import use_engine_proxy, get_orchestrator_proxy

        if not use_engine_proxy():
            return {
                "endpoints": {},
                "healthy": False,
                "error": "Engine not available (#GR.00000001.ENGINEOFF)",
            }

        proxy = await get_orchestrator_proxy()
        status = await proxy._get_status_async()

        # Convert gRPC response to expected format
        endpoints = {}
        for ep in status.get("endpoints", []):
            name = ep.get("name", "")
            endpoints[name] = {
                "status": ep.get("status", "stopped"),
                "port": ep.get("port"),
            }

        return {
            "endpoints": endpoints,
            "healthy": any(
                ep.get("status") == "healthy" for ep in status.get("endpoints", [])
            ),
        }
    except Exception as e:
        return {"endpoints": {}, "healthy": False, "error": str(e)}


async def _evolution_status(params: dict) -> dict:
    """Get evolution daemon status."""
    try:
        from ..agents.evolution.daemon import get_evolution_daemon

        daemon = get_evolution_daemon()
        if daemon:
            return {
                "running": daemon.is_running,
                "next_agent": daemon.next_agent or "",
                "mode": daemon.mode or "",
                "score_before": daemon.last_score_before,
                "score_after": daemon.last_score_after,
            }
        return {"running": False}
    except Exception as e:
        return {"running": False, "error": str(e)}


async def _list_objectives(params: dict) -> dict:
    """List RASE objectives."""
    try:
        from ..storage.kb_ops import get_kb_root
        from pathlib import Path

        kb_root = get_kb_root()
        objectives_dir = kb_root / "current" / "objectives"

        if not objectives_dir.exists():
            return {"objectives": []}

        objectives = []
        for path in objectives_dir.glob("*.md"):
            if path.name.startswith("_"):
                continue

            # Parse frontmatter for metadata
            try:
                content = path.read_text(encoding="utf-8")
                # Simple YAML frontmatter extraction
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        import yaml

                        meta = yaml.safe_load(parts[1])
                        objectives.append(
                            {
                                "name": meta.get("name", path.stem),
                                "description": meta.get("description", ""),
                                "priority": meta.get("priority", "normal"),
                            }
                        )
                    else:
                        objectives.append({"name": path.stem, "priority": "normal"})
                else:
                    objectives.append({"name": path.stem, "priority": "normal"})
            except Exception:
                objectives.append({"name": path.stem, "priority": "normal"})

        return {"objectives": objectives}
    except Exception as e:
        return {"objectives": [], "error": str(e)}


async def _verification_history(params: dict) -> dict:
    """Get verification run history."""
    try:
        # For now, return empty history - RASE verification integration
        # will be added when we have the verification database
        return {"runs": []}
    except Exception as e:
        return {"runs": [], "error": str(e)}


async def _search_kb(params: dict) -> dict:
    """Search the knowledge base."""
    try:
        from ..storage.kb_ops import search_kb

        query = params.get("query", "")
        results = search_kb(query, max_results=params.get("max_results", 10))
        return {"results": results}
    except Exception as e:
        return {"results": [], "error": str(e)}


async def _web_search(params: dict) -> dict:
    """Search the web via Brave API."""
    try:
        from ..web.brave import brave_search

        query = params.get("query", "")
        count = params.get("count", 5)
        results = await brave_search(query, count=count)
        return {"results": results}
    except Exception as e:
        return {"results": [], "error": str(e)}


async def _embed_text(params: dict) -> dict:
    """Generate text embedding."""
    try:
        from ..embeddings.nomic import embed_text

        text = params.get("text", "")
        embedding = await embed_text(text)
        return {"embedding": embedding.tolist() if hasattr(embedding, "tolist") else embedding}
    except Exception as e:
        return {"embedding": [], "error": str(e)}


async def _research_topic(params: dict) -> dict:
    """Research a topic and save to KB."""
    try:
        from ..agents.research import research_topic

        topic = params.get("topic", "")
        save_to_kb = params.get("save_to_kb", True)
        result = await research_topic(topic, save_to_kb=save_to_kb)
        return result if isinstance(result, dict) else {"result": result}
    except Exception as e:
        return {"error": str(e)}


async def _verify_objective(params: dict) -> dict:
    """Verify an objective using RASE."""
    try:
        objective_path = params.get("objective_path", "")
        # For now, return placeholder - RASE verification to be integrated
        return {"verdict": "NOT RUN", "objective": objective_path}
    except Exception as e:
        return {"error": str(e)}
