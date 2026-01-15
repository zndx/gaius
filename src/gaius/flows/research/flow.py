"""ResearchFlow - SOTA deep research with MemRL and swarm analysis.

Implements multi-pass research with Q-value learning on episodic memory:
1. start → Initialize and emit lineage
2. retrieve_memories → MemRL Phase A+B retrieval
3. search_fan_out → Fan out to parallel search types
4. run_search → Execute individual search (BM25 || Vector || Web in PARALLEL)
5. join_searches → Merge parallel search results
6. analyze_pass → 7-agent swarm analysis
7. synthesize_pass → Grok synthesis + merge perspectives
8. evaluate_pass → Compute reward signal + MemRL Bellman update
9. checkpoint_pass → Persist state + convergence check (recursive or proceed to final)
10. final_synthesis → Grok comprehensive report generation
11. write_kb → Persist research artifact with MemRL frontmatter
12. end → Report and emit lineage

Uses Metaflow foreach pattern for parallel searches and conditional dictionary
for multi-pass loop control. Progress events are printed to stdout for
ResearchWorkloadService to parse.

Guru Meditation Codes:
- #RF.00000001.MEMRETRIEVE: Memory retrieval failed
- #RF.00000002.SWARMFAIL: Swarm agent execution failed
- #RF.00000003.GROKFAIL: XAI API error
- #RF.00000004.EVALFAIL: Reward computation failed
- #RF.00000005.QUPDATE: Q-value update failed
- #RF.00000006.CONVERGEFAIL: Convergence check failed
- #RF.00000007.FLOWFAIL: Metaflow execution failed
- #RF.00000008.BM25FAIL: BM25 search failed
- #RF.00000009.VECSEARCHFAIL: Vector search failed
- #RF.00000010.WEBSEARCHFAIL: Web search failed
- #RF.00000011.FINALSYNTHFAIL: Final Grok synthesis failed
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from metaflow import FlowSpec, Parameter, step

from gaius.agents.metaagent.telemetry import TracedFlow, traced_step
from gaius.flows import register_flow
from gaius.flows.base import GaiusFlow, safe_filename
from gaius.flows.config import apply_metaflow_config
from gaius.hx.lineage.events import Dataset

from gaius.flows.research import (
    ResearchError,
    SearchError,
    SynthesisError,
)
from gaius.flows.research.convergence import ConvergenceTracker, PassResult, compute_centroid
from gaius.flows.research.memory import (
    ResearchMemory,
    RewardComponents,
    retrieve_memories,
    save_memory,
    update_related_memories,
)
from gaius.flows.research.progress import emit_progress
from gaius.flows.research.reward import compute_reward

logger = logging.getLogger(__name__)

# Research specialist agent roles
RESEARCH_PERSPECTIVES = [
    "Leader",  # Synthesis coordinator
    "Risk",  # Identifies gaps, limitations, counterarguments
    "Optimizer",  # Efficiency, practical applications
    "Opportunity",  # Novel connections, future directions
    "Domain",  # Domain-specific expertise
    "Analyst",  # Data-driven insights, evidence quality
    "Generalist",  # Cross-domain connections
]


@register_flow("research")
class ResearchFlow(TracedFlow, GaiusFlow):
    """Deep research with MemRL and multi-pass convergence.

    Uses Metaflow foreach pattern for parallel searches and conditional
    dictionary for multi-pass loop control:
    - search_fan_out fans out to parallel BM25/Vector/Web searches
    - join_searches merges results
    - checkpoint_pass persists state and checks convergence
    - Convergence uses conditional dictionary: {True: final, False: search_fan_out}

    Steps:
    1. start → Initialize and emit lineage
    2. retrieve_memories → MemRL Phase A+B retrieval
    3. search_fan_out → Fan out to 3 parallel search types
    4. run_search → Execute BM25 || Vector || Web in parallel
    5. join_searches → Merge parallel search results
    6. analyze_pass → 7-agent swarm analysis
    7. synthesize_pass → Grok synthesis + merge perspectives
    8. evaluate_pass → Reward computation + Q-value update
    9. checkpoint_pass → Persist state, convergence check → loop or final
    10. final_synthesis → Grok comprehensive report
    11. write_kb → Create zettelkasten with MemRL frontmatter
    12. end → Report and emit lineage
    """

    query = Parameter(
        "query",
        help="Research query",
        required=True,
    )

    max_passes = Parameter(
        "max_passes",
        help="Maximum research passes",
        default=5,
        type=int,
    )

    drift_threshold = Parameter(
        "drift_threshold",
        help="Convergence drift threshold",
        default=0.15,
        type=float,
    )

    bm25_limit = Parameter(
        "bm25_limit",
        help="BM25 result limit",
        default=10,
        type=int,
    )

    vector_limit = Parameter(
        "vector_limit",
        help="Vector search result limit",
        default=10,
        type=int,
    )

    web_limit = Parameter(
        "web_limit",
        help="Web search result limit",
        default=5,
        type=int,
    )

    # Engine-coordinated multi-pass continuation parameters
    session_id_param = Parameter(
        "session_id",
        help="Session ID for continuation (engine-coordinated multi-pass)",
        default="",
        type=str,
    )

    pass_number_param = Parameter(
        "pass_number",
        help="Pass number for continuation (1-indexed)",
        default=0,
        type=int,
    )

    tracker_state_param = Parameter(
        "tracker_state",
        help="JSON-serialized ConvergenceTracker state for resumption",
        default="",
        type=str,
    )

    @traced_step
    @step
    def start(self):
        """Initialize research session and emit lineage START.

        Engine-coordinated multi-pass:
        If session_id_param and pass_number_param are provided, this is a
        continuation run triggered by FlowSchedulerService. The tracker_state
        is restored from the previous pass.
        """
        import json

        # Check for continuation (engine-coordinated multi-pass)
        is_continuation = bool(self.session_id_param and self.pass_number_param > 0)

        if is_continuation:
            print(f"research.continuation session={self.session_id_param} pass={self.pass_number_param}")
        else:
            print("research.queued")

        self.emit_event("research.started", {
            "query": self.query,
            "max_passes": self.max_passes,
            "correlation_id": self.get_correlation_id(),
            "continuation": is_continuation,
            "pass_number": self.pass_number_param,
        })

        logger.info(f"ResearchFlow starting: query='{self.query}' continuation={is_continuation}")

        # Initialize or restore session
        if is_continuation:
            self.session_id = self.session_id_param
            self.pass_number = self.pass_number_param - 1  # Will be incremented in search_fan_out
        else:
            # Use provided session_id if available (for pg_notify correlation with service)
            # otherwise generate a new one
            self.session_id = self.session_id_param or f"res_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.pass_number = 0

        # Emit progress event via PostgreSQL (triggers pg_notify for TUI)
        emit_progress(
            session_id=self.session_id,
            event_name="queued",
            message=f"Research queued: {self.query}",
            max_passes=self.max_passes,
            metadata={"query": self.query, "max_passes": self.max_passes},
        )

        # Initialize result containers
        self.memories: list[dict] = []  # Retrieved high-Q memories
        self.bm25_results: list[dict] = []
        self.vector_results: list[dict] = []
        self.web_results: list[dict] = []
        self.swarm_perspectives: dict[str, str] = {}
        self.grok_synthesis: str = ""
        self.merged_synthesis: str = ""
        self.kb_path: str = ""

        # Convergence tracking - restore from state if continuation
        self.passes: list[dict] = []  # PassResult serialized
        if is_continuation and self.tracker_state_param:
            try:
                tracker_state = json.loads(self.tracker_state_param)
                self.convergence_tracker = ConvergenceTracker(
                    drift_threshold=tracker_state.get("drift_threshold", self.drift_threshold),
                    max_passes=tracker_state.get("max_passes", self.max_passes),
                )
                self.convergence_tracker.__setstate__(tracker_state)
                self.passes = [p.__dict__ for p in self.convergence_tracker.passes]
                logger.info(
                    f"Restored tracker state: {len(self.convergence_tracker.passes)} passes"
                )
            except Exception as e:
                logger.warning(f"Failed to restore tracker state: {e}")
                self.convergence_tracker = ConvergenceTracker(
                    drift_threshold=self.drift_threshold,
                    max_passes=self.max_passes,
                )
        else:
            self.convergence_tracker = ConvergenceTracker(
                drift_threshold=self.drift_threshold,
                max_passes=self.max_passes,
            )
        self.converged: bool = False
        self.convergence_reason: str = ""
        self.current_reward: dict = {}

        # Timing metrics
        self.timing: dict[str, float] = {}

        # Register flow run in meta.flow_runs for LISTEN/NOTIFY
        self._register_flow_run()

        # Emit lineage START
        inputs = [Dataset(namespace="gaius.research", name=self.query)]
        self.emit_lineage_start(job_name="research_flow", inputs=inputs)

        self.next(self.retrieve_memories)

    @traced_step
    @step
    def retrieve_memories(self):
        """MemRL Phase A+B: Semantic filter → Q-value ranking."""
        print("research.memories.retrieving")
        emit_progress(
            session_id=self.session_id,
            event_name="memories_retrieving",
            message="Retrieving episodic memories...",
            max_passes=self.max_passes,
        )
        start = time.time()

        async def do_retrieve():
            memories = await retrieve_memories(
                query=self.query,
                kb_root=str(self.kb_root),
                semantic_limit=20,
                q_rank_limit=5,
            )
            return [
                {
                    "session_id": m.session_id,
                    "query": m.query,
                    "q_value": m.q_value,
                    "kb_path": m.kb_path,
                    "synthesis": m.synthesis[:500] if m.synthesis else "",
                }
                for m in memories
            ]

        # Memory retrieval can return empty for first-time queries - that's valid
        # Only raise on actual errors (network, parse failures)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            self.memories = loop.run_until_complete(do_retrieve())
        finally:
            loop.close()

        print(f"research.memories.retrieved count={len(self.memories)}")
        emit_progress(
            session_id=self.session_id,
            event_name="memories_retrieved",
            message=f"Retrieved {len(self.memories)} memories",
            max_passes=self.max_passes,
            metadata={"count": len(self.memories)},
        )
        if self.memories:
            top_q = self.memories[0]["q_value"]
            print(f"research.memories.top_q q_value={top_q:.3f}")

        self.timing["retrieve_memories"] = time.time() - start
        self.next(self.search_fan_out)

    # =========================================================================
    # ENGINE-COORDINATED FLOW: Postgres state + LISTEN/NOTIFY triggers
    # =========================================================================
    # Architecture:
    # 1. Each flow run executes ONE pass (no in-flow recursion)
    # 2. Convergence state stored in PostgreSQL
    # 3. FlowEventListener receives completion → checks convergence → triggers next pass
    # 4. This enables Metaflow foreach for parallel searches (no recursion constraint)
    # =========================================================================

    @traced_step
    @step
    def search_fan_out(self):
        """Fan out to parallel search types (BM25, Vector, Web).

        Uses Metaflow's foreach pattern to execute all three search types
        in parallel, reducing search latency from ~1.5s to ~500ms.
        """
        self.pass_number += 1
        print(f"research.pass.{self.pass_number}.started")
        emit_progress(
            session_id=self.session_id,
            event_name="pass_started",
            pass_number=self.pass_number,
            max_passes=self.max_passes,
            message=f"Starting pass {self.pass_number}",
        )
        self.pass_start_time = time.time()

        # Define search types for foreach parallelism
        self.search_types = ["bm25", "vector", "web"]
        self.next(self.run_search, foreach="search_types")

    @traced_step
    @step
    def run_search(self):
        """Execute single search type (parallel branch).

        This step runs in parallel for each search type: bm25, vector, web.
        """
        search_type = self.input
        print(f"research.pass.{self.pass_number}.search type={search_type}")
        start = time.time()

        if search_type == "bm25":
            self.search_result = self._do_bm25_search()
        elif search_type == "vector":
            self.search_result = self._do_vector_search()
        else:  # web
            self.search_result = self._do_web_search()

        self.search_type = search_type
        self.search_duration = time.time() - start
        print(f"research.pass.{self.pass_number}.search.completed type={search_type} count={len(self.search_result)}")

        self.next(self.join_searches)

    @traced_step
    @step
    def join_searches(self, inputs):
        """Merge parallel search results.

        Collects results from all three parallel search branches and
        stores them in the appropriate instance variables.

        NOTE: In Metaflow join steps, self.* attributes from the parent
        (search_fan_out) are NOT automatically available. We must first
        merge artifacts from inputs to restore state like pass_number.
        """
        # First, merge artifact state from inputs to restore parent step's state
        # (pass_number, timing, etc.). merge_artifacts takes the full inputs list.
        self.merge_artifacts(inputs, exclude=["search_result", "search_type", "search_duration"])

        print(f"research.pass.{self.pass_number}.search.joining")

        # Now merge results from all parallel branches
        for inp in inputs:
            if inp.search_type == "bm25":
                self.bm25_results = inp.search_result
                self.timing[f"bm25_{self.pass_number}"] = inp.search_duration
            elif inp.search_type == "vector":
                self.vector_results = inp.search_result
                self.timing[f"vector_{self.pass_number}"] = inp.search_duration
            else:  # web
                self.web_results = inp.search_result
                self.timing[f"web_{self.pass_number}"] = inp.search_duration

        total_sources = len(self.bm25_results) + len(self.vector_results) + len(self.web_results)
        print(
            f"research.pass.{self.pass_number}.search.joined "
            f"bm25={len(self.bm25_results)} vector={len(self.vector_results)} web={len(self.web_results)}"
        )
        emit_progress(
            session_id=self.session_id,
            event_name="pass_search",
            pass_number=self.pass_number,
            max_passes=self.max_passes,
            message=f"Search complete: {total_sources} sources found",
            metadata={
                "bm25": len(self.bm25_results),
                "vector": len(self.vector_results),
                "web": len(self.web_results),
            },
        )

        self.next(self.analyze_pass)

    @traced_step
    @step
    def analyze_pass(self):
        """Execute 7-agent swarm analysis for diverse perspectives."""
        emit_progress(
            session_id=self.session_id,
            event_name="pass_swarm",
            pass_number=self.pass_number,
            max_passes=self.max_passes,
            message="Running 7-agent swarm analysis...",
        )
        self._do_swarm_analysis()
        self.next(self.synthesize_pass)

    @traced_step
    @step
    def synthesize_pass(self):
        """Execute Grok synthesis and merge perspectives."""
        emit_progress(
            session_id=self.session_id,
            event_name="pass_grok",
            pass_number=self.pass_number,
            max_passes=self.max_passes,
            message="Synthesizing with Grok...",
        )
        self._do_grok_synthesis()
        self._do_merge_perspectives()
        self.next(self.evaluate_pass)

    @traced_step
    @step
    def evaluate_pass(self):
        """Compute reward signal and Q-value update."""
        emit_progress(
            session_id=self.session_id,
            event_name="pass_evaluate",
            pass_number=self.pass_number,
            max_passes=self.max_passes,
            message="Computing reward and Q-value...",
        )
        self._do_evaluate()
        self._do_qvalue_update()
        self.next(self.checkpoint_pass)

    @traced_step
    @step
    def checkpoint_pass(self):
        """Persist convergence state to PostgreSQL and check termination.

        Engine-coordinated multi-pass:
        1. Check if converged
        2. If converged → proceed to final_synthesis
        3. If not converged → save state to Postgres, flow ends (end_pass)
        4. FlowEventListener receives completion → checks state → triggers new flow

        NOTE: No in-flow recursion. Multi-pass loop is coordinated by Engine
        via LISTEN/NOTIFY. This enables Metaflow foreach for parallel searches.

        Metaflow pattern (conditional dictionary):
            self.next({True: self.final_synthesis, False: self.end_pass},
                     condition='converged')
        """
        # Record pass duration
        if hasattr(self, "pass_start_time"):
            self.timing[f"pass_{self.pass_number}"] = time.time() - self.pass_start_time

        # Check convergence
        self.converged, self.convergence_reason = self.convergence_tracker.should_stop()

        # Save state to PostgreSQL for engine coordination
        self._save_research_state()

        if self.converged:
            print(f"research.pass.{self.pass_number}.converged reason={self.convergence_reason}")
            emit_progress(
                session_id=self.session_id,
                event_name="converged",
                pass_number=self.pass_number,
                max_passes=self.max_passes,
                message=f"Converged: {self.convergence_reason}",
                metadata={"reason": self.convergence_reason},
            )
        else:
            print(f"research.pass.{self.pass_number}.checkpoint saved={self.session_id}")
            emit_progress(
                session_id=self.session_id,
                event_name="pass_completed",
                pass_number=self.pass_number,
                max_passes=self.max_passes,
                message=f"Pass {self.pass_number} complete, continuing...",
            )

        # Metaflow conditional dictionary:
        # True → converged, proceed to final_synthesis
        # False → not converged, end this pass (engine triggers next)
        self.next(
            {True: self.final_synthesis, False: self.end_pass},
            condition="converged"
        )

    @traced_step
    @step
    def end_pass(self):
        """End of a single pass (non-converged).

        Flow state is saved in PostgreSQL. Engine's FlowEventListener will
        receive the completion event and decide whether to trigger another pass.

        IMPORTANT: Even when not converged, we still write a KB artifact so
        CLI users get results from pass 1. The artifact is marked as
        "in_progress" in the frontmatter for potential continuation.
        """
        print(f"research.pass.{self.pass_number}.ended awaiting_next_pass=true")

        # Write KB artifact even for non-converged pass so CLI gets results
        self._write_kb_artifact(is_converged=False)

        # Emit event for engine coordination
        self.emit_event("research.pass.completed", {
            "session_id": self.session_id,
            "pass_number": self.pass_number,
            "converged": False,
            "q_value": self.current_reward.get("total", 0.5),
            "max_passes": self.max_passes,
            "kb_path": self.kb_path,
        })

        # Transition to end - flow completes, engine triggers next pass
        self.next(self.end)

    def _save_research_state(self):
        """Persist research state to PostgreSQL for engine coordination.

        State includes:
        - Session ID, query, pass number
        - Convergence tracker state (serialized)
        - Current Q-value and reward components
        - Timing metrics

        This enables the engine to resume multi-pass research without
        in-flow recursion.
        """
        import json

        async def do_save():
            import asyncpg

            # Database URL from environment
            db_url = "postgres://gaius:gaius@localhost:5438/zndx_gaius?sslmode=disable"

            async with asyncpg.create_pool(db_url, min_size=1, max_size=1) as pool:
                async with pool.acquire() as conn:
                    # Upsert research state
                    await conn.execute(
                        """
                        INSERT INTO meta.research_state (
                            session_id, query, pass_number, converged,
                            convergence_reason, q_value, reward_components,
                            timing, tracker_state, created_at, updated_at
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW()
                        )
                        ON CONFLICT (session_id) DO UPDATE SET
                            pass_number = $3,
                            converged = $4,
                            convergence_reason = $5,
                            q_value = $6,
                            reward_components = $7,
                            timing = $8,
                            tracker_state = $9,
                            updated_at = NOW()
                        """,
                        self.session_id,
                        self.query,
                        self.pass_number,
                        self.converged,
                        self.convergence_reason,
                        self.current_reward.get("total", 0.5),
                        json.dumps(self.current_reward),
                        json.dumps(self.timing),
                        json.dumps(self.convergence_tracker.__getstate__()),
                    )

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(do_save())
            finally:
                loop.close()
            logger.info(f"Research state saved: session={self.session_id} pass={self.pass_number}")
        except Exception as e:
            # Log but don't fail - state persistence is for coordination, not critical path
            logger.warning(f"Failed to save research state: {e}")

    def _register_flow_run(self):
        """Register this flow run in meta.flow_runs for LISTEN/NOTIFY.

        Inserts a record with status='running' so the trigger can fire
        when we update to 'completed' at the end.
        """
        import json
        import uuid

        # Generate or restore run_id
        if not hasattr(self, "flow_run_id") or self.flow_run_id is None:
            self.flow_run_id = str(uuid.uuid4())

        async def do_register():
            import asyncpg

            db_url = "postgres://gaius:gaius@localhost:5438/zndx_gaius?sslmode=disable"

            async with asyncpg.create_pool(db_url, min_size=1, max_size=1) as pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO meta.flow_runs (
                            run_id, flow_type, started_at, status, metadata
                        ) VALUES (
                            $1, 'ResearchFlow', NOW(), 'running', $2
                        )
                        ON CONFLICT (run_id) DO UPDATE SET
                            status = 'running',
                            started_at = NOW()
                        """,
                        uuid.UUID(self.flow_run_id),
                        json.dumps({
                            "session_id": self.session_id,
                            "query": self.query,
                            "pass_number": self.pass_number,
                        }),
                    )

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(do_register())
            finally:
                loop.close()
            logger.info(f"Flow run registered: run_id={self.flow_run_id}")
        except Exception as e:
            logger.warning(f"Failed to register flow run: {e}")

    def _complete_flow_run(self, status: str = "completed"):
        """Update flow run status to trigger LISTEN/NOTIFY.

        This fires the meta_flow_runs_notify trigger which sends pg_notify
        to the 'flow_events' channel for engine coordination.
        """
        import json

        if not hasattr(self, "flow_run_id") or self.flow_run_id is None:
            logger.warning("No flow_run_id to complete")
            return

        total_time = int(sum(self.timing.values()) * 1000)  # ms

        async def do_complete():
            import asyncpg
            import uuid

            db_url = "postgres://gaius:gaius@localhost:5438/zndx_gaius?sslmode=disable"

            async with asyncpg.create_pool(db_url, min_size=1, max_size=1) as pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE meta.flow_runs
                        SET status = $2,
                            completed_at = NOW(),
                            duration_ms = $3,
                            outputs_count = $4,
                            metadata = $5
                        WHERE run_id = $1
                        """,
                        uuid.UUID(self.flow_run_id),
                        status,
                        total_time,
                        1 if self.kb_path else 0,
                        json.dumps({
                            "session_id": self.session_id,
                            "query": self.query,
                            "pass_number": self.pass_number,
                            "converged": self.converged,
                            "convergence_reason": self.convergence_reason,
                            "kb_path": self.kb_path,
                        }),
                    )

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(do_complete())
            finally:
                loop.close()
            logger.info(f"Flow run completed: run_id={self.flow_run_id} status={status}")
        except Exception as e:
            logger.warning(f"Failed to complete flow run: {e}")

    # =========================================================================
    # SEARCH METHODS (return results, called from run_search parallel branches)
    # =========================================================================

    def _do_bm25_search(self) -> list[dict]:
        """Execute BM25 search and return results."""
        try:
            from gaius.inference.search import get_kb_search

            kb_search = get_kb_search()
            if kb_search.index_size == 0:
                kb_search.build_index()

            results = kb_search.search(self.query, top_k=self.bm25_limit)
            return [
                {
                    "path": r.path,
                    "title": r.title,
                    "score": r.score,
                    "excerpt": r.snippet[:200] if r.snippet else "",
                }
                for r in results
            ]
        except Exception as e:
            self.emit_event("research.error", {
                "step": "run_search",
                "phase": "bm25",
                "error": str(e),
                "guru_code": "#RF.00000008.BM25FAIL",
            })
            raise SearchError(
                f"BM25 search failed: {e}",
                guru_code="#RF.00000008.BM25FAIL",
                hint="/health fix search",
            ) from e

    def _do_vector_search(self) -> list[dict]:
        """Execute vector search and return results.

        Event-driven: Streams progress events until COMPLETE or ERROR.
        No timeout - ColNomic loading may take significant time.

        Fail-fast: Raises SearchError on failure with remediation hint.
        """
        async def do_vector():
            from gaius.client import get_grpc_client

            client = await get_grpc_client()

            # Event-driven streaming - no timeout, wait for COMPLETE/ERROR
            async for event in client.stream(
                service="Search",
                action="semantic_stream",
                params={
                    "query": self.query,
                    "limit": self.vector_limit,
                    "use_maxsim": True,
                },
                timeout=None,  # Event-driven: wait indefinitely for completion
            ):
                phase = event.get("phase", "UNKNOWN")
                message = event.get("message", "")

                # Log progress events for observability
                if phase in ("REQUESTING_GPU", "EVICTING_ENDPOINTS", "LOADING_MODEL", "SEARCHING"):
                    print(f"  vector.{phase.lower()}: {message}")

                if phase == "ERROR":
                    error_msg = event.get("error", "Unknown error")
                    raise SearchError(
                        f"Vector search error: {error_msg}",
                        guru_code="#RF.00000009.VECSEARCHFAIL",
                        hint="/health fix search",
                    )

                if phase == "COMPLETE":
                    results = event.get("results", [])
                    return [
                        {
                            "path": r.get("path", ""),
                            "title": r.get("title", ""),
                            "score": r.get("score", 0.0),
                            "excerpt": r.get("excerpt", "")[:200],
                        }
                        for r in results
                    ]
            return []

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(do_vector())
            finally:
                loop.close()
        except SearchError:
            raise
        except Exception as e:
            self.emit_event("research.error", {
                "step": "run_search",
                "phase": "vector",
                "error": str(e),
                "guru_code": "#RF.00000009.VECSEARCHFAIL",
            })
            raise SearchError(
                f"Vector search failed: {e}",
                guru_code="#RF.00000009.VECSEARCHFAIL",
                hint="/health fix search",
            ) from e

    def _do_web_search(self) -> list[dict]:
        """Execute web search and return results."""
        async def do_web():
            from gaius.inference import get_search

            search = get_search()
            results = await search.search(self.query, count=self.web_limit)

            return [
                {
                    "title": r.title,
                    "url": r.url,
                    "snippet": (r.snippet[:300] if r.snippet else ""),
                    "source": "brave",
                }
                for r in results
            ]

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(do_web())
            finally:
                loop.close()
        except Exception as e:
            self.emit_event("research.error", {
                "step": "run_search",
                "phase": "web",
                "error": str(e),
                "guru_code": "#RF.00000010.WEBSEARCHFAIL",
            })
            raise SearchError(
                f"Web search failed: {e}",
                guru_code="#RF.00000010.WEBSEARCHFAIL",
                hint="/health fix brave",
            ) from e

    def _do_swarm_analysis(self):
        """Execute 7-agent swarm analysis for diverse perspectives."""
        print(f"research.pass.{self.pass_number}.swarm")
        start = time.time()

        # Build context from search results + prior memories
        context = self._build_context()

        async def do_swarm():
            from gaius.agents.swarm import SwarmManager

            manager = SwarmManager()

            # Run swarm analysis
            result = await manager.run_round(
                domain=self.query,
                context=context,
                parallel=True,
            )

            # Extract perspectives by role
            perspectives = {}
            for response in result.responses:
                role_name = response.role.value if hasattr(response.role, "value") else str(response.role)
                perspectives[role_name] = response.content

            return perspectives

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                self.swarm_perspectives = loop.run_until_complete(do_swarm())
            finally:
                loop.close()

            print(f"research.pass.{self.pass_number}.swarm.completed agents={len(self.swarm_perspectives)}")

        except Exception as e:
            self.emit_event("research.error", {
                "step": "research_pass",
                "phase": "swarm",
                "error": str(e),
                "guru_code": "#RF.00000002.SWARMFAIL",
            })
            raise SynthesisError(
                f"Swarm analysis failed: {e}",
                guru_code="#RF.00000002.SWARMFAIL",
                hint="/health fix endpoints",
            ) from e

        self.timing[f"swarm_{self.pass_number}"] = time.time() - start

    def _do_grok_synthesis(self):
        """Execute XAI Grok synthesis for high-quality output."""
        print(f"research.pass.{self.pass_number}.grok")
        start = time.time()

        # Build comprehensive context
        context = self._build_context()

        # Include swarm perspectives
        if self.swarm_perspectives:
            perspectives_text = "\n\n".join(
                f"### {role} Perspective\n{content}"
                for role, content in self.swarm_perspectives.items()
            )
            context += f"\n\n## Agent Perspectives\n\n{perspectives_text}"

        async def do_grok():
            from gaius.engine.backends.external.xai_backend import XAIBackend

            backend = XAIBackend(model="grok-4-1-fast")

            if not backend.is_available:
                raise ValueError("XAI_API_KEY not configured")

            prompt = f"""Based on the following comprehensive research context, synthesize a thorough analysis for the query: "{self.query}"

