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

**Flow Operations (Metaflow pipelines)**
- fetch_paper: Fetch arXiv paper with PDF→markdown→topics→scoring→KB pipeline
- list_flows: List available Metaflow pipelines
- query_lineage: Query lineage graph for a KB entry

**Cloudera Documentation Sync**
- sync_cloudera_docs: Download and convert Cloudera PDF docs to markdown KB
- list_cloudera_sources: List available Cloudera product documentation sources
- cloudera_sync_status: Get current sync status and document counts

**FMEA (Failure Mode and Effects Analysis)**
- fmea_catalog: List failure modes with base RPN scores
- fmea_calculate_rpn: Calculate RPN for a failure mode with context
- fmea_get_controls: Get preventive/detective/mitigative controls from KB heuristics
- fmea_map_health_check: Map health check to failure mode ID

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

    # --- RASE Objective Verification ---

    @server.tool()
    async def verify_objective(
        objective_path: str,
        document_path: str = "",
    ) -> str:
        """Verify an objective against KB state.

        Loads an objective from the KB and verifies it using intrinsic
        verification (the KB itself serves as the oracle).

        Args:
            objective_path: Path to objective file (e.g., "current/objectives/rsv.md")
            document_path: Optional specific document to verify (defaults to objective itself)

        Returns:
            JSON with verdict, accuracy, reward, and constraint results
        """
        from .rase.domains.kb import Objective, KBOracle

        kb_root = str(get_kb_root())

        try:
            # Load objective
            objective = Objective.from_file(objective_path, kb_root=kb_root)
        except FileNotFoundError:
            return json.dumps({"error": f"Objective not found: {objective_path}"})
        except ValueError as e:
            return json.dumps({"error": f"Invalid objective: {e}"})

        # Create oracle and verify
        oracle = KBOracle(kb_root=kb_root)

        doc_path = document_path if document_path else None
        result = await oracle.verify_objective(objective, document_path=doc_path)

        # Build response
        return json.dumps({
            "objective": objective.name,
            "description": objective.description,
            "verdict": result.verdict.value,
            "accuracy": result.accuracy,
            "reward": result.to_reward(),
            "constraints": [
                {
                    "name": cr.constraint_name,
                    "satisfied": cr.satisfied,
                    "message": cr.message,
                }
                for cr in result.constraint_results
            ],
            "gates": {
                "total": len(result.constraint_results),
                "passed": sum(1 for cr in result.constraint_results if cr.satisfied),
            },
        }, indent=2)

    # --- KB Sync Operations ---

    @server.tool()
    async def kb_sync(
        target: str = "minio-local",
        dry_run: bool = False,
        resume: bool = False,
    ) -> str:
        """Sync filesystem KB to S3 storage.

        Syncs all KB files from local filesystem to Minio/S3.
        Uses SHA-256 content hashing for incremental sync.

        Args:
            target: Sync target name (default: minio-local)
            dry_run: If True, show what would sync without uploading
            resume: Resume from last checkpoint if interrupted
        """
        from .storage.sync_engine import SyncEngine, get_sync_target
        from .storage.grid_state import get_database_url

        db_url = get_database_url()
        sync_target = await get_sync_target(target, db_url)

        if not sync_target:
            return json.dumps({"error": f"Unknown sync target: {target}"})

        kb_root = get_kb_root()
        engine = SyncEngine(
            source_root=str(kb_root),
            target=sync_target,
            db_url=db_url,
        )

        result = await engine.sync(dry_run=dry_run, resume=resume)

        return json.dumps({
            "target": target,
            "dry_run": dry_run,
            "files_scanned": result.files_scanned,
            "files_uploaded": result.files_uploaded,
            "files_skipped": result.files_skipped,
            "files_failed": result.files_failed,
            "bytes_uploaded": result.bytes_uploaded,
            "orphans_found": result.orphans_found,
            "duration_ms": result.duration_ms,
            "errors": result.errors[:10] if result.errors else [],
        }, indent=2)

    @server.tool()
    async def kb_sync_status(target: str = "minio-local") -> str:
        """Get sync status for a target.

        Shows sync state summary and last run info.

        Args:
            target: Sync target name
        """
        from .storage.sync_engine import get_sync_status
        from .storage.grid_state import get_database_url

        db_url = get_database_url()
        status = await get_sync_status(target, db_url)
        return json.dumps(status, indent=2)

    @server.tool()
    async def kb_sync_targets() -> str:
        """List configured sync targets.

        Returns all S3-compatible sync targets (Minio, AWS S3, etc.)
        """
        from .storage.sync_engine import list_sync_targets
        from .storage.grid_state import get_database_url

        db_url = get_database_url()
        targets = await list_sync_targets(db_url)
        return json.dumps({"targets": targets}, indent=2)

    @server.tool()
    async def kb_sync_verify(
        target: str = "minio-local",
        sample_size: int = 20,
    ) -> str:
        """Verify synced files match local content.

        Downloads and re-hashes a sample of synced files to verify integrity.

        Args:
            target: Sync target name
            sample_size: Number of files to verify
        """
        from .storage.sync_engine import verify_sync
        from .storage.grid_state import get_database_url

        kb_root = get_kb_root()
        db_url = get_database_url()
        result = await verify_sync(target, str(kb_root), db_url, sample_size)
        return json.dumps(result, indent=2)

    # --- Flow Operations (Metaflow pipelines) ---

    @server.tool()
    async def fetch_paper(
        arxiv_url: str,
        enable_topics: bool = True,
        topic_model: str = "bertopic",
        num_topics: int | None = None,
        enable_scoring: bool = True,
        scoring_rubric: str = "default",
        use_remote_scoring: bool = False,
        archive_pdf: bool = True,
    ) -> str:
        """Fetch arXiv paper with topic modeling and LLM scoring.

        Full pipeline: PDF → markdown → topics → scoring → KB zettelkasten.
        Default behavior enables all features for comprehensive analysis.

        Args:
            arxiv_url: arXiv URL or ID (e.g., "https://arxiv.org/abs/2312.12345" or "2312.12345")
            enable_topics: Enable topic extraction (default: True)
            topic_model: Topic model type: bertopic, lda, lsa, hdp (default: bertopic)
            num_topics: Number of topics (only for LDA/LSA, None=auto)
            enable_scoring: Enable LLM relevance scoring (default: True)
            scoring_rubric: Rubric name (default: "default")
            use_remote_scoring: Use remote LLM for scoring (default: False, uses local)
            archive_pdf: Save PDF to KB archive (default: True)
        """
        try:
            from gaius.flows.config import apply_metaflow_config
            from gaius.flows.runner import run_flow_with_gpu_management
            from gaius.flows.docling.flow import ArxivDoclingFlow

            # Apply local config
            apply_metaflow_config("local")

            # Build flow args
            subprocess_args = [
                f"--arxiv_url={arxiv_url}",
                f"--archive_pdf={archive_pdf}",
                f"--enable_topics={enable_topics}",
                f"--topic_model_type={topic_model}",
                f"--enable_scoring={enable_scoring}",
                f"--scoring_rubric={scoring_rubric}",
                f"--use_remote_scoring={use_remote_scoring}",
            ]
            if num_topics is not None:
                subprocess_args.append(f"--num_topics={num_topics}")

            result = await run_flow_with_gpu_management(
                flow_class=ArxivDoclingFlow,
                flow_args=subprocess_args,
                require_gpu=True,
                estimated_memory_mb=16000,
            )

            return json.dumps({
                "success": result.success,
                "arxiv_url": arxiv_url,
                "output_path": result.output_path,
                "workload_id": result.workload_id,
                "duration_s": result.duration_s,
                "evicted_endpoints": result.evicted_endpoints,
                "restored_endpoints": result.restored_endpoints,
                "options": {
                    "topics": enable_topics,
                    "topic_model": topic_model,
                    "num_topics": num_topics,
                    "scoring": enable_scoring,
                    "rubric": scoring_rubric,
                    "remote_scoring": use_remote_scoring,
                },
                "error": result.error,
            }, indent=2)

        except Exception as e:
            import traceback
            return json.dumps({
                "success": False,
                "arxiv_url": arxiv_url,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }, indent=2)

    @server.tool()
    async def list_flows() -> str:
        """List available Metaflow pipelines.

        Returns registered flows with descriptions.
        """
        try:
            from gaius.flows import FLOW_REGISTRY

            flows = []
            for name, flow_cls in FLOW_REGISTRY.items():
                doc = flow_cls.__doc__ or ""
                first_line = doc.split("\n")[0].strip() if doc else ""
                flows.append({
                    "name": name,
                    "description": first_line,
                    "class": f"{flow_cls.__module__}.{flow_cls.__name__}",
                })

            return json.dumps({
                "flows": flows,
                "total": len(flows),
            }, indent=2)

        except Exception as e:
            return json.dumps({"error": str(e)})

    @server.tool()
    async def query_lineage(kb_path: str) -> str:
        """Query lineage for a KB file.

        Shows the full provenance chain from source to KB entry.

        Args:
            kb_path: Path to KB file (e.g., "scratch/2024-12-17/paper.md")
        """
        try:
            from gaius.hx.lineage.graph import LineageGraphQuery

            query = LineageGraphQuery()
            path = await query.get_kb_lineage(kb_path)

            if not path.nodes:
                return json.dumps({
                    "kb_path": kb_path,
                    "lineage": None,
                    "message": "No lineage found for this KB path",
                })

            return json.dumps({
                "kb_path": kb_path,
                "nodes": [
                    {"type": n.node_type, "id": n.id, "properties": n.properties}
                    for n in path.nodes
                ],
                "edges": [
                    {"type": e.edge_type, "from": e.from_id, "to": e.to_id}
                    for e in path.edges
                ],
            }, indent=2)

        except Exception as e:
            return json.dumps({"error": str(e)})

    @server.tool()
    async def lineage_cypher(cypher: str, limit: int = 100) -> str:
        """Execute a Cypher query on the lineage graph.

        Enables code agents to write and execute graph queries for:
        - Tracing KB resource provenance to original sources
        - Understanding process dependencies
        - Impact analysis for content changes
        - Finding stale content by graph traversal

        The graph follows OpenLineage standard with these elements:

        Vertex Labels:
        - Dataset: {dataset_id, namespace, name} - Data sources/sinks
        - Job: {job_id, namespace, name} - Processing definitions
        - Run: {run_id, state, event_time, job_namespace, job_name} - Executions

        Edge Labels:
        - INPUT_TO: Dataset consumed by Run
        - OUTPUTS: Run produced Dataset
        - EXECUTES: Job spawned Run
        - PARENT: Run is child of another Run

        Example queries:

        # Count vertices by label
        MATCH (n) RETURN labels(n)[0] as label, count(n) as cnt

        # Find KB files from arxiv source
        MATCH (s:Dataset)-[:INPUT_TO]->(:Run)-[:OUTPUTS]->(kb:Dataset)
        WHERE s.namespace = 'gaius.source' AND s.name STARTS WITH 'arxiv:'
        RETURN s.name as source, kb.name as kb_path

        # Trace upstream sources for a KB file
        MATCH path = (src:Dataset)-[:INPUT_TO|OUTPUTS*1..5]->(target:Dataset)
        WHERE target.namespace = 'gaius.kb'
          AND target.name CONTAINS 'attention_is_all_you_need'
        RETURN src.namespace, src.name

        Args:
            cypher: Cypher query string (read-only - MATCH only)
            limit: Max rows to return (safety limit, default 100)
        """
        import re

        # Security: only allow read queries
        cypher_upper = cypher.upper().strip()
        disallowed = ["CREATE", "DELETE", "REMOVE", "SET", "MERGE", "DROP", "DETACH"]
        for keyword in disallowed:
            if re.search(rf'\b{keyword}\b', cypher_upper):
                return json.dumps({
                    "error": f"Write operations not allowed. Found: {keyword}",
                    "hint": "Only MATCH/RETURN queries are permitted",
                })

        try:
            import asyncpg
            from gaius.core.config import get_config

            config = get_config()
            conn = await asyncpg.connect(config.database.url)

            try:
                # Set up AGE
                await conn.execute("SET search_path = ag_catalog, public")

                # Wrap cypher in SELECT FROM cypher()
                # AGE requires declaring return types, so we use agtype
                # Count columns in RETURN clause to determine result shape
                return_match = re.search(r'\bRETURN\s+(.+?)(?:\s+ORDER\s|\s+LIMIT\s|$)', cypher, re.IGNORECASE | re.DOTALL)
                if not return_match:
                    return json.dumps({
                        "error": "Query must have a RETURN clause",
                        "hint": "Example: MATCH (n) RETURN n.name, n.namespace",
                    })

                return_clause = return_match.group(1).strip()
                # Count commas to estimate column count (rough heuristic)
                # This won't be perfect but AGE allows extra columns
                col_count = return_clause.count(',') + 1

                # Build column declarations
                col_decls = ", ".join([f"c{i} agtype" for i in range(col_count)])

                # Inject LIMIT if not present
                if "LIMIT" not in cypher_upper:
                    cypher = f"{cypher.rstrip().rstrip(';')} LIMIT {limit}"

                # Execute via AGE cypher() function
                age_query = f"""
                    SELECT * FROM cypher('gaius_hx', $cypher$
                        {cypher}
                    $cypher$) AS ({col_decls});
                """

                rows = await conn.fetch(age_query)

                # Parse results
                results = []
                for row in rows:
                    row_data = {}
                    for i, val in enumerate(row.values()):
                        if val is not None:
                            # AGE returns JSON strings for agtype
                            try:
                                import json as json_mod
                                parsed = json_mod.loads(str(val))
                                row_data[f"c{i}"] = parsed
                            except (json.JSONDecodeError, TypeError):
                                row_data[f"c{i}"] = str(val)
                        else:
                            row_data[f"c{i}"] = None
                    results.append(row_data)

                return json.dumps({
                    "query": cypher,
                    "row_count": len(results),
                    "results": results,
                }, indent=2)

            finally:
                await conn.close()

        except Exception as e:
            import traceback
            return json.dumps({
                "error": str(e),
                "traceback": traceback.format_exc(),
                "hint": "Check Cypher syntax. AGE uses openCypher with some limitations.",
            }, indent=2)

    # --- Cloudera Documentation Sync ---

    @server.tool()
    async def sync_cloudera_docs(
        product: str = "all",
        num_gpus: int = 4,
    ) -> str:
        """Sync Cloudera documentation archives to KB.

        Downloads PDF archives from docs.cloudera.com, converts them to
        markdown using docling (GPU-accelerated PDF parsing), and stores
        in the KB under current/cloudera/docs/{product}/{version}/.

        This is a long-running operation. For large archives like CSA
        (~500 PDFs), expect 30-60 minutes depending on GPU availability.

        Args:
            product: Product to sync (csa, csa-operator, or "all" for all archive products)
            num_gpus: Number of GPUs to use for parallel processing (default: 4)
        """
        import asyncio
        import hashlib
        from pathlib import Path
        from datetime import datetime

        try:
            from gaius.flows.cloudera_docs.sources import PRODUCT_SOURCES, SourceType
            from gaius.flows.cloudera_docs.flow import download_archive, extract_doc_files
            from gaius.flows.cloudera_docs.parallel import ParallelDocProcessor

            kb_root = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
            kb_prefix_path = kb_root / "current" / "cloudera" / "docs"

            # Determine which sources to sync
            if product.lower() == "all":
                sources = [s for s in PRODUCT_SOURCES.values() if s.source_type == SourceType.ARCHIVE]
            else:
                source = PRODUCT_SOURCES.get(product.lower())
                if not source:
                    available = [n for n, s in PRODUCT_SOURCES.items() if s.source_type == SourceType.ARCHIVE]
                    return json.dumps({
                        "error": f"Unknown product: {product}",
                        "available_archive_products": available,
                    }, indent=2)
                if source.source_type != SourceType.ARCHIVE:
                    return json.dumps({
                        "error": f"Product {product} uses HTML source, not archive",
                        "source_type": source.source_type.value,
                    }, indent=2)
                sources = [source]

            results = {}
            start_time = datetime.now()

            for source in sources:
                source_start = datetime.now()

                # Download archive
                try:
                    archive_bytes = download_archive(source.archive_url)
                    archive_hash = hashlib.sha256(archive_bytes).hexdigest()[:16]
                except Exception as e:
                    results[source.name] = {
                        "status": "download_failed",
                        "error": str(e),
                    }
                    continue

                # Extract PDFs
                doc_files = extract_doc_files(archive_bytes)
                if not doc_files:
                    results[source.name] = {"status": "no_pdfs"}
                    continue

                # Process documents with parallel GPU processor
                processor = ParallelDocProcessor(
                    workload_id=f"cloudera-docs-{source.name}-sync",
                    product_name=source.name,
                    num_gpus=num_gpus,
                    preemptible=False,
                )

                # Use high-numbered GPUs (avoid reasoning model on 0-3)
                gpu_offset = 4
                gpus = list(range(gpu_offset, gpu_offset + num_gpus))

                def gpu_allocation():
                    return True, gpus
                processor.request_gpu_allocation = gpu_allocation

                result = processor.process_documents(
                    doc_files=doc_files,
                    kb_prefix_path=str(kb_prefix_path),
                    archive_name=source.name,
                    archive_hash=archive_hash,
                    exclude_check=source.should_exclude,
                )

                elapsed = (datetime.now() - source_start).total_seconds()
                results[source.name] = {
                    "status": "completed",
                    "archive_url": source.archive_url,
                    "archive_hash": archive_hash,
                    "total_pdfs": len(doc_files),
                    "completed": result["completed"],
                    "failed": result["failed"],
                    "skipped": result.get("skipped", 0),
                    "elapsed_s": elapsed,
                    "kb_prefix": str(kb_prefix_path / source.name),
                }

            total_elapsed = (datetime.now() - start_time).total_seconds()

            return json.dumps({
                "success": True,
                "products_synced": list(results.keys()),
                "total_elapsed_s": total_elapsed,
                "results": results,
            }, indent=2)

        except Exception as e:
            import traceback
            return json.dumps({
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }, indent=2)

    @server.tool()
    async def list_cloudera_sources() -> str:
        """List available Cloudera documentation sources.

        Shows all configured product sources with their types,
        versions, and archive URLs.
        """
        try:
            from gaius.flows.cloudera_docs.sources import PRODUCT_SOURCES

            sources = []
            for name, source in PRODUCT_SOURCES.items():
                sources.append({
                    "name": name,
                    "display_name": source.display_name,
                    "version": source.version,
                    "source_type": source.source_type.value,
                    "archive_url": source.archive_url,
                    "kb_prefix": source.kb_prefix,
                    "domain": source.domain,
                })

            return json.dumps({
                "sources": sources,
                "total": len(sources),
                "archive_count": sum(1 for s in sources if s["source_type"] == "archive"),
            }, indent=2)

        except Exception as e:
            return json.dumps({"error": str(e)})

    @server.tool()
    async def cloudera_sync_status() -> str:
        """Get status of Cloudera docs sync.

        Shows which products have been synced and document counts.
        """
        import subprocess
        from pathlib import Path

        try:
            kb_root = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
            docs_path = kb_root / "current" / "cloudera" / "docs"

            if not docs_path.exists():
                return json.dumps({
                    "synced": False,
                    "message": "No Cloudera docs synced yet",
                    "kb_path": str(docs_path),
                })

            # Count docs by product
            products = {}
            for product_dir in docs_path.iterdir():
                if product_dir.is_dir():
                    result = subprocess.run(
                        ["find", str(product_dir), "-name", "*.md", "-type", "f"],
                        capture_output=True,
                        text=True,
                    )
                    doc_count = len([l for l in result.stdout.strip().split("\n") if l])
                    products[product_dir.name] = doc_count

            total_docs = sum(products.values())

            return json.dumps({
                "synced": True,
                "kb_path": str(docs_path),
                "total_documents": total_docs,
                "products": products,
            }, indent=2)

        except Exception as e:
            return json.dumps({"error": str(e)})

    @server.tool()
    async def cloudera_sync_progress() -> str:
        """Get real-time progress of running Cloudera docs sync.

        Returns live progress including:
        - Percentage complete
        - Documents completed/failed/remaining
        - Rate (docs/sec) and ETA
        - Recent files processed

        Use this to monitor ongoing sync operations. For CLI display
        with Rich progress bars, run:
            uv run python -c "from gaius.flows.cloudera_docs.progress import watch_progress_rich; watch_progress_rich()"
        """
        try:
            from gaius.flows.cloudera_docs.progress import (
                get_sync_progress,
                format_progress_human,
            )

            progress = get_sync_progress()
            if progress is None:
                return json.dumps({
                    "running": False,
                    "message": "No sync in progress",
                    "hint": "Use sync_cloudera_docs() to start a sync",
                }, indent=2)

            # Include both structured data and human-readable format
            progress["human_display"] = format_progress_human(progress)

            return json.dumps({
                "running": progress.get("status") == "running",
                **progress,
            }, indent=2)

        except Exception as e:
            return json.dumps({"error": str(e)})

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

    # --- Model Addition Workflow Tools ---

    @server.tool()
    async def model_launch_coding(gpus: str = "0,1", timeout: int = 120) -> str:
        """Launch coding model endpoint for code generation.

        Uses engine's ensure_endpoint for proper resource management.
        Called by orchestrator when coding model is needed.

        Args:
            gpus: Comma-separated GPU indices (default "0,1")
            timeout: Seconds to wait for healthy endpoint
        """
        try:
            from .client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

            # Use engine client (agent-first architecture)
            if not use_engine_proxy():
                return json.dumps(
                    {
                        "status": "failed",
                        "error": "Gaius engine not running",
                        "hint": "Start the engine with: gaius-engine start",
                    },
                    indent=2,
                )

            orch = await get_orchestrator_proxy()
            result = await orch.ensure_endpoint("coding")

            if result.get("healthy"):
                return json.dumps(
                    {
                        "status": "started",
                        "model_id": result.get("model"),
                        "port": result.get("port"),
                        "gpu_ids": result.get("gpu_ids", []),
                    },
                    indent=2,
                )
            else:
                return json.dumps(
                    {
                        "status": result.get("status", "failed"),
                        "error": result.get("message", "Failed to start coding endpoint"),
                    },
                    indent=2,
                )
        except Exception as e:
            return json.dumps({"status": "failed", "error": str(e)}, indent=2)

    @server.tool()
    async def model_stop_coding() -> str:
        """Stop coding model endpoint to free GPU resources.

        Called by orchestrator after code generation complete.
        Ensures system returns to healthy baseline state.
        """
        try:
            from .client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

            if not use_engine_proxy():
                return json.dumps(
                    {"status": "skipped", "reason": "Engine not running"},
                    indent=2,
                )

            orch = await get_orchestrator_proxy()
            success = await orch.stop_endpoint("coding")
            return json.dumps(
                {"status": "stopped" if success else "failed"},
                indent=2,
            )
        except Exception as e:
            return json.dumps({"status": "failed", "error": str(e)}, indent=2)

    @server.tool()
    async def model_fetch_hf(model_id: str) -> str:
        """Fetch HuggingFace model metadata.

        Returns API info, config.json, and README excerpt for code generation.

        Args:
            model_id: HuggingFace model ID (e.g., "mistralai/Mistral-7B-Instruct-v0.3")
        """
        try:
            from .agents.modeladd.tools import fetch_hf_model_data

            data = await fetch_hf_model_data(model_id)
            return json.dumps(
                {
                    "model_id": data.model_id,
                    "has_api_info": bool(data.api_info),
                    "has_config": bool(data.config),
                    "has_readme": bool(data.readme),
                    "context_length": data.config.get("max_position_embeddings"),
                    "architectures": data.config.get("architectures", []),
                    "pipeline_tag": data.api_info.get("pipeline_tag"),
                    "tags": data.api_info.get("tags", [])[:10],
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def model_generate_code(
        model_id: str,
        hf_data_json: str = "",
        critic_feedback: str = "",
    ) -> str:
        """Generate ModelSpec Python code via coding model.

        Uses local coding endpoint (via engine) or XAI Grok fallback.
        Optionally incorporates critic feedback for regeneration attempts.

        Args:
            model_id: HuggingFace model ID
            hf_data_json: JSON string with HF data (from model_fetch_hf)
            critic_feedback: Feedback from previous failed attempt
        """
        try:
            from .agents.modeladd.tools import (
                fetch_hf_model_data,
                generate_modelspec_code,
                HFModelData,
            )
            from .agents.modeladd.prompts import MODELSPEC_SYSTEM_PROMPT
            import os

            # Get or fetch HF data
            if hf_data_json:
                data = json.loads(hf_data_json)
                hf_data = HFModelData(
                    model_id=data.get("model_id", model_id),
                    api_info=data.get("api_info", {}),
                    config=data.get("config", {}),
                    readme=data.get("readme"),
                )
            else:
                hf_data = await fetch_hf_model_data(model_id)

            # Get coding endpoint via engine (agent-first)
            from .client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

            if use_engine_proxy():
                orch = await get_orchestrator_proxy()
                result = await orch.ensure_endpoint("coding")
                if result.get("healthy"):
                    port = result.get("port", 8082)
                    endpoint_url = f"http://localhost:{port}/v1"
                    coding_model = result.get("model", "coding")
                elif os.getenv("XAI_API_KEY"):
                    endpoint_url = "https://api.x.ai/v1"
                    coding_model = "grok-2-latest"
                else:
                    return json.dumps(
                        {"error": "Coding endpoint not healthy and XAI_API_KEY not set"},
                        indent=2,
                    )
            elif os.getenv("XAI_API_KEY"):
                endpoint_url = "https://api.x.ai/v1"
                coding_model = "grok-2-latest"
            else:
                return json.dumps(
                    {"error": "No coding endpoint available and XAI_API_KEY not set"},
                    indent=2,
                )

            result = await generate_modelspec_code(
                hf_data=hf_data,
                endpoint_url=endpoint_url,
                model_id=coding_model,
                system_prompt=MODELSPEC_SYSTEM_PROMPT,
                critic_feedback=critic_feedback or None,
            )

            return json.dumps(
                {
                    "code": result.code,
                    "model_used": result.model_used,
                    "endpoint_used": result.endpoint_used,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def model_validate_code(code: str, use_devenv: bool = False) -> str:
        """Validate generated ModelSpec code in isolated environment.

        Runs syntax check, import test, and serve_command validation.

        Args:
            code: The generated Python code to validate
            use_devenv: If True, use devenv container for stronger isolation
        """
        try:
            from .agents.modeladd.sandbox import validate_modelspec_code

            result = validate_modelspec_code(code, use_devenv=use_devenv)
            return json.dumps(
                {
                    "valid": result.is_valid,
                    "syntax": result.syntax,
                    "imports": result.imports,
                    "serve_cmd": result.serve_cmd,
                    "variable_name": result.variable_name,
                    "warnings": result.warnings,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def model_xai_critique(code: str, model_id: str) -> str:
        """Get XAI Grok critique of generated ModelSpec code.

        Returns quality score, issues found, and suggestions.
        Budget-limited - uses tiered evaluation tracking.

        Args:
            code: The generated Python code to critique
            model_id: HuggingFace model ID for context
        """
        try:
            from .agents.modeladd.tools import (
                critique_modelspec_code,
                fetch_hf_model_data,
            )

            hf_data = await fetch_hf_model_data(model_id)
            result = await critique_modelspec_code(code, hf_data)

            return json.dumps(
                {
                    "score": result.score,
                    "issues": result.issues,
                    "suggestions": result.suggestions,
                    "approved": result.approved,
                    "model_used": result.model_used,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def model_save_pending(
        model_id: str,
        code: str,
        validation_json: str,
        critique_json: str = "",
    ) -> str:
        """Save generated code for user confirmation.

        Persists to .pending_model_add.json for /model add-confirm.

        Args:
            model_id: HuggingFace model ID
            code: Validated Python code
            validation_json: JSON validation results from model_validate_code
            critique_json: Optional JSON critique results from model_xai_critique
        """
        try:
            from pathlib import Path
            from datetime import datetime

            validation = json.loads(validation_json) if validation_json else {}
            critique = json.loads(critique_json) if critique_json else {}

            pending_data = {
                "model_id": model_id,
                "code": code,
                "validation": validation,
                "critique": critique,
                "generated_at": datetime.now().isoformat(),
            }

            # Get KB root from config
            try:
                from .config import get_config

                config = get_config()
                pending_path = Path(config.kb.root) / ".pending_model_add.json"
            except Exception:
                pending_path = Path("build/dev/.pending_model_add.json")

            pending_path.parent.mkdir(parents=True, exist_ok=True)
            pending_path.write_text(json.dumps(pending_data, indent=2))

            return json.dumps(
                {
                    "status": "saved",
                    "path": str(pending_path),
                    "model_id": model_id,
                    "variable_name": validation.get("variable_name"),
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def model_add_status() -> str:
        """Get status of pending model addition.

        Returns current state from .pending_model_add.json if exists.
        """
        try:
            from pathlib import Path

            # Get KB root from config
            try:
                from .config import get_config

                config = get_config()
                pending_path = Path(config.kb.root) / ".pending_model_add.json"
            except Exception:
                pending_path = Path("build/dev/.pending_model_add.json")

            if not pending_path.exists():
                return json.dumps({"pending": False}, indent=2)

            data = json.loads(pending_path.read_text())
            return json.dumps(
                {
                    "pending": True,
                    "model_id": data.get("model_id"),
                    "variable_name": data.get("validation", {}).get("variable_name"),
                    "validation_passed": data.get("validation", {}).get("imports", False),
                    "critique_score": data.get("critique", {}).get("score"),
                    "next_steps": [
                        "/model add-confirm  - Commit to registry",
                        "/model add-cancel   - Discard",
                    ],
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- Reasoning Operations ---

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

        Uses ColNomic multi-vector embeddings with MaxSim late-interaction
        scoring for high-quality semantic retrieval via the engine gRPC.

        Args:
            query: Search query
            collection: Collection to search (kb, research, etc.)
            limit: Maximum results
        """
        try:
            client = await _get_engine_client()
            if client is None:
                return json.dumps(
                    {"error": "Engine not available. Start with: devenv processes up"},
                    indent=2,
                )

            result = await client.call(
                "Search",
                "semantic",
                {
                    "query": query,
                    "collection": collection,
                    "limit": limit,
                    "use_maxsim": True,
                },
            )
            return json.dumps(result, indent=2)
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
            from .client.engine_proxy import get_scheduler_proxy, use_engine_proxy
            from .agents.roles import AgentRole

            if not use_engine_proxy():
                return json.dumps({"error": "Gaius engine not running. Start with: devenv up -d"}, indent=2)

            # Select subset of roles based on num_agents
            all_roles = [r.value for r in AgentRole]
            roles = all_roles[:num_agents] if num_agents < len(all_roles) else None  # None = default roles

            scheduler = await get_scheduler_proxy()
            # run_swarm now returns (results, saved_path) tuple
            raw_results, saved_path = await scheduler.run_swarm(
                domain=domain or query,
                context=query,
                roles=roles,
            )

            # Convert engine response format
            perspectives = []
            total_tokens = 0
            total_latency = 0
            synthesis = ""

            for role_name, data in raw_results.items():
                tokens = data.get("input_tokens", 0) + data.get("output_tokens", 0)
                succeeded = data.get("status") == "completed"
                content = data.get("content", "")

                perspectives.append({
                    "agent": role_name,
                    "role": role_name.lower(),
                    "analysis": content[:500] + "..." if len(content) > 500 else content,
                    "tokens": tokens,
                    "succeeded": succeeded,
                })
                total_tokens += tokens
                total_latency += data.get("latency_ms", 0)

                # Extract synthesis from Leader
                if role_name == "Leader" and succeeded:
                    synthesis = content

            success_count = sum(1 for p in perspectives if p["succeeded"])
            success_rate = success_count / len(perspectives) if perspectives else 0.0

            return json.dumps(
                {
                    "query": query,
                    "domain": domain or query,
                    "synthesis": synthesis,
                    "perspectives": perspectives,
                    "success_rate": success_rate,
                    "tokens_used": total_tokens,
                    "latency_ms": total_latency,
                    "saved_to": saved_path,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    # --- MetaAgent Operations ---

    @server.tool()
    async def metaagent_query(
        query: str,
        domains: str = "",
        include_dot: bool = True,
        include_markdown: bool = True,
    ) -> str:
        """Run multi-agent analytics query.

        MetaAgent coordinates specialist agents to answer natural language
        questions by correlating data from multiple sources:
        - Lineage: AGE graph for data provenance (Cypher queries)
        - Operations: Flow runs, agent performance (SQL on meta.flow_runs)
        - Resources: GPU utilization, inference throughput (SQL on meta.*)
        - Topology: Document clusters, semantic regions (SQL on meta.kb_topology)

        Args:
            query: Natural language question (e.g., "Why are arxiv flows slow?")
            domains: Comma-separated filter (lineage,ops,resources,topology) - empty for all
            include_dot: Generate GraphViz DOT output for visualization
            include_markdown: Generate Markdown tables for evidence

        Returns:
            JSON with answer, evidence, DOT graph, and agent insights
        """
        try:
            client = await _get_engine_client()
            if not client:
                return json.dumps(
                    {"error": "Gaius engine not running. Start with: devenv up -d"},
                    indent=2,
                )

            # Parse domains
            domain_list = [d.strip() for d in domains.split(",") if d.strip()] if domains else []

            # Call engine gRPC
            result = await client.call(
                "Gaius",
                "MetaAgentQuery",
                {
                    "query": query,
                    "domains": domain_list,
                    "include_dot": include_dot,
                    "include_markdown": include_markdown,
                },
            )

            # Format response
            return json.dumps(
                {
                    "success": result.get("success", False),
                    "answer": result.get("answer", ""),
                    "dot_graph": result.get("dot_graph", ""),
                    "markdown_tables": result.get("markdown_tables", []),
                    "queries_executed": result.get("queries_executed", []),
                    "agents_used": result.get("agents_used", 0),
                    "duration_ms": result.get("duration_ms", 0),
                    "error": result.get("error", ""),
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
        Uses gaius-engine if available (GAIUS_ALLOW_FALLBACKS=true), otherwise direct access.
        """
        try:
            # Try engine proxy first
            client = await _get_engine_client()
            if client:
                status = await client.call("Scheduler", "status", {})
                return json.dumps(status, indent=2, default=str)

            # Fall back to direct access
            import warnings
            warnings.warn(
                "LEGACY_FALLBACK: scheduler_status using direct scheduler access instead of engine. "
                "Start gaius-engine for proper resource management.",
                DeprecationWarning,
                stacklevel=2,
            )
            logger.warning("LEGACY_FALLBACK: scheduler_status bypassing engine - tech debt")

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
            from .client.engine_proxy import get_scheduler_proxy, use_engine_proxy

            if not use_engine_proxy():
                return json.dumps({"error": "Gaius engine not running. Start with: devenv up -d"}, indent=2)

            scheduler = await get_scheduler_proxy()

            # Parse roles
            role_list = None
            if roles:
                role_list = [r.strip() for r in roles.split(",")]

            # run_swarm now returns (results, saved_path) tuple
            raw_results, saved_path = await scheduler.run_swarm(
                domain=domain,
                context=context,
                roles=role_list,
            )

            # Format results
            output = {
                "domain": domain,
                "agents": {},
                "summary": {
                    "total": len(raw_results),
                    "completed": sum(1 for r in raw_results.values() if r.get("status") == "completed"),
                    "failed": sum(1 for r in raw_results.values() if r.get("status") == "failed"),
                },
                "saved_to": saved_path,
            }

            for role_name, result in raw_results.items():
                content = result.get("content", "")
                output["agents"][role_name] = {
                    "status": result.get("status", "unknown"),
                    "content": content[:500] + "..." if len(content) > 500 else content,
                    "model": result.get("model", ""),
                    "endpoint": result.get("endpoint", ""),
                    "latency_ms": result.get("latency_ms", 0),
                    "error": result.get("error"),
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
        Uses gaius-engine if available (GAIUS_ALLOW_FALLBACKS=true), otherwise direct access.
        """
        try:
            # Try engine proxy first
            client = await _get_engine_client()
            if client:
                status = await client.call("Orchestrator", "status", {})
                return json.dumps(status, indent=2, default=str)

            # Fall back to direct access
            import warnings
            warnings.warn(
                "LEGACY_FALLBACK: orchestrator_status using direct orchestrator instead of engine. "
                "Start gaius-engine for proper resource management.",
                DeprecationWarning,
                stacklevel=2,
            )
            logger.warning("LEGACY_FALLBACK: orchestrator_status bypassing engine - tech debt")

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
            from .client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

            # Use engine client (agent-first architecture)
            if use_engine_proxy():
                orch = await get_orchestrator_proxy()
                endpoint_list = [e.strip() for e in endpoints.split(",") if e.strip()]
                results = await orch.clean_start(endpoint_list or ["reasoning"])
                return json.dumps(results, indent=2, default=str)

            # Fallback to legacy
            logger.warning("LEGACY_FALLBACK: orchestrator_clean_start bypassing engine - tech debt")
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

        Uses engine's ensure_endpoint for proper resource management.

        Args:
            endpoint: Endpoint name to start (empty string starts all configured endpoints)
        """
        try:
            from .client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

            # Use engine client (agent-first architecture)
            if use_engine_proxy():
                orch = await get_orchestrator_proxy()

                if endpoint:
                    result = await orch.ensure_endpoint(endpoint)
                    return json.dumps(
                        {
                            "endpoint": endpoint,
                            "started": result.get("healthy", False),
                            "status": result.get("status", "unknown"),
                            "port": result.get("port"),
                            "gpu_ids": result.get("gpu_ids", []),
                            "message": result.get("message", ""),
                        },
                        indent=2,
                    )
                else:
                    # Start all returns status for all endpoints
                    success = await orch.start_endpoint("")
                    return json.dumps(
                        {"action": "start_all", "success": success},
                        indent=2,
                    )

            # Fallback to legacy
            logger.warning("LEGACY_FALLBACK: orchestrator_start bypassing engine - tech debt")
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
            from .client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

            # Use engine client (agent-first architecture)
            if use_engine_proxy():
                orch = await get_orchestrator_proxy()

                if endpoint:
                    success = await orch.stop_endpoint(endpoint)
                    return json.dumps(
                        {"endpoint": endpoint, "stopped": success},
                        indent=2,
                    )
                else:
                    success = await orch.stop_endpoint("")
                    return json.dumps(
                        {"action": "stop_all", "stopped": success},
                        indent=2,
                    )

            # Fallback to legacy
            logger.warning("LEGACY_FALLBACK: orchestrator_stop bypassing engine - tech debt")
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
            from .client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

            # Use engine client (agent-first architecture)
            if use_engine_proxy():
                orch = await get_orchestrator_proxy()
                success = await orch.restart_endpoint(endpoint)
                # Get status after restart
                status = await orch.get_endpoint_status(endpoint)
                return json.dumps(
                    {
                        "endpoint": endpoint,
                        "restarted": success,
                        "status": status.get("status", "unknown") if status else "unknown",
                        "port": status.get("port") if status else None,
                    },
                    indent=2,
                )

            # Fallback to legacy
            logger.warning("LEGACY_FALLBACK: orchestrator_restart bypassing engine - tech debt")
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
            from .client.engine_proxy import get_orchestrator_proxy, use_engine_proxy

            # Use engine client (agent-first architecture)
            if use_engine_proxy():
                orch = await get_orchestrator_proxy()
                logs = await orch.get_logs_async(endpoint, lines=lines)
                return json.dumps(
                    {
                        "endpoint": endpoint,
                        "lines": len(logs) if logs else 0,
                        "logs": logs or [],
                    },
                    indent=2,
                )

            # Fallback to legacy
            logger.warning("LEGACY_FALLBACK: orchestrator_logs bypassing engine - tech debt")
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
        Uses gaius-engine if available (GAIUS_ALLOW_FALLBACKS=true), otherwise direct access.
        """
        try:
            # Try engine proxy first
            client = await _get_engine_client()
            if client:
                health = await client.call("Health", "gpu_detailed", {})
                return json.dumps(health, indent=2, default=str)

            # Fall back to direct access
            logger.warning("LEGACY_FALLBACK: gpu_health bypassing engine - tech debt")
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

    # --- FMEA Operations ---
    # Failure Mode and Effects Analysis for RPN-based risk assessment

    @server.tool()
    async def fmea_catalog(category: str = "") -> str:
        """List FMEA failure modes from the catalog.

        Shows all failure modes with their base RPN scores.

        Args:
            category: Filter by category (gpu, vllm, model_quality, evolution, emergent, resource, infra)
        """
        try:
            from .health.fmea import FMEAEngine

            engine = FMEAEngine()
            client = await _get_engine_client()

            if not client:
                return json.dumps({"error": "Database not available"}, indent=2)

            pool = await client._get_pool() if hasattr(client, "_get_pool") else None
            if pool:
                async with pool.acquire() as conn:
                    if category:
                        from .health.fmea.loader import get_failure_modes_by_category
                        modes = await get_failure_modes_by_category(conn, category)
                    else:
                        from .health.fmea.loader import load_all_failure_modes
                        modes = await load_all_failure_modes(conn)

                    return json.dumps({
                        "total": len(modes),
                        "failure_modes": [m.to_dict() for m in modes],
                    }, indent=2)
            else:
                return json.dumps({"error": "Database pool not available"}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def fmea_calculate_rpn(failure_mode_id: str, context: str = "{}") -> str:
        """Calculate RPN score for a failure mode with context.

        RPN = Severity × Occurrence × Detection (max 1000)

        Args:
            failure_mode_id: Failure mode ID (e.g., GPU_001, VLLM_001)
            context: JSON context for score adjustments (e.g., {"unhealthy_endpoints": ["reasoning"]})
        """
        try:
            from .health.fmea import FMEAEngine

            engine = FMEAEngine()
            context_dict = json.loads(context) if context else {}

            rpn = await engine.calculate_rpn(
                failure_mode_id,
                context=context_dict,
            )

            # Get policy
            policy = engine.determine_action(rpn)

            # Get KB heuristic if available
            heuristic = await engine.get_heuristics_for_failure_mode(failure_mode_id)

            result = {
                "rpn_score": rpn.to_dict(),
                "policy": policy.to_dict(),
            }

            if heuristic.get("found"):
                result["heuristic"] = {
                    "path": heuristic.get("path"),
                    "automation_level": heuristic.get("automation_level"),
                    "symptom": heuristic.get("symptom", "")[:200],  # Truncate
                }

            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def fmea_get_controls(failure_mode_id: str) -> str:
        """Get FMEA controls from KB heuristics for a failure mode.

        Extracts preventive, detective, and mitigative controls from
        the KB heuristics that map to the specified failure mode.

        Args:
            failure_mode_id: Failure mode ID (e.g., GPU_001, VLLM_001)
        """
        try:
            from .health.fmea import FMEAEngine

            engine = FMEAEngine()

            # Get controls from heuristic
            controls = await engine.get_controls_from_heuristic(failure_mode_id)

            # Get full heuristic info
            heuristic = await engine.get_heuristics_for_failure_mode(failure_mode_id)

            result = {
                "failure_mode_id": failure_mode_id,
                "controls": controls,
            }

            if heuristic.get("found"):
                result["heuristic_path"] = heuristic.get("path")
                result["automation_level"] = heuristic.get("automation_level")
                result["symptom"] = heuristic.get("symptom", "")[:300]
                result["cause"] = heuristic.get("cause", "")[:300]

            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def fmea_map_health_check(check_name: str) -> str:
        """Map a health check name to its FMEA failure mode.

        Args:
            check_name: Name of the health check (e.g., gpu_memory, stuck_endpoints)
        """
        try:
            from .health.fmea import map_health_check_to_failure_mode, HEALTH_CHECK_TO_FMEA

            failure_mode_id = map_health_check_to_failure_mode(check_name)

            if not failure_mode_id:
                return json.dumps({
                    "check_name": check_name,
                    "failure_mode_id": None,
                    "message": f"No FMEA mapping found for '{check_name}'",
                    "available_mappings": list(HEALTH_CHECK_TO_FMEA.keys()),
                }, indent=2)

            return json.dumps({
                "check_name": check_name,
                "failure_mode_id": failure_mode_id,
            }, indent=2)
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
        Uses gaius-engine if available (GAIUS_ALLOW_FALLBACKS=true), otherwise direct access.
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
    async def trigger_task_ideation(
        max_concepts: int = 2,
        min_novelty: float = 0.5,
    ) -> str:
        """Trigger a task ideation cycle to generate new reasoning tasks.

        Analyzes capability gaps and generates novel task concepts
        that can be converted to Nous Research format for training.

        Args:
            max_concepts: Maximum task concepts to generate per cycle
            min_novelty: Minimum novelty threshold (0-1) for accepting tasks
        """
        try:
            from .agents.evolution import get_evolution_daemon

            daemon = get_evolution_daemon()
            drafts = await daemon.force_ideation_cycle()

            # Format results
            results = []
            for draft in drafts:
                results.append({
                    "name": draft.name,
                    "description": draft.description[:200] if draft.description else None,
                    "modality": draft.modality,
                    "tags": draft.tags,
                    "example_count": len(draft.examples),
                })

            return json.dumps(
                {
                    "success": True,
                    "drafts_generated": len(drafts),
                    "drafts": results,
                    "message": f"Generated {len(drafts)} task drafts"
                    if drafts
                    else "No novel tasks generated (may need more capability gaps)",
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def get_capability_gaps() -> str:
        """Analyze capability coverage gaps in the reasoning task pool.

        Returns analysis of which capabilities are underrepresented
        in the current task pool, guiding task ideation priorities.
        """
        try:
            from .agents.evolution import get_task_ideation_agent

            agent = await get_task_ideation_agent()
            gap_analysis = await agent.identify_gaps(refresh=True)

            # Calculate coverage from taxonomy
            all_capabilities = set()
            for caps in agent.CAPABILITY_TAXONOMY.values():
                all_capabilities.update(caps)
            total = len(all_capabilities)
            covered = len(gap_analysis.existing_capabilities)

            return json.dumps(
                {
                    "total_capabilities": total,
                    "covered_count": covered,
                    "coverage_percent": round(covered / total * 100, 1) if total > 0 else 0,
                    "existing_categories": sorted(gap_analysis.existing_categories)[:10],
                    "identified_gaps": gap_analysis.identified_gaps[:10],
                    "gap_rationales": dict(list(gap_analysis.gap_rationales.items())[:5]),
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def trigger_model_merge(agent_id: str = "") -> str:
        """Trigger a model merge cycle for agent versions.

        Merges top-performing agent versions using TIES/DARE algorithms
        to create improved combined models. Records lineage in the database.

        Args:
            agent_id: Specific agent to merge (empty for all agents)
        """
        try:
            from .agents.evolution import get_evolution_daemon

            daemon = get_evolution_daemon()
            results = await daemon.force_merge_cycle(agent_id if agent_id else None)

            # Summarize results
            successful = sum(1 for r in results.values() if r.get("success"))
            total = len(results)

            return json.dumps(
                {
                    "success": True,
                    "agents_merged": successful,
                    "total_attempted": total,
                    "results": results,
                    "message": (
                        f"Merged {successful}/{total} agents"
                        if successful
                        else "No agents had enough candidates for merging"
                    ),
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def get_merge_candidates(agent_id: str) -> str:
        """Get candidate versions available for merging.

        Shows which agent versions have sufficient scores and evaluations
        to be considered for model merging.

        Args:
            agent_id: Agent to check candidates for
        """
        try:
            from .agents.evolution import get_merge_coordinator

            coordinator = get_merge_coordinator()
            candidates = await coordinator.get_merge_candidates(agent_id)

            return json.dumps(
                {
                    "agent_id": agent_id,
                    "candidate_count": len(candidates),
                    "candidates": candidates,
                    "message": (
                        f"Found {len(candidates)} candidates for merging"
                        if candidates
                        else "Not enough high-quality versions for merging"
                    ),
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def get_model_lineage(model_id: str) -> str:
        """Get lineage information for a model.

        Shows the ancestry of a model, including parent models
        and merge operations that created it.

        Args:
            model_id: Model ID to trace lineage for
        """
        try:
            from .models.lineage import get_lineage_tracker

            tracker = get_lineage_tracker()
            lineage = await tracker.get_model_lineage(model_id)

            return json.dumps(
                {
                    "model_id": model_id,
                    "lineage_events": len(lineage),
                    "lineage": lineage,
                },
                indent=2,
                default=str,  # Handle datetime serialization
            )
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

    # --- RASE Calibration ---

    @server.tool()
    async def calibration_status(agent_id: str = "") -> str:
        """Get calibration status for an agent or all agents.

        Shows calibration health including drift detection, score correlation,
        and whether recalibration is needed.

        Args:
            agent_id: Specific agent (empty for all agents)
        """
        try:
            # Query calibration_health view
            query = """
                SELECT * FROM calibration_health
            """
            if agent_id:
                query += f" WHERE agent_id = '{agent_id}'"

            from .storage.database import _get_pool

            pool = await _get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(query)

            results = []
            for row in rows:
                results.append({
                    "agent_id": row["agent_id"],
                    "total_calibrations": row["total_calibrations"],
                    "drift_count": row["drift_count"],
                    "avg_delta": round(row["avg_delta"], 3) if row["avg_delta"] else 0,
                    "max_abs_delta": round(row["max_abs_delta"], 3) if row["max_abs_delta"] else 0,
                    "score_correlation": round(row["score_correlation"], 3) if row["score_correlation"] else None,
                    "calibration_status": row["calibration_status"],
                    "last_calibration": row["last_calibration"].isoformat() if row["last_calibration"] else None,
                })

            return json.dumps(
                {"agents": results, "total": len(results)},
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def trigger_calibration(
        agent_id: str,
        objective_name: str = "research-synthesis-verification",
        provider: str = "cerebras",
    ) -> str:
        """Trigger a calibration cycle for an agent.

        Runs verification with both local and frontier model to compare scores.
        Records results in the calibration database for drift analysis.

        Args:
            agent_id: Agent to calibrate
            objective_name: Objective to use for verification
            provider: Frontier model provider (cerebras, xai)
        """
        try:
            from .agents.evolution import get_calibration_oracle

            oracle = await get_calibration_oracle()

            # Run calibration
            result = await oracle.run_calibration_cycle(
                agent_id=agent_id,
                objective_name=objective_name,
                provider=provider,
            )

            return json.dumps(
                {
                    "agent_id": agent_id,
                    "objective": objective_name,
                    "provider": result.external_provider,
                    "local_score": round(result.intrinsic_scores[0], 3) if result.intrinsic_scores else 0,
                    "calibration_score": round(result.external_scores[0], 3) if result.external_scores else 0,
                    "correlation": round(result.correlation, 3),
                    "bias": round(result.bias, 3),
                    "drift_detected": result.drift_detected,
                    "drift_severity": result.drift_severity,
                    "duration_ms": result.duration_ms,
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def calibration_history(agent_id: str = "", limit: int = 20) -> str:
        """Get calibration history for an agent.

        Shows recent calibration runs with scores and drift status.

        Args:
            agent_id: Specific agent (empty for all)
            limit: Maximum records to return
        """
        try:
            query = """
                SELECT
                    id, agent_id, version_id, objective_name,
                    provider, model_id,
                    local_score, calibration_score, delta,
                    drift_detected, drift_magnitude,
                    created_at, latency_ms
                FROM evolution_calibrations
            """
            if agent_id:
                query += f" WHERE agent_id = '{agent_id}'"
            query += f" ORDER BY created_at DESC LIMIT {limit}"

            from .storage.database import _get_pool

            pool = await _get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(query)

            results = []
            for row in rows:
                results.append({
                    "id": row["id"],
                    "agent_id": row["agent_id"],
                    "objective": row["objective_name"],
                    "provider": row["provider"],
                    "local_score": round(row["local_score"], 3),
                    "calibration_score": round(row["calibration_score"], 3),
                    "delta": round(row["delta"], 3),
                    "drift_detected": row["drift_detected"],
                    "created_at": row["created_at"].isoformat(),
                })

            return json.dumps({"calibrations": results}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def list_objectives() -> str:
        """List available RASE objectives in the KB.

        Returns all objectives with their gates and priority.
        """
        try:
            from pathlib import Path
            from .rase.domains.kb import Objective

            kb_root = Path(KB_ROOT)
            objectives_dir = kb_root / "current" / "objectives"

            objectives = []
            for obj_file in objectives_dir.glob("*.md"):
                if obj_file.name.startswith("."):
                    continue
                try:
                    rel_path = obj_file.relative_to(kb_root)
                    obj = Objective.from_file(str(rel_path), kb_root=str(kb_root))
                    objectives.append({
                        "name": obj.name,
                        "description": obj.frontmatter.description,
                        "priority": obj.frontmatter.priority,
                        "gates": len(obj.gates),
                        "gate_names": [g.name for g in obj.gates],
                        "path": str(rel_path),
                    })
                except Exception:
                    pass

            return json.dumps(
                {"objectives": objectives, "total": len(objectives)},
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def verification_history(
        objective_name: str = "",
        limit: int = 20,
    ) -> str:
        """Get verification run history.

        Shows recent verification runs with verdicts and accuracy.

        Args:
            objective_name: Filter by objective (empty for all)
            limit: Maximum records to return
        """
        try:
            query = """
                SELECT
                    run_id, objective_name, domain,
                    document_path, verdict, accuracy, reward,
                    gates_total, gates_passed,
                    thread_id, started_at, duration_ms
                FROM objective_verifications
            """
            if objective_name:
                query += f" WHERE objective_name = '{objective_name}'"
            query += f" ORDER BY started_at DESC LIMIT {limit}"

            from .storage.database import _get_pool

            pool = await _get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(query)

            results = []
            for row in rows:
                results.append({
                    "run_id": row["run_id"],
                    "objective": row["objective_name"],
                    "document": row["document_path"],
                    "verdict": row["verdict"],
                    "accuracy": round(row["accuracy"], 3),
                    "reward": round(row["reward"], 3),
                    "gates": f"{row['gates_passed']}/{row['gates_total']}",
                    "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                })

            return json.dumps({"verifications": results}, indent=2)
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

    # --- AIOps / MLOps Tools ---

    @server.tool()
    async def aiops_report() -> str:
        """Generate AIOps health report with action links.

        Creates a KB scratch document with GPU health, endpoint status,
        and action links for remediation. Returns the report path.
        """
        try:
            from .cli import GaiusCLI
            cli = GaiusCLI()
            result = await cli._generate_aiops_report()
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def aiops_status() -> str:
        """Get pending AIOps remediation approvals.

        Shows high-severity actions awaiting user approval.
        """
        try:
            from .cli import GaiusCLI
            cli = GaiusCLI()
            result = await cli._aiops_pending_approvals()
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def aiops_approve(approval_id: int) -> str:
        """Approve a pending AIOps remediation action.

        Args:
            approval_id: ID of the approval to confirm
        """
        try:
            from .cli import GaiusCLI
            cli = GaiusCLI()
            result = await cli._aiops_approve(str(approval_id))
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def aiops_history() -> str:
        """Get recent AIOps event history.

        Shows infrastructure health events and remediations.
        """
        try:
            from .cli import GaiusCLI
            cli = GaiusCLI()
            result = await cli._aiops_history()
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def mlops_report() -> str:
        """Generate MLOps model lifecycle report.

        Creates a KB scratch document with agent versions, evolution status,
        and action links for model management. Returns the report path.
        """
        try:
            from .cli import GaiusCLI
            cli = GaiusCLI()
            result = await cli._generate_mlops_report()
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def mlops_agents() -> str:
        """Get agent version status.

        Shows active versions, scores, and evaluation counts.
        """
        try:
            from .cli import GaiusCLI
            cli = GaiusCLI()
            result = await cli._mlops_agent_status()
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def mlops_evolution() -> str:
        """Get evolution daemon status and metrics.

        Shows daemon state, cycle counts, and GPU utilization.
        """
        try:
            from .cli import GaiusCLI
            cli = GaiusCLI()
            result = await cli._mlops_evolution_metrics()
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def mlops_promote(version_id: str) -> str:
        """Promote an agent version to active.

        Args:
            version_id: Version ID to promote
        """
        try:
            from .cli import GaiusCLI
            cli = GaiusCLI()
            result = await cli._mlops_promote(version_id)
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    @server.tool()
    async def mlops_history() -> str:
        """Get recent MLOps event history.

        Shows model lifecycle events like promotions, rollbacks, drift detection.
        """
        try:
            from .cli import GaiusCLI
            cli = GaiusCLI()
            result = await cli._mlops_history()
            return json.dumps(result, indent=2, default=str)
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
    # Initialize telemetry early with MCP entry point
    try:
        from .core.config import get_config
        from .core.telemetry import init_from_config
        config = get_config()
        init_from_config(config, entry_point="mcp")
    except Exception:
        pass  # Telemetry init failure is non-fatal

    ensure_mcp()
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
