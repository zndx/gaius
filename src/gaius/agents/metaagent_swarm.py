"""MetaAgent: Multi-agent analytics for Gaius.

A DeepAgents multi-agent system that answers natural language questions by
correlating data from multiple domains:
- AGE lineage graph (data provenance, dependencies)
- Meta schema (operations, resources, topology)
- KB content (documents, embeddings, clusters)

Architecture:
    ┌─────────────────────────────────────────────────────────────────┐
    │                         MetaAgent                               │
    ├─────────────────────────────────────────────────────────────────┤
    │  User Question: "Why are arxiv flows slow?"                     │
    │                                                                 │
    │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐│
    │  │ Lineage    │  │ Operations │  │ Resource   │  │ Topology   ││
    │  │ Analyst    │  │ Analyst    │  │ Analyst    │  │ Analyst    ││
    │  │ (Cypher)   │  │ (SQL)      │  │ (SQL)      │  │ (SQL)      ││
    │  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘│
    │        └───────────────┴───────────────┴───────────────┘       │
    │                              │                                  │
    │                       ┌──────▼──────┐                          │
    │                       │  Correlator │                          │
    │                       │ (Synthesis) │                          │
    │                       └──────┬──────┘                          │
    │                              │                                  │
    │  Answer + Evidence (DOT, Markdown)                              │
    └─────────────────────────────────────────────────────────────────┘

Usage:
    from gaius.agents.metaagent import MetaAgentManager

    metaagent = MetaAgentManager()
    result = await metaagent.analyze("What sources feed into the CSA docs?")
    print(result.answer)
    print(result.dot_graph)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Callable

from .roles import (
    AgentRole,
    RoleDefinition,
    get_role,
    METAAGENT_ANALYST_ROLES,
)

logger = logging.getLogger(__name__)


class MetaAgentEventType(Enum):
    """Event types for MetaAgent streaming."""

    AGENT_STARTED = "agent_started"
    AGENT_QUERY = "agent_query"
    AGENT_RESULT = "agent_result"
    AGENT_COMPLETED = "agent_completed"
    CORRELATION = "correlation"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class MetaAgentEvent:
    """Event emitted during MetaAgent analysis."""

    type: MetaAgentEventType
    agent: str = ""
    domain: str = ""
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AnalystInsight:
    """Result from a single analyst agent."""

    role: AgentRole
    reasoning: str
    query: str
    query_type: str  # "cypher" or "sql"
    results: list[dict[str, Any]]
    insight: str
    error: str | None = None
    duration_ms: int = 0

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass
class MetaAgentResult:
    """Complete result from MetaAgent analysis."""

    question: str
    answer: str
    correlations: str
    evidence: list[str]
    recommendations: str
    dot_graph: str
    markdown_tables: list[str]
    agent_insights: dict[str, AnalystInsight]  # Role name -> insight
    queries_executed: list[str]
    duration_ms: int
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass
class ResolvedEntity:
    """An entity resolved from natural language to KB paths."""

    mention: str  # Original mention in question (e.g., "CSA docs")
    kb_paths: list[str]  # Resolved KB paths
    dataset_names: list[str]  # Resolved dataset names for lineage
    confidence: float  # Match confidence (0-1)


class MetaAgentManager:
    """Orchestrates multi-agent analytics across data domains.

    Runs analyst agents in parallel to query different data sources,
    then uses a Correlator to synthesize findings into a coherent answer.

    Entity Resolution:
        Before running analysts, the manager resolves natural language
        entity references (e.g., "CSA docs") to actual KB paths and
        dataset names using semantic search. This enables accurate
        lineage queries even with informal entity names.
    """

    def __init__(
        self,
        inference_fn: Callable | None = None,
        db_url: str | None = None,
        search_fn: Callable | None = None,
    ):
        """Initialize MetaAgent.

        Args:
            inference_fn: Async function for LLM calls. Signature:
                async def inference_fn(system: str, user: str, temperature: float) -> str
            db_url: Database URL (uses config if not provided)
            search_fn: Async function for KB search. Signature:
                async def search_fn(query: str, limit: int) -> list[dict]
                Returns dicts with 'path', 'title', 'score' keys
        """
        self._inference_fn = inference_fn
        self._db_url = db_url
        self._search_fn = search_fn
        self._analyst_roles = METAAGENT_ANALYST_ROLES
        self._correlator_role = AgentRole.CORRELATOR

    async def analyze(
        self,
        question: str,
        domains: list[str] | None = None,
        include_dot: bool = True,
        include_markdown: bool = True,
    ) -> MetaAgentResult:
        """Run multi-agent analysis on a question.

        Phase 0: Resolve entity references via KB search
        Phase 1: Run analyst agents in parallel (with resolved context)
        Phase 2: Correlator synthesizes findings

        Args:
            question: Natural language question
            domains: Filter domains (lineage, ops, resources, topology)
            include_dot: Generate GraphViz DOT output
            include_markdown: Generate Markdown tables

        Returns:
            MetaAgentResult with answer and evidence
        """
        start_time = time.time()

        # Phase 0: Resolve entity references
        resolved_entities = await self._resolve_entities(question)
        entity_context = self._format_entity_context(resolved_entities)

        # Filter analysts by domain if specified
        active_roles = self._filter_roles(domains)

        # Phase 1: Run analysts in parallel (with entity context)
        analyst_tasks = [
            self._run_analyst(role, question, entity_context) for role in active_roles
        ]
        analyst_results = await asyncio.gather(*analyst_tasks, return_exceptions=True)

        # Collect insights
        insights: dict[str, AnalystInsight] = {}
        for role, result in zip(active_roles, analyst_results):
            role_def = get_role(role)
            if isinstance(result, Exception):
                logger.warning(f"Analyst {role_def.name} failed: {result}")
                insights[role_def.name] = AnalystInsight(
                    role=role,
                    reasoning="",
                    query="",
                    query_type="unknown",
                    results=[],
                    insight="",
                    error=str(result),
                )
            else:
                insights[role_def.name] = result

        # Phase 2: Correlator synthesizes
        correlation_result = await self._run_correlator(question, insights)

        # Generate evidence formats
        dot_graph = ""
        markdown_tables: list[str] = []
        if include_dot:
            dot_graph = self._generate_dot(insights)
        if include_markdown:
            markdown_tables = self._generate_markdown_tables(insights)

        # Collect all queries
        queries = [
            insight.query
            for insight in insights.values()
            if insight.query and insight.succeeded
        ]

        duration_ms = int((time.time() - start_time) * 1000)

        return MetaAgentResult(
            question=question,
            answer=correlation_result.get("answer", "Unable to synthesize answer"),
            correlations=correlation_result.get("correlations", ""),
            evidence=correlation_result.get("evidence", []),
            recommendations=correlation_result.get("recommendations", ""),
            dot_graph=dot_graph,
            markdown_tables=markdown_tables,
            agent_insights=insights,
            queries_executed=queries,
            duration_ms=duration_ms,
        )

    async def analyze_streaming(
        self,
        question: str,
        domains: list[str] | None = None,
        include_dot: bool = True,
        include_markdown: bool = True,
    ) -> AsyncIterator[MetaAgentEvent]:
        """Run analysis with streaming events.

        Yields events as analysis progresses for real-time UI updates.

        Args:
            question: Natural language question
            domains: Filter domains
            include_dot: Generate DOT output
            include_markdown: Generate Markdown tables

        Yields:
            MetaAgentEvent for each analysis step
        """
        start_time = time.time()
        active_roles = self._filter_roles(domains)

        # Phase 1: Start analysts
        for role in active_roles:
            role_def = get_role(role)
            yield MetaAgentEvent(
                type=MetaAgentEventType.AGENT_STARTED,
                agent=role_def.name,
                domain=self._get_domain_for_role(role),
                message=f"Starting {role_def.name}...",
            )

        # Run analysts in parallel with progress tracking
        analyst_tasks = {
            role: asyncio.create_task(self._run_analyst_with_events(role, question))
            for role in active_roles
        }

        insights: dict[str, AnalystInsight] = {}
        for role, task in analyst_tasks.items():
            role_def = get_role(role)
            try:
                # Get events from analyst
                async for event in await task:
                    yield event
                # Get final insight (last event has the data)
            except Exception as e:
                logger.warning(f"Analyst {role_def.name} failed: {e}")
                yield MetaAgentEvent(
                    type=MetaAgentEventType.ERROR,
                    agent=role_def.name,
                    message=str(e),
                )
                insights[role_def.name] = AnalystInsight(
                    role=role,
                    reasoning="",
                    query="",
                    query_type="unknown",
                    results=[],
                    insight="",
                    error=str(e),
                )

        # Phase 2: Correlation
        yield MetaAgentEvent(
            type=MetaAgentEventType.CORRELATION,
            agent="Correlator",
            message="Synthesizing findings across domains...",
        )

        correlation_result = await self._run_correlator(question, insights)

        # Generate evidence
        dot_graph = self._generate_dot(insights) if include_dot else ""
        markdown_tables = self._generate_markdown_tables(insights) if include_markdown else []

        duration_ms = int((time.time() - start_time) * 1000)

        # Final event
        yield MetaAgentEvent(
            type=MetaAgentEventType.COMPLETE,
            message="Analysis complete",
            data={
                "answer": correlation_result.get("answer", ""),
                "correlations": correlation_result.get("correlations", ""),
                "evidence": correlation_result.get("evidence", []),
                "dot_graph": dot_graph,
                "markdown_tables": markdown_tables,
                "duration_ms": duration_ms,
            },
        )

    def _filter_roles(self, domains: list[str] | None) -> list[AgentRole]:
        """Filter analyst roles by domain."""
        if not domains:
            return list(self._analyst_roles)

        domain_map = {
            "lineage": AgentRole.LINEAGE_ANALYST,
            "ops": AgentRole.OPERATIONS_ANALYST,
            "operations": AgentRole.OPERATIONS_ANALYST,
            "resources": AgentRole.RESOURCE_ANALYST,
            "resource": AgentRole.RESOURCE_ANALYST,
            "topology": AgentRole.TOPOLOGY_ANALYST,
        }

        return [
            domain_map[d.lower()]
            for d in domains
            if d.lower() in domain_map
        ]

    def _get_domain_for_role(self, role: AgentRole) -> str:
        """Get domain name for a role."""
        domain_map = {
            AgentRole.LINEAGE_ANALYST: "lineage",
            AgentRole.OPERATIONS_ANALYST: "operations",
            AgentRole.RESOURCE_ANALYST: "resources",
            AgentRole.TOPOLOGY_ANALYST: "topology",
        }
        return domain_map.get(role, "unknown")

    async def _resolve_entities(self, question: str) -> list[ResolvedEntity]:
        """Resolve natural language entity references to KB paths.

        Uses semantic search to find KB documents that match entity
        mentions in the question. This allows queries like "CSA docs"
        to resolve to actual paths like "current/cloudera/docs/csa/...".

        Args:
            question: Natural language question

        Returns:
            List of resolved entities with KB paths and dataset names
        """
        if not self._search_fn:
            # Try to get search function from engine
            try:
                from gaius.client.grpc_client import get_grpc_client

                async def default_search(query: str, limit: int = 10) -> list[dict]:
                    client = await get_grpc_client()
                    if client:
                        result = await client.call(
                            "Search",
                            "semantic",
                            {"query": query, "limit": limit, "collection": "kb"},
                        )
                        return result.get("results", [])
                    return []

                self._search_fn = default_search
            except Exception as e:
                logger.warning(f"Could not initialize search function: {e}")
                return []

        # Extract potential entity mentions (quoted strings, capitalized phrases, etc.)
        entity_patterns = [
            # Quoted strings
            r'"([^"]+)"',
            r"'([^']+)'",
            # Capitalized multi-word phrases (e.g., "CSA docs", "Apache Kudu")
            r'\b([A-Z][a-z]*(?:\s+[A-Z][a-z]*)+)\b',
            # Acronyms followed by words (e.g., "CSA docs", "KB entries")
            r'\b([A-Z]{2,}(?:\s+\w+)?)\b',
        ]

        mentions = set()
        for pattern in entity_patterns:
            matches = re.findall(pattern, question)
            mentions.update(m.strip() for m in matches if len(m.strip()) > 2)

        # Also search for the full question to catch implicit entities
        if not mentions:
            mentions.add(question)

        resolved: list[ResolvedEntity] = []

        for mention in mentions:
            try:
                results = await self._search_fn(mention, limit=5)
                if results:
                    # Extract paths and derive dataset names
                    kb_paths = [r.get("path", "") for r in results if r.get("path")]
                    dataset_names = self._paths_to_dataset_names(kb_paths)

                    # Calculate confidence based on search scores
                    avg_score = sum(r.get("score", 0) for r in results) / len(results)

                    resolved.append(ResolvedEntity(
                        mention=mention,
                        kb_paths=kb_paths[:5],
                        dataset_names=dataset_names[:5],
                        confidence=min(avg_score, 1.0),
                    ))
            except Exception as e:
                logger.warning(f"Entity resolution failed for '{mention}': {e}")

        return resolved

    def _paths_to_dataset_names(self, paths: list[str]) -> list[str]:
        """Convert KB paths to dataset names for lineage queries.

        Maps paths like:
        - "current/cloudera/docs/csa/..." -> "cloudera.csa"
        - "scratch/2025-12-17/paper.md" -> "gaius.kb:scratch/2025-12-17/paper.md"
        - "current/topics/kudu.md" -> "gaius.kb:current/topics/kudu.md"
        """
        dataset_names = []
        for path in paths:
            if not path:
                continue

            # Normalize path
            path = path.lstrip("/")

            # Extract meaningful dataset name
            if "cloudera/docs/" in path:
                # Extract product from cloudera docs path
                parts = path.split("cloudera/docs/")
                if len(parts) > 1:
                    product = parts[1].split("/")[0]
                    dataset_names.append(f"cloudera.{product}")
            elif path.startswith("scratch/"):
                dataset_names.append(f"gaius.kb:{path}")
            elif path.startswith("current/"):
                dataset_names.append(f"gaius.kb:{path}")
            else:
                dataset_names.append(f"gaius.kb:{path}")

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for name in dataset_names:
            if name not in seen:
                seen.add(name)
                unique.append(name)

        return unique

    def _format_entity_context(self, entities: list[ResolvedEntity]) -> str:
        """Format resolved entities as context for analysts.

        Creates a structured context string that helps analysts
        generate accurate queries using actual KB paths and dataset names.
        """
        if not entities:
            return ""

        lines = ["## Resolved Entity References", ""]
        lines.append("The following entities were resolved from the question:")
        lines.append("")

        for entity in entities:
            lines.append(f"### \"{entity.mention}\" (confidence: {entity.confidence:.2f})")
            if entity.kb_paths:
                lines.append("KB Paths:")
                for path in entity.kb_paths[:3]:
                    lines.append(f"  - {path}")
            if entity.dataset_names:
                lines.append("Dataset Names (for lineage queries):")
                for name in entity.dataset_names[:3]:
                    lines.append(f"  - {name}")
            lines.append("")

        lines.append("Use these resolved names in your queries instead of the natural language references.")

        return "\n".join(lines)

    async def _run_analyst(
        self,
        role: AgentRole,
        question: str,
        entity_context: str = "",
    ) -> AnalystInsight:
        """Run a single analyst agent.

        1. Generate query via LLM (with entity context)
        2. Execute query (Cypher or SQL)
        3. Return insight
        """
        start_time = time.time()
        role_def = get_role(role)

        try:
            # Generate query with entity context
            prompt = role_def.get_prompt(domain=question, context=entity_context)

            # Build user prompt with entity hints
            user_prompt = f"Generate a query to answer: {question}"
            if entity_context:
                user_prompt += f"\n\n{entity_context}"

            response = await self._llm_call(
                system=prompt,
                user=user_prompt,
                temperature=role_def.temperature,
            )

            # Parse JSON response
            parsed = self._parse_analyst_response(response)

            # Determine query type and execute
            query_type = "cypher" if role == AgentRole.LINEAGE_ANALYST else "sql"
            query = parsed.get("query", "")

            if query:
                if query_type == "cypher":
                    results = await self._execute_cypher(query)
                else:
                    results = await self._execute_sql(query)
            else:
                results = []

            duration_ms = int((time.time() - start_time) * 1000)

            return AnalystInsight(
                role=role,
                reasoning=parsed.get("reasoning", ""),
                query=query,
                query_type=query_type,
                results=results,
                insight=parsed.get("insight", ""),
                duration_ms=duration_ms,
            )

        except Exception as e:
            logger.exception(f"Analyst {role_def.name} error")
            return AnalystInsight(
                role=role,
                reasoning="",
                query="",
                query_type="unknown",
                results=[],
                insight="",
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )

    async def _run_analyst_with_events(
        self,
        role: AgentRole,
        question: str,
    ) -> AsyncIterator[MetaAgentEvent]:
        """Run analyst with streaming events."""
        role_def = get_role(role)
        domain = self._get_domain_for_role(role)
        start_time = time.time()

        try:
            # Generate query
            prompt = role_def.get_prompt(domain=question, context="")
            response = await self._llm_call(
                system=prompt,
                user=f"Generate a query to answer: {question}",
                temperature=role_def.temperature,
            )

            parsed = self._parse_analyst_response(response)
            query = parsed.get("query", "")

            yield MetaAgentEvent(
                type=MetaAgentEventType.AGENT_QUERY,
                agent=role_def.name,
                domain=domain,
                message=f"Generated query",
                data={"query": query, "reasoning": parsed.get("reasoning", "")},
            )

            # Execute query
            query_type = "cypher" if role == AgentRole.LINEAGE_ANALYST else "sql"
            if query:
                if query_type == "cypher":
                    results = await self._execute_cypher(query)
                else:
                    results = await self._execute_sql(query)
            else:
                results = []

            yield MetaAgentEvent(
                type=MetaAgentEventType.AGENT_RESULT,
                agent=role_def.name,
                domain=domain,
                message=f"Got {len(results)} results",
                data={"results": results[:10]},  # Limit for streaming
            )

            duration_ms = int((time.time() - start_time) * 1000)

            yield MetaAgentEvent(
                type=MetaAgentEventType.AGENT_COMPLETED,
                agent=role_def.name,
                domain=domain,
                message=f"Completed in {duration_ms}ms",
                data={
                    "insight": AnalystInsight(
                        role=role,
                        reasoning=parsed.get("reasoning", ""),
                        query=query,
                        query_type=query_type,
                        results=results,
                        insight=parsed.get("insight", ""),
                        duration_ms=duration_ms,
                    ).__dict__
                },
            )

        except Exception as e:
            yield MetaAgentEvent(
                type=MetaAgentEventType.ERROR,
                agent=role_def.name,
                domain=domain,
                message=str(e),
            )

    async def _run_correlator(
        self,
        question: str,
        insights: dict[str, AnalystInsight],
    ) -> dict[str, Any]:
        """Run Correlator to synthesize analyst findings."""
        role_def = get_role(self._correlator_role)

        # Format analyst findings for context
        context_parts = []
        for name, insight in insights.items():
            if insight.succeeded and insight.results:
                context_parts.append(f"""