{context}

Provide a comprehensive synthesis that:
1. Integrates all search results and agent perspectives
2. Identifies key findings and insights
3. Notes areas of consensus and disagreement among perspectives
4. Highlights gaps and areas for further research
5. Provides actionable conclusions

Use [[wikilinks]] to reference KB documents and [Markdown links](url) for web sources."""

            messages = [
                {"role": "system", "content": "You are a senior research analyst. Synthesize multi-source research into comprehensive, insightful analysis. Cite sources appropriately."},
                {"role": "user", "content": prompt},
            ]

            response = await backend.complete(
                messages=messages,
                model="grok-4-1-fast",
                max_tokens=4096,
            )

            return response.content

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                self.grok_synthesis = loop.run_until_complete(do_grok())
            finally:
                loop.close()

            print(f"research.pass.{self.pass_number}.grok.completed")

        except Exception as e:
            self.emit_event("research.error", {
                "step": "research_pass",
                "phase": "grok",
                "error": str(e),
                "guru_code": "#RF.00000003.GROKFAIL",
            })
            raise SynthesisError(
                f"Grok synthesis failed: {e}",
                guru_code="#RF.00000003.GROKFAIL",
                hint="Check XAI_API_KEY environment variable",
            ) from e

        self.timing[f"grok_{self.pass_number}"] = time.time() - start

    def _do_merge_perspectives(self):
        """Merge swarm perspectives with Grok synthesis."""
        print(f"research.pass.{self.pass_number}.merge")

        # Build merged synthesis
        sections = []

        # Grok synthesis is primary
        if self.grok_synthesis:
            sections.append(self.grok_synthesis)

        # Add swarm perspectives as supplementary
        if self.swarm_perspectives:
            sections.append("\n## Agent Perspectives\n")
            for role, content in self.swarm_perspectives.items():
                sections.append(f"### {role}\n{content[:500]}...")

        self.merged_synthesis = "\n\n".join(sections)

        print(f"research.pass.{self.pass_number}.merge.completed")

    def _do_evaluate(self):
        """Compute reward signal for this research pass."""
        print(f"research.pass.{self.pass_number}.evaluate")
        start = time.time()

        # Get prior syntheses for novelty computation
        prior_syntheses = [p.get("synthesis", "") for p in self.passes if p.get("synthesis")]

        async def do_evaluate():
            sources = [
                {"title": r.get("title", ""), "url": r.get("url", "")}
                for r in self.web_results
            ]
            return await compute_reward(
                synthesis=self.merged_synthesis,
                query=self.query,
                sources=sources,
                prior_syntheses=prior_syntheses,
            )

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                reward = loop.run_until_complete(do_evaluate())
            finally:
                loop.close()

            self.current_reward = reward.to_dict()
            self.current_reward["total"] = reward.total

            print(
                f"research.pass.{self.pass_number}.evaluate.completed "
                f"coherence={reward.coherence:.2f} coverage={reward.coverage:.2f} "
                f"novelty={reward.novelty:.2f} total={reward.total:.2f}"
            )

        except Exception as e:
            self.emit_event("research.error", {
                "step": "research_pass",
                "phase": "evaluate",
                "error": str(e),
                "guru_code": "#RF.00000004.EVALFAIL",
            })
            raise ResearchError(
                f"Evaluation failed: {e}",
                guru_code="#RF.00000004.EVALFAIL",
                hint="/health fix endpoints",
            ) from e

        self.timing[f"evaluate_{self.pass_number}"] = time.time() - start

    def _do_qvalue_update(self):
        """MemRL Bellman update: Q_new ← Q_old + α(reward - Q_old)."""
        print(f"research.pass.{self.pass_number}.qupdate")

        # Compute centroid for drift detection
        async def do_centroid():
            texts = [self.merged_synthesis] + [r.get("excerpt", "") for r in self.bm25_results[:3]]
            return await compute_centroid(texts, use_embedding=True)

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                centroid = loop.run_until_complete(do_centroid())
            finally:
                loop.close()
        except Exception as e:
            self.emit_event("research.error", {
                "step": "research_pass",
                "phase": "centroid",
                "error": str(e),
                "guru_code": "#RF.00000006.CONVERGEFAIL",
            })
            raise ResearchError(
                f"Centroid computation failed: {e}",
                guru_code="#RF.00000006.CONVERGEFAIL",
                hint="/health fix embeddings",
            ) from e

        # Create PassResult
        pass_result = PassResult(
            pass_number=self.pass_number,
            synthesis=self.merged_synthesis,
            q_value=self.current_reward.get("total", 0.5),
            reward_total=self.current_reward.get("total", 0.5),
            centroid=centroid,
            sources_count=len(self.bm25_results) + len(self.vector_results) + len(self.web_results),
            duration_ms=int(sum(self.timing.values()) * 1000),
        )

        # Add to convergence tracker
        self.convergence_tracker.add_pass(pass_result)

        # Store serialized pass
        self.passes.append({
            "pass_number": self.pass_number,
            "q_value": pass_result.q_value,
            "reward_total": pass_result.reward_total,
            "synthesis": self.merged_synthesis[:1000],
            "sources_count": pass_result.sources_count,
        })

        print(f"research.pass.{self.pass_number}.qupdate.completed q_value={pass_result.q_value:.3f}")

    @traced_step
    @step
    def final_synthesis(self):
        """Generate final comprehensive report with Grok."""
        print("research.synthesis.final")
        emit_progress(
            session_id=self.session_id,
            event_name="final_synthesis",
            pass_number=self.pass_number,
            max_passes=self.max_passes,
            message="Generating final synthesis...",
        )
        start = time.time()

        # Build comprehensive context from all passes
        all_syntheses = "\n\n---\n\n".join(
            f"## Pass {p['pass_number']} (Q={p['q_value']:.3f})\n{p['synthesis']}"
            for p in self.passes
        )

        # Include high-Q memories
        memory_context = ""
        if self.memories:
            memory_context = "\n\n## Prior Research (High-Q Memories)\n\n" + "\n\n".join(
                f"- **{m['query']}** (Q={m['q_value']:.3f}): {m['synthesis'][:200]}..."
                for m in self.memories
            )

        async def do_final_grok():
            from gaius.engine.backends.external.xai_backend import XAIBackend

            backend = XAIBackend(model="grok-4-1-fast")

            if not backend.is_available:
                raise ValueError("XAI_API_KEY not configured")

            prompt = f"""You are synthesizing a comprehensive research report on: "{self.query}"

