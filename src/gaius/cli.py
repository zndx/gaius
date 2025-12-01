"""Gaius CLI - Non-interactive command mode.

Execute commands without starting the TUI. Useful for:
- Testing logic
- Scripting
- Batch operations
- CI/CD pipelines

Usage:
    # Single command
    uv run python -m gaius.cli --cmd "/info K10"

    # Multiple commands
    uv run python -m gaius.cli --cmd "/domain pension" --cmd "/overlay h1"

    # Pipe commands
    echo "/info K10" | uv run python -m gaius.cli

    # Output formats
    uv run python -m gaius.cli --cmd "/info" --format json
    uv run python -m gaius.cli --cmd "/info" --format text
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import TextIO

from .core.state import AppState, ViewMode, OverlayMode
from .static import (
    GRID_DATA,
    AGENT_DATA,
    FILE_TREE,
    DEATH_LOOPS,
    TDA_METRICS,
    get_position_hint,
)


class GaiusCLI:
    """Non-interactive command executor."""

    def __init__(self, output: TextIO = sys.stdout, error: TextIO = sys.stderr):
        self.state = AppState()
        self.output = output
        self.error = error
        self.format = "text"
        self._load_test_data()

    def _run_async(self, coro):
        """Run an async coroutine synchronously."""
        return asyncio.run(coro)

    def _load_test_data(self) -> None:
        """Initialize with static test data."""
        self.state.black_stones = GRID_DATA["black"]
        self.state.white_stones = GRID_DATA["white"]
        self.state.allocations = GRID_DATA["alloc"]
        self.state.death_loops = DEATH_LOOPS
        self.state.tda_entropy = TDA_METRICS["entropy"]

        for agent in AGENT_DATA:
            self.state.agent_positions.append((
                agent["name"],
                agent["pos"][0],
                agent["pos"][1],
                agent["color"],
            ))

    def execute(self, cmd: str) -> dict:
        """Execute a command and return result dict."""
        if cmd.startswith("/"):
            cmd = cmd[1:]

        parts = cmd.split(maxsplit=1)
        command = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""

        result = {"command": command, "args": args, "success": True, "data": {}}

        try:
            if command == "info":
                result["data"] = self._cmd_info(args)
            elif command == "goto":
                result["data"] = self._cmd_goto(args)
            elif command == "domain":
                result["data"] = self._cmd_domain(args)
            elif command == "overlay":
                result["data"] = self._cmd_overlay(args)
            elif command == "view":
                result["data"] = self._cmd_view(args)
            elif command == "state":
                result["data"] = self._cmd_state()
            elif command == "agents":
                result["data"] = self._cmd_agents()
            elif command == "grid":
                result["data"] = self._cmd_grid()
            elif command == "help":
                result["data"] = self._cmd_help()
            # Inference commands (async)
            elif command == "ask":
                result["data"] = self._run_async(self._cmd_ask(args))
            elif command == "search":
                result["data"] = self._run_async(self._cmd_search(args))
            elif command == "research":
                result["data"] = self._run_async(self._cmd_research(args))
            elif command == "research!" or command == "research-eval":
                result["data"] = self._run_async(self._cmd_research_eval(args))
            elif command == "eval":
                result["data"] = self._run_async(self._cmd_eval(args))
            elif command == "eval-stats":
                result["data"] = self._cmd_eval_stats()
            elif command == "technique":
                result["data"] = self._cmd_technique(args)
            elif command == "kb":
                result["data"] = self._cmd_kb(args)
            # Scheduler commands
            elif command == "scheduler" or command == "sched":
                result["data"] = self._run_async(self._cmd_scheduler(args))
            elif command == "submit":
                result["data"] = self._run_async(self._cmd_submit(args))
            elif command == "swarm":
                result["data"] = self._run_async(self._cmd_swarm(args))
            # GPU Orchestrator commands
            elif command == "gpu" or command == "orch":
                result["data"] = self._run_async(self._cmd_gpu(args))
            else:
                result["success"] = False
                result["error"] = f"Unknown command: {command}"
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)

        return result

    def _cmd_info(self, args: str) -> dict:
        """Get info about a position."""
        if args:
            x, y = self._parse_coord(args)
        else:
            x, y = self.state.cursor_x, self.state.cursor_y

        hint = get_position_hint(x, y)
        coord = self._coord_string(x, y)

        return {
            "position": coord,
            "x": x,
            "y": y,
            "hint": hint,
            "allocation": self.state.allocations[y][x] if self.state.allocations else None,
            "has_black": (x, y) in self.state.black_stones,
            "has_white": (x, y) in self.state.white_stones,
        }

    def _cmd_goto(self, args: str) -> dict:
        """Move cursor to position."""
        if not args:
            raise ValueError("goto requires a position argument")
        x, y = self._parse_coord(args)
        self.state.cursor_x = x
        self.state.cursor_y = y
        return {"position": self._coord_string(x, y), "x": x, "y": y}

    def _cmd_domain(self, args: str) -> dict:
        """Set or get domain."""
        if args:
            self.state.domain = args
        return {"domain": self.state.domain}

    def _cmd_overlay(self, args: str) -> dict:
        """Set or cycle overlay mode."""
        if args:
            self.state.overlay_mode = OverlayMode(args.lower())
        else:
            self.state.cycle_overlay_mode()
        return {"overlay": self.state.overlay_mode.value}

    def _cmd_view(self, args: str) -> dict:
        """Set or cycle view mode."""
        if args:
            self.state.view_mode = ViewMode(args.lower())
        else:
            self.state.cycle_view_mode()
        return {"view": self.state.view_mode.value}

    def _cmd_state(self) -> dict:
        """Get full state."""
        return {
            "cursor": self._coord_string(self.state.cursor_x, self.state.cursor_y),
            "cursor_x": self.state.cursor_x,
            "cursor_y": self.state.cursor_y,
            "view_mode": self.state.view_mode.value,
            "overlay_mode": self.state.overlay_mode.value,
            "domain": self.state.domain,
            "tda_entropy": self.state.tda_entropy,
            "num_agents": len(self.state.agent_positions),
            "num_death_loops": len(self.state.death_loops),
        }

    def _cmd_agents(self) -> dict:
        """List agents."""
        agents = []
        for name, x, y, color in self.state.agent_positions:
            agents.append({
                "name": name,
                "position": self._coord_string(x, y),
                "x": x,
                "y": y,
                "color": color,
            })
        return {"agents": agents}

    def _cmd_grid(self) -> dict:
        """Get grid representation."""
        grid_str = self._render_grid_ascii()
        return {"grid": grid_str}

    def _cmd_help(self) -> dict:
        """Get help text."""
        return {
            "commands": {
                "info [pos]": "Get info about position (default: cursor)",
                "goto <pos>": "Move cursor to position",
                "domain [name]": "Set or get domain",
                "overlay [mode]": "Set or cycle overlay mode",
                "view [mode]": "Set or cycle view mode",
                "state": "Get full application state",
                "agents": "List all agents",
                "grid": "Get ASCII grid representation",
                "help": "Show this help",
                # Inference commands
                "ask <question>": "Query local LLM (optillm)",
                "search <query>": "Hybrid search (BM25 + Vector + Web)",
                "research <topic>": "Hybrid search + LLM → Zettelkasten note",
                "research-eval <topic>": "Research + evaluate with frontier model",
                "eval <path>": "Evaluate a Zettelkasten note",
                "eval-stats": "Show aggregate evaluation statistics",
                "technique [name]": "Set or show optillm technique",
                "kb <subcommand>": "KB operations (list, read <path>, search <query>)",
                # Scheduler commands
                "scheduler [cmd]": "Scheduler ops (status, health, metrics, start, stop)",
                "submit [flags] <prompt>": "Submit job (flags: priority:high model:name)",
                "swarm <domain> [context]": "Run swarm analysis with optimal scheduling",
                # GPU Orchestrator commands
                "gpu [cmd] [args]": "GPU orchestrator (status, start, stop, restart, logs, health)",
            }
        }

    # --- Inference Commands ---

    async def _cmd_ask(self, args: str) -> dict:
        """Query local LLM via optillm."""
        if not args:
            raise ValueError("ask requires a question")

        try:
            from .inference import get_client, Message

            client = get_client()
            result = await client.complete(
                messages=[Message(role="user", content=args)],
            )

            return {
                "response": result.content,
                "model": result.model,
                "technique": result.technique,
                "tokens": f"{result.input_tokens}+{result.output_tokens}",
            }
        except ImportError:
            raise RuntimeError("Inference not available. Run: uv sync --extra inference")

    async def _cmd_search(self, args: str) -> dict:
        """Hybrid search: BM25 + Vector (Qdrant) + Brave web search.

        Combines lexical, semantic, and web results for comprehensive search.
        Uses RRF (Reciprocal Rank Fusion) to merge KB results.
        """
        if not args:
            raise ValueError("search requires a query")

        bm25_results = []
        vector_results = []
        web_results = []
        errors = []

        # BM25 lexical search over KB
        try:
            from .inference.search import get_kb_search

            kb_search = get_kb_search()
            if kb_search.index_size == 0:
                kb_search.build_index()

            bm25_hits = kb_search.search(args, top_k=10)
            bm25_results = [
                {
                    "source": "bm25",
                    "path": r.path,
                    "title": r.title,
                    "snippet": r.snippet[:150],
                    "score": round(r.score, 2),
                    "citation": f"{r.path}:/{r.match_pattern}/" if r.match_pattern else r.path,
                }
                for r in bm25_hits
            ]
        except ImportError:
            errors.append("BM25 not available (run: uv sync --extra search)")
        except Exception as e:
            errors.append(f"BM25 error: {e}")

        # Vector semantic search over KB (Qdrant)
        try:
            from .inference.search import get_vector_search

            vector_search = get_vector_search()
            vector_hits = vector_search.search(args, top_k=10)
            vector_results = [
                {
                    "source": "vector",
                    "path": r.path,
                    "title": r.title,
                    "snippet": r.snippet[:150],
                    "score": round(r.score, 3),
                    "chunk_id": r.chunk_id,
                }
                for r in vector_hits
            ]
        except ImportError:
            errors.append("Vector search not available")
        except Exception as e:
            errors.append(f"Vector search error: {e}")

        # Brave web search
        try:
            from .inference import get_search

            search = get_search()
            web_hits = await search.search(args, count=5)
            web_results = [
                {
                    "source": "web",
                    "url": r.url,
                    "title": r.title,
                    "snippet": r.snippet[:150],
                }
                for r in web_hits
            ]
        except ImportError:
            errors.append("Brave search not available")
        except RuntimeError as e:
            errors.append(f"Web search error: {e}")

        # RRF fusion of BM25 + Vector results
        fused_kb = self._rrf_fusion(bm25_results, vector_results, k=60)

        return {
            "query": args,
            "kb_results": fused_kb[:10],  # Top 10 fused
            "web_results": web_results,
            "kb_count": len(fused_kb),
            "web_count": len(web_results),
            "bm25_count": len(bm25_results),
            "vector_count": len(vector_results),
            "errors": errors if errors else None,
        }

    def _rrf_fusion(
        self,
        bm25_results: list[dict],
        vector_results: list[dict],
        k: int = 60,
    ) -> list[dict]:
        """Reciprocal Rank Fusion of BM25 and vector results.

        RRF score = sum(1 / (k + rank)) across result lists.
        """
        scores: dict[str, float] = {}
        docs: dict[str, dict] = {}

        # Score BM25 results
        for rank, doc in enumerate(bm25_results, 1):
            path = doc["path"]
            scores[path] = scores.get(path, 0) + 1 / (k + rank)
            if path not in docs:
                docs[path] = doc.copy()
                docs[path]["sources"] = []
            docs[path]["sources"].append("bm25")

        # Score vector results
        for rank, doc in enumerate(vector_results, 1):
            path = doc["path"]
            scores[path] = scores.get(path, 0) + 1 / (k + rank)
            if path not in docs:
                docs[path] = doc.copy()
                docs[path]["sources"] = []
            if "vector" not in docs[path].get("sources", []):
                docs[path]["sources"].append("vector")

        # Sort by RRF score and return
        sorted_paths = sorted(scores.keys(), key=lambda p: scores[p], reverse=True)
        result = []
        for path in sorted_paths:
            doc = docs[path]
            doc["rrf_score"] = round(scores[path], 4)
            doc["source"] = "+".join(doc.pop("sources", ["kb"]))
            result.append(doc)

        return result

    async def _cmd_research(self, args: str) -> dict:
        """Research topic using hybrid search and generate Zettelkasten note.

        Uses BM25 + Vector + Web search, then synthesizes with LLM.
        """
        if not args:
            raise ValueError("research requires a topic")

        try:
            # First, run hybrid search
            search_result = await self._cmd_search(args)

            kb_results = search_result.get("kb_results", [])
            web_results = search_result.get("web_results", [])

            if not kb_results and not web_results:
                return {"error": "No search results found"}

            # Synthesize Zettelkasten note
            from .inference import ZettelkastenSynthesizer

            synthesizer = ZettelkastenSynthesizer()
            note = await synthesizer.synthesize(
                query=args,
                kb_results=kb_results,
                web_results=web_results,
                domain=self.state.domain,
            )

            # Save note
            saved_path = note.save()

            # Verify KB citations
            verification = synthesizer.verify_citations(note)
            verified_count = sum(1 for v in verification.values() if v)

            return {
                "topic": args,
                "saved_to": str(saved_path),
                "kb_sources": len([c for c in note.citations if not c.is_web]),
                "web_sources": len([c for c in note.citations if c.is_web]),
                "wiki_links": note.wiki_links,
                "citations_verified": f"{verified_count}/{len(verification)}",
                "model": note.metadata.get("model"),
                "technique": note.metadata.get("technique"),
            }
        except ImportError as e:
            raise RuntimeError(f"Inference not available: {e}. Run: uv sync --extra search")

    async def _cmd_research_eval(self, args: str) -> dict:
        """Research topic and evaluate the generated note with frontier model."""
        if not args:
            raise ValueError("research! requires a topic")

        # First do the research
        research_result = await self._cmd_research(args)

        if "error" in research_result:
            return research_result

        # Now evaluate
        try:
            from .inference import (
                SynthesisEvaluator,
                ZettelkastenSynthesizer,
            )

            # Load the note we just created
            saved_path = research_result.get("saved_to")
            if not saved_path:
                return {**research_result, "eval_error": "No note path available"}

            # Re-run search to get sources for evaluation context
            search_result = await self._cmd_search(args)
            all_sources = (
                search_result.get("kb_results", []) +
                search_result.get("web_results", [])
            )

            # Load the saved note
            from pathlib import Path
            note_path = Path(saved_path)
            note_content = note_path.read_text()

            # Reconstruct minimal note for evaluation
            from .inference import ZettelkastenNote
            from datetime import datetime

            # Parse some metadata from content
            note = ZettelkastenNote(
                query=args,
                content=note_content,
            )

            # Evaluate - check for backend hint in domain
            backend = None
            if self.state.domain and self.state.domain.startswith("eval:"):
                backend = self.state.domain.split(":")[1]

            evaluator = SynthesisEvaluator(backend=backend)
            eval_result = await evaluator.evaluate(note, all_sources)
            eval_result.note_path = str(saved_path)

            # Save evaluation
            eval_path = eval_result.save()

            return {
                **research_result,
                "evaluation": {
                    "overall_score": round(eval_result.overall_score, 2),
                    "dimension_scores": {
                        ds.dimension: ds.score
                        for ds in eval_result.dimension_scores
                    },
                    "strengths": eval_result.strengths[:3],
                    "weaknesses": eval_result.weaknesses[:3],
                    "eval_saved_to": str(eval_path),
                },
            }
        except ImportError as e:
            return {**research_result, "eval_error": f"Evaluation not available: {e}"}
        except Exception as e:
            return {**research_result, "eval_error": str(e)}

    async def _cmd_eval(self, args: str) -> dict:
        """Evaluate an existing Zettelkasten note."""
        if not args:
            raise ValueError("eval requires a note path")

        try:
            from pathlib import Path
            from .inference import (
                SynthesisEvaluator,
                ZettelkastenNote,
            )

            kb_root = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
            note_path = kb_root / args if not args.startswith("/") else Path(args)

            if not note_path.exists():
                return {"error": f"Note not found: {args}"}

            # Read and parse note
            content = note_path.read_text()

            # Extract query from title (first # line)
            import re
            title_match = re.search(r'^# (.+)$', content, re.MULTILINE)
            query = title_match.group(1) if title_match else "unknown"

            note = ZettelkastenNote(
                query=query,
                content=content,
            )

            # For evaluation we need sources - try to extract from note
            # This is a simplified version; ideally we'd store sources separately
            sources = []

            # Evaluate
            evaluator = SynthesisEvaluator()
            eval_result = await evaluator.evaluate(note, sources)
            eval_result.note_path = str(note_path)

            # Save evaluation
            eval_path = eval_result.save()

            return {
                "note_path": str(note_path),
                "query": query,
                "overall_score": round(eval_result.overall_score, 2),
                "dimension_scores": {
                    ds.dimension: ds.score
                    for ds in eval_result.dimension_scores
                },
                "strengths": eval_result.strengths,
                "weaknesses": eval_result.weaknesses,
                "improvement_suggestions": eval_result.improvement_suggestions,
                "eval_saved_to": str(eval_path),
            }
        except ImportError as e:
            raise RuntimeError(f"Evaluation not available: {e}")

    def _cmd_eval_stats(self) -> dict:
        """Show aggregate evaluation statistics."""
        try:
            from .inference import load_evaluations, compute_aggregate_scores

            results = load_evaluations()

            if not results:
                return {
                    "total_evaluations": 0,
                    "message": "No evaluations found. Run /research! to generate evaluated notes.",
                }

            aggregates = compute_aggregate_scores(results)

            # Get recent trend (last 5 vs all)
            recent = results[-5:] if len(results) > 5 else results
            recent_agg = compute_aggregate_scores(recent)

            return {
                "total_evaluations": len(results),
                "overall_average": round(aggregates.get("overall", 0), 2),
                "dimension_averages": {
                    k: round(v, 2)
                    for k, v in aggregates.items()
                    if k != "overall"
                },
                "recent_trend": {
                    "count": len(recent),
                    "overall": round(recent_agg.get("overall", 0), 2),
                },
                "best_scoring": max(results, key=lambda r: r.overall_score).note_path if results else None,
                "worst_scoring": min(results, key=lambda r: r.overall_score).note_path if results else None,
            }
        except ImportError as e:
            raise RuntimeError(f"Evaluation not available: {e}")

    def _cmd_technique(self, args: str) -> dict:
        """Set or show optillm technique."""
        try:
            from .inference import get_client
            from .inference.config import OptillmTechnique

            client = get_client()

            if args:
                client.set_technique(args)
                return {"technique": args, "status": "set"}
            else:
                return {
                    "current": client.config.optillm_technique.value or "none",
                    "available": [t.value for t in OptillmTechnique if t.value],
                }
        except ImportError:
            raise RuntimeError("Inference not available. Run: uv sync --extra inference")

    # --- Scheduler Commands ---

    async def _cmd_scheduler(self, args: str) -> dict:
        """Scheduler operations: status, health, metrics."""
        parts = args.split(maxsplit=1) if args else ["status"]
        subcmd = parts[0].lower()

        try:
            from .inference.scheduler import get_scheduler_service

            service = get_scheduler_service()

            if subcmd == "status":
                return service.get_status()

            elif subcmd == "health":
                health = await service.health_check()
                return {
                    "endpoints": health,
                    "all_healthy": all(health.values()),
                    "healthy_count": sum(1 for v in health.values() if v),
                }

            elif subcmd == "metrics":
                return service.get_metrics()

            elif subcmd == "start":
                await service.start()
                return {"status": "started"}

            elif subcmd == "stop":
                await service.stop()
                return {"status": "stopped"}

            else:
                return {"error": f"Unknown scheduler command: {subcmd}"}

        except ImportError as e:
            raise RuntimeError(f"Scheduler not available: {e}")

    async def _cmd_submit(self, args: str) -> dict:
        """Submit an inference job to the scheduler.

        Usage: /submit [priority:high] [model:qwen] <prompt>
        """
        if not args:
            raise ValueError("submit requires a prompt")

        try:
            from .inference.scheduler import (
                get_scheduler_service,
                Job,
                JobPriority,
            )

            # Parse optional flags
            priority = JobPriority.NORMAL
            model = ""
            prompt_parts = []

            for part in args.split():
                if part.startswith("priority:"):
                    p = part.split(":")[1].lower()
                    priority_map = {
                        "critical": JobPriority.CRITICAL,
                        "high": JobPriority.HIGH,
                        "normal": JobPriority.NORMAL,
                        "low": JobPriority.LOW,
                    }
                    priority = priority_map.get(p, JobPriority.NORMAL)
                elif part.startswith("model:"):
                    model = part.split(":")[1]
                else:
                    prompt_parts.append(part)

            prompt = " ".join(prompt_parts)
            if not prompt:
                raise ValueError("submit requires a prompt after flags")

            service = get_scheduler_service()

            job = Job(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                priority=priority,
            )

            result = await service.submit(job)

            return {
                "job_id": result.job_id,
                "status": result.status.value,
                "content": result.content[:500] + "..." if len(result.content) > 500 else result.content,
                "model": result.model,
                "endpoint": result.endpoint,
                "latency_ms": result.latency_ms,
                "tokens": f"{result.input_tokens}+{result.output_tokens}",
                "error": result.error,
            }

        except ImportError as e:
            raise RuntimeError(f"Scheduler not available: {e}")

    async def _cmd_swarm(self, args: str) -> dict:
        """Run a swarm analysis.

        Usage: /swarm <domain> [context...]
        """
        if not args:
            args = self.state.domain or "general analysis"

        try:
            from .inference.scheduler import get_scheduler_service

            service = get_scheduler_service()

            # Parse domain and context
            parts = args.split(maxsplit=1)
            domain = parts[0]
            context = parts[1] if len(parts) > 1 else ""

            results = await service.run_swarm(
                domain=domain,
                context=context,
            )

            # Format results
            output = {
                "domain": domain,
                "agents": {},
                "summary": {
                    "total": len(results),
                    "completed": sum(1 for r in results.values() if r.status.value == "completed"),
                    "failed": sum(1 for r in results.values() if r.status.value == "failed"),
                    "total_tokens": sum(r.input_tokens + r.output_tokens for r in results.values()),
                    "total_latency_ms": sum(r.latency_ms for r in results.values()),
                },
            }

            for role_name, result in results.items():
                output["agents"][role_name] = {
                    "status": result.status.value,
                    "preview": result.content[:200] + "..." if len(result.content) > 200 else result.content,
                    "endpoint": result.endpoint,
                    "latency_ms": result.latency_ms,
                }

            return output

        except ImportError as e:
            raise RuntimeError(f"Scheduler not available: {e}")

    async def _cmd_gpu(self, args: str) -> dict:
        """GPU orchestrator operations.

        Usage:
            /gpu status          - Show all endpoints and GPU health
            /gpu start [name]    - Start endpoint(s)
            /gpu stop [name]     - Stop endpoint(s)
            /gpu restart <name>  - Restart endpoint
            /gpu logs <name>     - Show endpoint logs
            /gpu health          - Detailed GPU metrics
        """
        parts = args.split(maxsplit=1) if args else ["status"]
        subcmd = parts[0].lower()
        subargs = parts[1] if len(parts) > 1 else ""

        try:
            from .inference.orchestrator import get_orchestrator

            orchestrator = get_orchestrator()

            if subcmd == "status":
                return orchestrator.get_status()

            elif subcmd == "start":
                if subargs:
                    success = await orchestrator.start_endpoint(subargs)
                    proc = orchestrator.get_endpoint_status(subargs)
                    return {
                        "endpoint": subargs,
                        "started": success,
                        "status": proc.status.value if proc else "unknown",
                        "pid": proc.pid if proc else None,
                    }
                else:
                    results = await orchestrator.start_all()
                    return {
                        "action": "start_all",
                        "results": results,
                        "successful": sum(1 for v in results.values() if v),
                    }

            elif subcmd == "stop":
                if subargs:
                    success = await orchestrator.stop_endpoint(subargs)
                    return {"endpoint": subargs, "stopped": success}
                else:
                    results = await orchestrator.stop_all()
                    return {
                        "action": "stop_all",
                        "results": results,
                        "stopped": sum(1 for v in results.values() if v),
                    }

            elif subcmd == "restart":
                if not subargs:
                    return {"error": "restart requires an endpoint name"}
                success = await orchestrator.restart_endpoint(subargs)
                proc = orchestrator.get_endpoint_status(subargs)
                return {
                    "endpoint": subargs,
                    "restarted": success,
                    "status": proc.status.value if proc else "unknown",
                    "pid": proc.pid if proc else None,
                }

            elif subcmd == "logs":
                if not subargs:
                    return {"error": "logs requires an endpoint name"}
                logs = orchestrator.get_logs(subargs, lines=50)
                return {
                    "endpoint": subargs,
                    "lines": len(logs),
                    "logs": logs,
                }

            elif subcmd == "health":
                from .inference.health import get_health_monitor

                monitor = get_health_monitor()
                return monitor.get_summary()

            else:
                return {"error": f"Unknown gpu command: {subcmd}"}

        except ImportError as e:
            raise RuntimeError(f"GPU orchestrator not available: {e}")

    def _cmd_kb(self, args: str) -> dict:
        """KB operations."""
        parts = args.split(maxsplit=1)
        subcmd = parts[0] if parts else "list"
        subargs = parts[1] if len(parts) > 1 else ""

        kb_root = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
        allowed_dirs = ("archive", "current", "scratch")

        if subcmd == "list":
            entries = []
            for d in allowed_dirs:
                dir_path = kb_root / d
                if dir_path.exists():
                    for f in dir_path.rglob("*.md"):
                        entries.append(str(f.relative_to(kb_root)))
            return {"entries": entries, "total": len(entries)}

        elif subcmd == "read":
            if not subargs:
                raise ValueError("kb read requires a path")
            path = kb_root / subargs
            if not path.exists():
                return {"error": f"Not found: {subargs}"}
            return {"path": subargs, "content": path.read_text()}

        elif subcmd == "search":
            if not subargs:
                raise ValueError("kb search requires a query")
            results = []
            for d in allowed_dirs:
                dir_path = kb_root / d
                if not dir_path.exists():
                    continue
                for f in dir_path.rglob("*.md"):
                    if subargs.lower() in f.name.lower():
                        results.append(str(f.relative_to(kb_root)))
                    elif subargs.lower() in f.read_text().lower():
                        results.append(str(f.relative_to(kb_root)))
            return {"query": subargs, "results": results}

        else:
            return {"error": f"Unknown kb subcommand: {subcmd}"}

    def _parse_coord(self, coord: str) -> tuple[int, int]:
        """Parse coordinate string like 'K10' to (x, y)."""
        coord = coord.strip().upper()
        if len(coord) < 2:
            raise ValueError(f"Invalid coordinate: {coord}")

        col = coord[0]
        row_str = coord[1:]

        # Handle 'I' skip
        if col >= 'J':
            x = ord(col) - ord('A') - 1
        else:
            x = ord(col) - ord('A')

        if not (0 <= x < 19):
            raise ValueError(f"Invalid column: {col}")

        try:
            row = int(row_str)
        except ValueError:
            raise ValueError(f"Invalid row: {row_str}")

        y = 19 - row
        if not (0 <= y < 19):
            raise ValueError(f"Invalid row: {row}")

        return x, y

    def _coord_string(self, x: int, y: int) -> str:
        """Convert x, y to coordinate string."""
        col = chr(65 + x + (1 if x >= 8 else 0))
        row = 19 - y
        return f"{col}{row}"

    def _render_grid_ascii(self) -> str:
        """Render simple ASCII grid."""
        lines = []
        for y in range(19):
            row = []
            for x in range(19):
                if (x, y) == (self.state.cursor_x, self.state.cursor_y):
                    row.append("X")
                elif (x, y) in self.state.black_stones:
                    row.append("#")
                elif (x, y) in self.state.white_stones:
                    row.append("O")
                else:
                    row.append(".")
            lines.append(f"{19-y:2} " + " ".join(row))
        lines.append("   " + " ".join(chr(65+i) if i < 8 else chr(66+i) for i in range(19)))
        return "\n".join(lines)

    def format_output(self, result: dict) -> str:
        """Format result based on output format."""
        if self.format == "json":
            return json.dumps(result, indent=2)
        else:
            # Text format
            if not result["success"]:
                return f"Error: {result.get('error', 'Unknown error')}"

            data = result["data"]
            if not data:
                return "OK"

            lines = []
            for key, value in data.items():
                if isinstance(value, dict):
                    lines.append(f"{key}:")
                    for k, v in value.items():
                        lines.append(f"  {k}: {v}")
                elif isinstance(value, list):
                    lines.append(f"{key}:")
                    for item in value:
                        if isinstance(item, dict):
                            lines.append(f"  - {item}")
                        else:
                            lines.append(f"  - {item}")
                else:
                    lines.append(f"{key}: {value}")
            return "\n".join(lines)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Gaius CLI - Non-interactive command mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python -m gaius.cli --cmd "/info K10"
  uv run python -m gaius.cli --cmd "/domain pension" --cmd "/state"
  echo "/info" | uv run python -m gaius.cli
        """
    )
    parser.add_argument(
        "--cmd", "-c",
        action="append",
        dest="commands",
        help="Command to execute (can be repeated)"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)"
    )

    args = parser.parse_args()

    cli = GaiusCLI()
    cli.format = args.format

    commands = args.commands or []

    # Read from stdin if no commands and stdin is not a tty
    if not commands and not sys.stdin.isatty():
        for line in sys.stdin:
            line = line.strip()
            if line:
                commands.append(line)

    if not commands:
        parser.print_help()
        sys.exit(1)

    exit_code = 0
    for cmd in commands:
        result = cli.execute(cmd)
        output = cli.format_output(result)
        print(output)
        if not result["success"]:
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