## {name}
Reasoning: {insight.reasoning}
Query ({insight.query_type}): {insight.query}
Results: {json.dumps(insight.results[:10], indent=2)}
""")
            elif insight.error:
                context_parts.append(f"""
## {name}
Error: {insight.error}
""")

        context = "\n".join(context_parts) if context_parts else "No analyst results available."

        prompt = role_def.get_prompt(domain=question, context=context)

        try:
            response = await self._llm_call(
                system=prompt,
                user="Synthesize the analyst findings into a coherent answer.",
                temperature=role_def.temperature,
            )

            # Parse structured response
            return self._parse_correlator_response(response)

        except Exception as e:
            logger.exception("Correlator error")
            return {
                "answer": f"Failed to synthesize: {e}",
                "correlations": "",
                "evidence": [],
                "recommendations": "",
            }

    def _parse_analyst_response(self, response: str) -> dict[str, Any]:
        """Parse analyst LLM response (expects JSON)."""
        # Try to extract JSON from response
        try:
            # Look for JSON block
            json_match = re.search(r"\{[\s\S]*\}", response)
            if json_match:
                return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

        # Fallback: try to extract query directly
        query_match = re.search(
            r"(?:MATCH|SELECT)[\s\S]+?(?:RETURN|;|$)", response, re.IGNORECASE
        )
        return {
            "reasoning": response[:200] if len(response) > 200 else response,
            "query": query_match.group() if query_match else "",
            "expected_columns": [],
        }

    def _parse_correlator_response(self, response: str) -> dict[str, Any]:
        """Parse Correlator response (structured text format)."""
        result = {
            "answer": "",
            "correlations": "",
            "evidence": [],
            "recommendations": "",
        }

        # Extract ANSWER section
        answer_match = re.search(
            r"ANSWER:\s*(.+?)(?=CORRELATIONS:|EVIDENCE:|RECOMMENDATIONS:|$)",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        if answer_match:
            result["answer"] = answer_match.group(1).strip()

        # Extract CORRELATIONS section
        corr_match = re.search(
            r"CORRELATIONS:\s*(.+?)(?=EVIDENCE:|RECOMMENDATIONS:|$)",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        if corr_match:
            result["correlations"] = corr_match.group(1).strip()

        # Extract EVIDENCE section (bullet points)
        evidence_match = re.search(
            r"EVIDENCE:\s*(.+?)(?=RECOMMENDATIONS:|$)",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        if evidence_match:
            evidence_text = evidence_match.group(1).strip()
            # Parse bullet points
            result["evidence"] = [
                line.strip().lstrip("-•* ").strip()
                for line in evidence_text.split("\n")
                if line.strip() and line.strip().startswith(("-", "•", "*"))
            ]

        # Extract RECOMMENDATIONS section
        rec_match = re.search(
            r"RECOMMENDATIONS:\s*(.+?)$",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        if rec_match:
            result["recommendations"] = rec_match.group(1).strip()

        # Fallback if no structured format found
        if not result["answer"]:
            result["answer"] = response[:500] if len(response) > 500 else response

        return result

    def _generate_dot(self, insights: dict[str, AnalystInsight]) -> str:
        """Generate GraphViz DOT from analyst insights."""
        lines = [
            "digraph metaagent_lineage {",
            "  rankdir=LR;",
            "  node [shape=box];",
            "",
        ]

        # Add nodes and edges from lineage results
        lineage = insights.get("LineageAnalyst")
        if lineage and lineage.succeeded and lineage.results:
            seen_nodes = set()
            for row in lineage.results[:20]:  # Limit
                # Try to extract source/target from row
                source = None
                target = None
                for key, value in row.items():
                    if value and isinstance(value, str):
                        if "source" in key.lower() or key == "c0":
                            source = value
                        elif "target" in key.lower() or "kb" in key.lower() or key == "c1":
                            target = value

                if source and target:
                    # Sanitize for DOT
                    source_id = re.sub(r"[^a-zA-Z0-9_]", "_", source)[:30]
                    target_id = re.sub(r"[^a-zA-Z0-9_]", "_", target)[:30]

                    if source_id not in seen_nodes:
                        lines.append(f'  {source_id} [label="{source[:30]}"];')
                        seen_nodes.add(source_id)
                    if target_id not in seen_nodes:
                        lines.append(f'  {target_id} [label="{target[:30]}"];')
                        seen_nodes.add(target_id)
                    lines.append(f"  {source_id} -> {target_id};")

        lines.append("}")
        return "\n".join(lines)

    def _generate_markdown_tables(
        self, insights: dict[str, AnalystInsight]
    ) -> list[str]:
        """Generate Markdown tables from analyst results."""
        tables = []

        for name, insight in insights.items():
            if not insight.succeeded or not insight.results:
                continue

            # Get columns from first result
            if insight.results:
                columns = list(insight.results[0].keys())
                if not columns:
                    continue

                # Build table
                lines = [
                    f"### {name} Results",
                    "",
                    "| " + " | ".join(columns) + " |",
                    "| " + " | ".join(["---"] * len(columns)) + " |",
                ]

                for row in insight.results[:10]:  # Limit rows
                    values = [
                        str(row.get(col, ""))[:50]  # Truncate long values
                        for col in columns
                    ]
                    lines.append("| " + " | ".join(values) + " |")

                tables.append("\n".join(lines))

        return tables

    async def _llm_call(
        self,
        system: str,
        user: str,
        temperature: float = 0.7,
    ) -> str:
        """Call LLM for text generation."""
        if self._inference_fn:
            return await self._inference_fn(system, user, temperature)

        # Default: use engine scheduler
        try:
            from gaius.engine.client import get_engine_client

            client = await get_engine_client()
            response = await client.complete(
                prompt=user,
                system_prompt=system,
                temperature=temperature,
                max_tokens=2048,
            )
            return response.text
        except Exception as e:
            logger.warning(f"Engine client not available: {e}")
            raise RuntimeError(
                "No inference function provided and engine client not available.\n"
                "  Try: /health fix engine"
            ) from e

    async def _execute_cypher(self, cypher: str) -> list[dict[str, Any]]:
        """Execute Cypher query on AGE graph."""
        import asyncpg

        # Security check
        cypher_upper = cypher.upper()
        disallowed = ["CREATE", "DELETE", "REMOVE", "SET", "MERGE", "DROP"]
        for keyword in disallowed:
            if re.search(rf"\b{keyword}\b", cypher_upper):
                raise ValueError(f"Write operations not allowed: {keyword}")

        db_url = self._db_url
        if not db_url:
            from gaius.core.config import get_config
            db_url = get_config().database.url

        conn = await asyncpg.connect(db_url)
        try:
            await conn.execute("SET search_path = ag_catalog, public")

            # Count columns for result type declaration
            return_match = re.search(
                r"\bRETURN\s+(.+?)(?:\s+ORDER\s|\s+LIMIT\s|$)",
                cypher,
                re.IGNORECASE | re.DOTALL,
            )
            if not return_match:
                raise ValueError("Query must have a RETURN clause")

            col_count = return_match.group(1).count(",") + 1
            col_decls = ", ".join([f"c{i} agtype" for i in range(col_count)])

            # Add LIMIT if not present
            if "LIMIT" not in cypher_upper:
                cypher = f"{cypher.rstrip().rstrip(';')} LIMIT 100"

            age_query = f"""
                SELECT * FROM cypher('gaius_hx', $cypher$
                    {cypher}
                $cypher$) AS ({col_decls});
            """

            rows = await conn.fetch(age_query)

            results = []
            for row in rows:
                row_data = {}
                for i, val in enumerate(row.values()):
                    if val is not None:
                        try:
                            parsed = json.loads(str(val))
                            row_data[f"c{i}"] = parsed
                        except (json.JSONDecodeError, TypeError):
                            row_data[f"c{i}"] = str(val)
                    else:
                        row_data[f"c{i}"] = None
                results.append(row_data)

            return results

        finally:
            await conn.close()

    async def _execute_sql(self, sql: str) -> list[dict[str, Any]]:
        """Execute SQL query on meta schema."""
        import asyncpg

        # Security check - only allow SELECT
        sql_upper = sql.upper().strip()
        if not sql_upper.startswith("SELECT"):
            raise ValueError("Only SELECT queries allowed")

        disallowed = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE"]
        for keyword in disallowed:
            if re.search(rf"\b{keyword}\b", sql_upper):
                raise ValueError(f"Write operations not allowed: {keyword}")

        db_url = self._db_url
        if not db_url:
            from gaius.core.config import get_config
            db_url = get_config().database.url

        conn = await asyncpg.connect(db_url)
        try:
            # Add LIMIT if not present
            if "LIMIT" not in sql_upper:
                sql = f"{sql.rstrip().rstrip(';')} LIMIT 100"

            rows = await conn.fetch(sql)

            results = []
            for row in rows:
                row_data = {}
                for key, val in dict(row).items():
                    # Convert special types
                    if hasattr(val, "isoformat"):
                        row_data[key] = val.isoformat()
                    elif isinstance(val, (list, dict)):
                        row_data[key] = val
                    else:
                        row_data[key] = val
                results.append(row_data)

            return results

        finally:
            await conn.close()