## Research Journey

This research converged after {self.pass_number} passes with reason: {self.convergence_reason}

{all_syntheses}

{memory_context}

Create a polished, comprehensive research report that:

1. **Executive Summary** (2-3 paragraphs): Key findings and insights
2. **Key Findings** (numbered list): Most important discoveries with source citations
3. **Synthesis**: Comprehensive analysis integrating all passes
4. **Perspectives**: Summary of different analytical angles considered
5. **Open Questions**: Unresolved issues and areas for deeper research
6. **Recommendations**: Actionable conclusions

Use [[wikilinks]] for KB sources and [Markdown links](url) for web sources.
Write in a clear, authoritative tone suitable for professional research output."""

            messages = [
                {"role": "system", "content": "You are a senior research director producing the final deliverable. Create polished, comprehensive, and insightful research output."},
                {"role": "user", "content": prompt},
            ]

            response = await backend.complete(
                messages=messages,
                model="grok-4-1-fast",
                max_tokens=8192,  # Larger limit for comprehensive report
            )

            return response.content

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                self.final_report = loop.run_until_complete(do_final_grok())
            finally:
                loop.close()

            print("research.synthesis.final.completed")

        except Exception as e:
            self.emit_event("research.error", {
                "step": "final_synthesis",
                "phase": "grok",
                "error": str(e),
                "guru_code": "#RF.00000011.FINALSYNTHFAIL",
            })
            raise SynthesisError(
                f"Final Grok synthesis failed: {e}",
                guru_code="#RF.00000011.FINALSYNTHFAIL",
                hint="Check XAI_API_KEY environment variable",
            ) from e

        self.timing["final_synthesis"] = time.time() - start
        self.next(self.write_kb)

    def _write_kb_artifact(self, is_converged: bool = True) -> None:
        """Write KB artifact to disk.

        Helper method used by both write_kb (converged) and end_pass (not converged).
        This ensures CLI users always get results even after a single pass.

        Args:
            is_converged: Whether research has converged. Affects frontmatter status.
        """
        print(f"research.kb.writing converged={is_converged}")
        emit_progress(
            session_id=self.session_id,
            event_name="kb_write",
            pass_number=self.pass_number,
            max_passes=self.max_passes,
            message="Writing KB artifact...",
        )

        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H%M%S")

        # Generate KB path
        kb_filename = f"{time_str}_research.md"
        self.kb_path = f"scratch/{date_str}/{kb_filename}"

        # Get best Q-value
        best_q = max(p["q_value"] for p in self.passes) if self.passes else 0.5

        # Get final reward components
        final_reward = self.current_reward if hasattr(self, "current_reward") else {}

        # Build content with MemRL frontmatter
        content = self._build_kb_content(
            now=now,
            best_q=best_q,
            reward_components=final_reward,
            is_converged=is_converged,
        )

        # Write to KB
        full_path = self.kb_root / self.kb_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)

        print(f"research.kb.written path={self.kb_path}")

    @traced_step
    @step
    def write_kb(self):
        """Create zettelkasten KB artifact with MemRL frontmatter (converged research)."""
        # Write the KB artifact
        self._write_kb_artifact(is_converged=True)

        # Update related memories with reward signal (only for converged research)
        best_q = max(p["q_value"] for p in self.passes) if self.passes else 0.5

        async def do_update_related():
            await update_related_memories(
                current_memory=ResearchMemory(
                    session_id=self.session_id,
                    query=self.query,
                    q_value=best_q,
                ),
                reward=best_q,
                kb_root=str(self.kb_root),
            )

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(do_update_related())
            finally:
                loop.close()
        except Exception as e:
            self.emit_event("research.error", {
                "step": "write_kb",
                "phase": "update_related",
                "error": str(e),
                "guru_code": "#RF.00000005.QUPDATE",
            })
            raise ResearchError(
                f"Failed to update related memories: {e}",
                guru_code="#RF.00000005.QUPDATE",
                hint="/health fix kb",
            ) from e

        self.next(self.end)

    @traced_step
    @step
    def end(self):
        """Report results and emit lineage."""
        # Calculate totals
        total_time = sum(self.timing.values())
        total_sources = len(self.bm25_results) + len(self.vector_results) + len(self.web_results)

        # Get best Q-value
        best_q = max(p["q_value"] for p in self.passes) if self.passes else 0.5

        # Emit completion progress event
        emit_progress(
            session_id=self.session_id,
            event_name="completed",
            pass_number=self.pass_number,
            max_passes=self.max_passes,
            message=f"Research complete: {self.convergence_reason}",
            metadata={
                "kb_path": self.kb_path,
                "q_value": best_q,
                "total_time": total_time,
                "sources": total_sources,
            },
        )

        self.emit_event("research.completed", {
            "query": self.query,
            "passes": self.pass_number,
            "convergence_reason": self.convergence_reason,
            "best_q": best_q,
            "kb_path": self.kb_path,
            "timing": self.timing,
            "correlation_id": self.get_correlation_id(),
        })

        # Emit lineage COMPLETE
        outputs = [Dataset.from_kb(self.kb_path)]
        self.emit_lineage_complete(outputs)

        # Complete flow run to trigger LISTEN/NOTIFY for engine coordination
        self._complete_flow_run()

        print("")
        print("=" * 60)
        print("  Research Complete")
        print("=" * 60)
        print(f"  Query:            {self.query}")
        print(f"  Passes:           {self.pass_number}")
        print(f"  Convergence:      {self.convergence_reason}")
        print(f"  Best Q-value:     {best_q:.3f}")
        print(f"  Memories used:    {len(self.memories)}")
        print(f"  Total sources:    {total_sources}")
        print(f"  Swarm agents:     {len(self.swarm_perspectives)}")
        print(f"  KB artifact:      {self.kb_path}")
        print(f"  Total time:       {total_time:.1f}s")
        print("=" * 60)

    def _build_context(self) -> str:
        """Build context string for synthesis from search results + memories."""
        sections = []

        # High-Q memories (if available)
        if self.memories:
            memory_items = []
            for m in self.memories:
                memory_items.append(
                    f"**Prior Research** (Q={m['q_value']:.2f}): {m['query']}\n{m['synthesis'][:300]}..."
                )
            sections.append("## Prior High-Q Research\n\n" + "\n\n".join(memory_items))

        # KB results (BM25 + Vector combined)
        kb_results = []
        seen_paths = set()

        for i, r in enumerate(self.bm25_results, 1):
            if r["path"] not in seen_paths:
                kb_results.append(f"[KB:{i}] **{r.get('title', r['path'])}**\n{r.get('excerpt', '')}")
                seen_paths.add(r["path"])

        for i, r in enumerate(self.vector_results, len(kb_results) + 1):
            if r["path"] not in seen_paths:
                kb_results.append(f"[KB:{i}] **{r.get('title', r['path'])}**\n{r.get('excerpt', '')}")
                seen_paths.add(r["path"])

        if kb_results:
            sections.append("## Knowledge Base Results\n\n" + "\n\n".join(kb_results))

        # Web results
        if self.web_results:
            web_items = []
            for i, r in enumerate(self.web_results, 1):
                web_items.append(f"[Web:{i}] **{r.get('title', 'Untitled')}**\n{r.get('url', '')}\n{r.get('snippet', '')}")
            sections.append("## Web Search Results\n\n" + "\n\n".join(web_items))

        return "\n\n".join(sections) if sections else "No search results available."

    def _build_kb_content(
        self,
        now: datetime,
        best_q: float,
        reward_components: dict,
        is_converged: bool = True,
    ) -> str:
        """Build zettelkasten markdown content with MemRL frontmatter.

        Args:
            now: Current timestamp.
            best_q: Best Q-value from all passes.
            reward_components: Reward components dict.
            is_converged: Whether research converged (affects status field).
        """
        import yaml

        # Build frontmatter
        frontmatter = {
            "type": "research_memory",
            "status": "converged" if is_converged else "in_progress",
            "query": self.query,
            "query_embedding_path": "",  # Would be populated by embedding service
            "q_value": round(best_q, 3),
            "reward_components": {
                "coherence": round(reward_components.get("coherence", 0.5), 3),
                "coverage": round(reward_components.get("coverage", 0.5), 3),
                "novelty": round(reward_components.get("novelty", 0.5), 3),
            },
            "update_count": 1,
            "pass_number": self.pass_number,
            "total_passes": self.pass_number,
            "session_id": self.session_id,
            "convergence_reason": self.convergence_reason,
            "created": now.isoformat(),
            "last_updated": now.isoformat(),
        }

        frontmatter_yaml = yaml.dump(
            frontmatter,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

        sections = []

        # Header with frontmatter
        sections.append(f"---\n{frontmatter_yaml}---\n")
        sections.append(f"# Research: {self.query}\n")

        # Final report (from Grok)
        final_report = getattr(self, "final_report", None)
        merged_synthesis = getattr(self, "merged_synthesis", None)

        if final_report:
            sections.append(final_report)
        elif merged_synthesis:
            # Fallback to merged synthesis
            sections.append("## Synthesis\n")
            sections.append(merged_synthesis)
        else:
            # No synthesis at all - add warning
            sections.append("## Synthesis\n")
            sections.append("*No synthesis generated - check search results and API connectivity.*\n")
            sections.append("- Verify XAI_API_KEY for Grok synthesis")
            sections.append("- Verify inference endpoints for swarm analysis")

        # Agent perspectives (if not already in final report)
        if self.swarm_perspectives and (not final_report or "Agent Perspectives" not in final_report):
            sections.append("\n## Agent Perspectives\n")
            for role, content in self.swarm_perspectives.items():
                sections.append(f"### {role}\n{content[:500]}...\n")

        # KB Sources
        kb_sources = []
        seen_paths = set()

        for r in self.bm25_results + self.vector_results:
            path = r.get("path", "")
            if path and path not in seen_paths:
                title = r.get("title", path)
                excerpt = r.get("excerpt", "")[:80]
                kb_sources.append(f"- [[{path}]] - {title}\n  > {excerpt}...")
                seen_paths.add(path)

        # Always include KB Sources section (even if empty for visibility)
        sections.append("\n## KB Sources\n")
        if kb_sources:
            sections.append("\n".join(kb_sources))
        else:
            sections.append("*No KB sources found - KB may be empty or query too specific.*")

        # Always include Web Sources section (even if empty for visibility)
        sections.append("\n## Web Sources\n")
        if self.web_results:
            web_sources = []
            for r in self.web_results:
                title = r.get("title", "Untitled")
                url = r.get("url", "")
                web_sources.append(f"- [{title}]({url})")
            sections.append("\n".join(web_sources))
        else:
            sections.append("*No web sources found - Brave API may be unavailable.*")

        # Open Questions (extracted from final report or synthesized)
        sections.append("\n## Open Questions\n")
        sections.append("- Further research needed on specific aspects")
        sections.append("- Cross-domain implications to explore")

        # Actions
        sections.append("\n## Actions\n")
        sections.append(f"[action:/research {self.query}]")
        sections.append(f"[action:/search --local {self.query}]")

        # Session Metadata
        sections.append("\n## Session Metadata\n")
        sections.append(f"- Session: {self.session_id}")
        sections.append(f"- Passes: {self.pass_number}")
        sections.append(f"- Convergence: {self.convergence_reason}")
        sections.append(f"- Best Q-value: {best_q:.3f}")
        sections.append(f"- Memories retrieved: {len(self.memories)}")
        sections.append(f"- Total duration: {sum(self.timing.values()):.1f}s")

        return "\n".join(sections)


if __name__ == "__main__":
    apply_metaflow_config("local")
    ResearchFlow()
