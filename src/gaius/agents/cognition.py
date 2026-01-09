"""Cognition Agent for Gaius.

Generates "thoughts" between sessions - patterns, connections, curiosities,
and observations that give Gaius the appearance of ongoing inner life.

Thought Types:
- PATTERN: Emerging patterns detected across content ("Raft mentions up 3x this week")
- CONNECTION: Cross-domain links discovered ("Pension LDI and climate risk share frameworks")
- CURIOSITY: Questions worth investigating ("Why do LLM optimizations ignore semantic drift?")
- MOMENTUM: Topics gaining/losing attention ("Byzantine fault tolerance trending")
- OBSERVATION: Notable changes or trends ("Heavy activity in distributed systems domain")
- SYNTHESIS: Consolidated understanding ("Here's what we know about X")

Usage:
    from gaius.agents.cognition import CognitionAgent, get_cognition_agent

    agent = get_cognition_agent()
    thoughts = await agent.think()
    for thought in thoughts:
        print(f"{thought.thought_type}: {thought.title}")
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
import logging

from ..core.config import get_config

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Enums and Data Classes
# ═══════════════════════════════════════════════════════════════════════════════


class ThoughtType(str, Enum):
    """Types of thoughts the cognition agent can generate."""

    # Standard thought types
    PATTERN = "pattern"
    CONNECTION = "connection"
    CURIOSITY = "curiosity"
    MOMENTUM = "momentum"
    OBSERVATION = "observation"
    SYNTHESIS = "synthesis"

    # Self-aware thought types (new)
    SELF_OBSERVATION = "self_observation"  # Thoughts about own thought patterns
    ENGINE_AUDIT = "engine_audit"          # Observations about engine health
    META_REFLECTION = "meta_reflection"    # Higher-order pattern recognition

    # Evolution thought types
    TASK_IDEA = "task_idea"                # New reasoning task concepts
    EVOLUTION_INSIGHT = "evolution_insight"  # Observations about agent improvement


class ThoughtStatus(str, Enum):
    """Lifecycle status of a thought."""

    ACTIVE = "active"
    SURFACED = "surfaced"
    ACKNOWLEDGED = "acknowledged"
    STALE = "stale"
    ARCHIVED = "archived"


@dataclass
class Thought:
    """A single cognitive observation."""

    thought_type: ThoughtType
    title: str
    content: str
    summary: str = ""  # 1-2 sentence version for greeting

    # Relationships
    domains: list[str] = field(default_factory=list)
    kb_paths: list[str] = field(default_factory=list)
    source_entries: list[str] = field(default_factory=list)

    # Scoring (0.0 - 1.0)
    salience: float = 0.5
    confidence: float = 0.5
    novelty: float = 0.5

    # Status
    status: ThoughtStatus = ThoughtStatus.ACTIVE
    id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)

    # Lineage tracking (for recursive self-observation)
    predecessor_id: str | None = None    # Direct parent thought
    generation: int = 0                   # Depth in chain (0 = root)
    thought_chain_id: str | None = None  # Groups related thoughts
    note_path: str | None = None         # Path to saved markdown note
    content_hash: str | None = None      # For duplicate detection

    def to_markdown(self) -> str:
        """Format thought as markdown section."""
        indicator = {
            ThoughtType.PATTERN: "[PATTERN]",
            ThoughtType.CONNECTION: "[LINK]",
            ThoughtType.CURIOSITY: "[?]",
            ThoughtType.MOMENTUM: "[TREND]",
            ThoughtType.OBSERVATION: "[OBS]",
            ThoughtType.SYNTHESIS: "[SYNTH]",
            ThoughtType.SELF_OBSERVATION: "[SELF]",
            ThoughtType.ENGINE_AUDIT: "[AUDIT]",
            ThoughtType.META_REFLECTION: "[META]",
            ThoughtType.TASK_IDEA: "[TASK]",
            ThoughtType.EVOLUTION_INSIGHT: "[EVOL]",
        }.get(self.thought_type, "[*]")

        lines = [f"### {indicator} {self.title}"]

        if self.summary:
            lines.append(f"_{self.summary}_")
            lines.append("")

        lines.append(self.content)

        if self.kb_paths:
            lines.append("")
            lines.append("**Related:**")
            for path in self.kb_paths[:3]:
                lines.append(f"- [[{path}]]")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON/database storage."""
        return {
            "id": self.id,
            "thought_type": self.thought_type.value,
            "title": self.title,
            "content": self.content,
            "summary": self.summary,
            "domains": self.domains,
            "kb_paths": self.kb_paths,
            "source_entries": self.source_entries,
            "salience": self.salience,
            "confidence": self.confidence,
            "novelty": self.novelty,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            # Lineage tracking
            "predecessor_id": self.predecessor_id,
            "generation": self.generation,
            "thought_chain_id": self.thought_chain_id,
            "note_path": self.note_path,
        }


@dataclass
class CognitionContext:
    """All context available for a cognition cycle."""

    # Recent content
    recent_kb_entries: list[dict] = field(default_factory=list)
    recent_content_items: list[dict] = field(default_factory=list)
    kb_entries_scanned: int = 0

    # Activity
    queries_today: list[str] = field(default_factory=list)
    swarm_runs: list[dict] = field(default_factory=list)
    domains_active: list[str] = field(default_factory=list)

    # Time
    time_since_last_think: timedelta = field(default_factory=lambda: timedelta(hours=24))
    emphasis_hours: int = 24
    tactical_days: int = 7

    # Existing thoughts (to avoid duplicates)
    active_thoughts: list[Thought] = field(default_factory=list)

    # Engine observations (for auditing)
    engine_observations: list[dict] = field(default_factory=list)
    evolution_cycles: list[dict] = field(default_factory=list)

    # Thought chains (for recursive self-observation)
    thought_chains: list[dict] = field(default_factory=list)


@dataclass
class CognitionResult:
    """Result of a cognition cycle."""

    thoughts: list[Thought]
    cycle_id: int | None = None

    # Metrics
    patterns_detected: int = 0
    connections_found: int = 0
    curiosities_generated: int = 0
    self_observations: int = 0
    engine_audits: int = 0

    # Resources
    model_used: str = ""
    tokens_used: int = 0
    duration_ms: int = 0

    # Context
    content_analyzed: int = 0
    kb_entries_scanned: int = 0
    trigger_reason: str = "manual"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "thoughts": [t.to_dict() for t in self.thoughts],
            "patterns_detected": self.patterns_detected,
            "connections_found": self.connections_found,
            "curiosities_generated": self.curiosities_generated,
            "self_observations": self.self_observations,
            "engine_audits": self.engine_audits,
            "model_used": self.model_used,
            "tokens_used": self.tokens_used,
            "duration_ms": self.duration_ms,
            "content_analyzed": self.content_analyzed,
            "kb_entries_scanned": self.kb_entries_scanned,
            "trigger_reason": self.trigger_reason,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Cognition Agent
# ═══════════════════════════════════════════════════════════════════════════════


class CognitionAgent:
    """Agent that generates thoughts between sessions.

    Runs background cognition cycles to detect patterns, find connections,
    and generate curiosity-driven questions from accumulated knowledge.
    """

    def __init__(self, profile: str = "default"):
        self.profile = profile
        self.config = get_config()

    async def think(
        self,
        max_thoughts: int = 5,
        trigger_reason: str = "manual",
    ) -> CognitionResult:
        """Run a cognition cycle to generate thoughts.

        Args:
            max_thoughts: Maximum thoughts to generate
            trigger_reason: Why cognition was triggered (manual, scheduled, content_threshold, session_start)

        Returns:
            CognitionResult with generated thoughts
        """
        import time

        start_time = time.time()

        # Gather context
        context = await self._gather_context()

        # Generate thoughts using different strategies
        thoughts: list[Thought] = []

        # 1. Detect patterns (topic velocity, clustering)
        pattern_thoughts = await self._detect_patterns(context)
        thoughts.extend(pattern_thoughts)

        # 2. Find cross-domain connections
        connection_thoughts = await self._find_connections(context)
        thoughts.extend(connection_thoughts)

        # 3. Generate curiosity questions
        curiosity_thoughts = await self._generate_curiosities(context)
        thoughts.extend(curiosity_thoughts)

        # 4. Track momentum (what's trending)
        momentum_thoughts = await self._track_momentum(context)
        thoughts.extend(momentum_thoughts)

        # 5. Self-observation (recursive thinking about thoughts)
        self_observation_thoughts = await self._observe_own_thoughts(context)
        thoughts.extend(self_observation_thoughts)

        # 6. Engine auditing (if enabled)
        engine_audit_thoughts = await self._audit_engine_health(context)
        thoughts.extend(engine_audit_thoughts)

        # Filter for novelty (don't repeat existing thoughts)
        thoughts = self._filter_for_novelty(thoughts, context.active_thoughts)

        # Rank by salience and take top N
        thoughts = sorted(thoughts, key=lambda t: t.salience, reverse=True)
        thoughts = thoughts[:max_thoughts]

        # Persist thoughts to database
        for thought in thoughts:
            await self._save_thought(thought)

        # Record the cycle
        duration_ms = int((time.time() - start_time) * 1000)

        result = CognitionResult(
            thoughts=thoughts,
            patterns_detected=len([t for t in thoughts if t.thought_type == ThoughtType.PATTERN]),
            connections_found=len([t for t in thoughts if t.thought_type == ThoughtType.CONNECTION]),
            curiosities_generated=len([t for t in thoughts if t.thought_type == ThoughtType.CURIOSITY]),
            self_observations=len([t for t in thoughts if t.thought_type == ThoughtType.SELF_OBSERVATION]),
            engine_audits=len([t for t in thoughts if t.thought_type == ThoughtType.ENGINE_AUDIT]),
            content_analyzed=len(context.recent_content_items),
            kb_entries_scanned=len(context.recent_kb_entries),
            duration_ms=duration_ms,
            trigger_reason=trigger_reason,
        )

        await self._record_cycle(result)

        return result

    async def get_active_thoughts(self, limit: int = 10) -> list[Thought]:
        """Get currently active thoughts from database."""
        try:
            import asyncpg

            conn = await asyncpg.connect(self.config.database.url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT id, thought_type, title, content, summary,
                           domains, kb_paths, source_entries,
                           salience, confidence, novelty, status, created_at
                    FROM cognition_thoughts
                    WHERE profile_name = $1 AND status = 'active'
                    ORDER BY salience DESC, created_at DESC
                    LIMIT $2
                    """,
                    self.profile,
                    limit,
                )

                return [
                    Thought(
                        id=str(row["id"]),
                        thought_type=ThoughtType(row["thought_type"]),
                        title=row["title"],
                        content=row["content"],
                        summary=row["summary"] or "",
                        domains=row["domains"] or [],
                        kb_paths=row["kb_paths"] or [],
                        source_entries=row["source_entries"] or [],
                        salience=row["salience"],
                        confidence=row["confidence"],
                        novelty=row["novelty"],
                        status=ThoughtStatus(row["status"]),
                        created_at=row["created_at"],
                    )
                    for row in rows
                ]

            finally:
                await conn.close()

        except Exception as e:
            raise RuntimeError(
                f"Failed to get active thoughts from database: {e}\n"
                "Guru Meditation: #COG.00000002.DBREAD\n"
                "Check: /health postgres"
            ) from e

    async def mark_surfaced(self, thought_ids: list[str]) -> None:
        """Mark thoughts as surfaced (shown to user)."""
        if not thought_ids:
            return

        try:
            import asyncpg

            conn = await asyncpg.connect(self.config.database.url)
            try:
                await conn.execute(
                    """
                    UPDATE cognition_thoughts
                    SET status = 'surfaced',
                        surfaced_at = NOW(),
                        updated_at = NOW()
                    WHERE id = ANY($1::uuid[])
                    """,
                    thought_ids,
                )
            finally:
                await conn.close()

        except Exception as e:
            raise RuntimeError(
                f"Failed to mark thoughts surfaced in database: {e}\n"
                "Guru Meditation: #COG.00000003.DBWRITE\n"
                "Check: /health postgres"
            ) from e

    # ─────────────────────────────────────────────────────────────────────────
    # Context Gathering
    # ─────────────────────────────────────────────────────────────────────────

    async def _gather_context(self) -> CognitionContext:
        """Gather all context for cognition."""
        context = CognitionContext()

        # Get recent KB entries
        context.recent_kb_entries = await self._get_recent_kb_entries()
        context.kb_entries_scanned = len(context.recent_kb_entries)

        # Get recent content items (from workers)
        context.recent_content_items = await self._get_recent_content_items()

        # Get activity summary
        context.queries_today = await self._get_recent_queries()
        context.swarm_runs = await self._get_recent_swarm_runs()

        # Get active domains
        context.domains_active = await self._get_active_domains()

        # Get existing active thoughts
        context.active_thoughts = await self.get_active_thoughts(limit=20)

        # Time since last cognition
        context.time_since_last_think = await self._time_since_last_think()

        return context

    async def _get_recent_kb_entries(self, days: int = 7) -> list[dict]:
        """Scan KB for recent entries."""
        entries = []
        kb_root = Path(self.config.kb.root)
        cutoff = datetime.now() - timedelta(days=days)

        try:
            for path in kb_root.rglob("*.md"):
                try:
                    mtime = datetime.fromtimestamp(path.stat().st_mtime)
                    if mtime > cutoff:
                        # Read first few lines for preview
                        content = path.read_text(encoding="utf-8")
                        lines = content.split("\n")
                        title = lines[0].lstrip("#").strip() if lines else path.stem
                        preview = " ".join(lines[1:5]).strip()[:200]

                        # Extract domain from path
                        rel_path = path.relative_to(kb_root)
                        domain = rel_path.parts[1] if len(rel_path.parts) > 1 else "general"

                        entries.append({
                            "path": str(rel_path),
                            "title": title,
                            "preview": preview,
                            "domain": domain,
                            "mtime": mtime,
                        })
                except Exception:
                    continue

            entries.sort(key=lambda e: e["mtime"], reverse=True)

        except Exception as e:
            raise RuntimeError(
                f"Failed to scan KB entries: {e}\n"
                "Guru Meditation: #COG.00000009.KBSCAN\n"
                "Check: KB root path exists and is accessible"
            ) from e

        return entries[:100]  # Limit for performance

    async def _get_recent_content_items(self, days: int = 7) -> list[dict]:
        """Get recently fetched content items."""
        try:
            import asyncpg

            conn = await asyncpg.connect(self.config.database.url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT c.id, c.title, s.name AS source_name, c.kb_path, c.fetched_at
                    FROM content_items c
                    LEFT JOIN feed_sources s ON c.source_id = s.id
                    WHERE c.fetched_at > NOW() - ($1 || ' days')::INTERVAL
                    ORDER BY c.fetched_at DESC
                    LIMIT 100
                    """,
                    str(days),
                )
                return [dict(row) for row in rows]
            finally:
                await conn.close()

        except Exception as e:
            raise RuntimeError(
                f"Failed to get recent content items from database: {e}\n"
                "Guru Meditation: #COG.00000004.DBCONTENT\n"
                "Check: /health postgres"
            ) from e

    async def _get_recent_queries(self, days: int = 1) -> list[str]:
        """Get recent user queries from activity log."""
        try:
            import asyncpg

            conn = await asyncpg.connect(self.config.database.url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT details->>'query' as query
                    FROM activity_events
                    WHERE event_type = 'query'
                      AND created_at > NOW() - ($1 || ' days')::INTERVAL
                      AND details ? 'query'
                    ORDER BY created_at DESC
                    LIMIT 50
                    """,
                    str(days),
                )
                return [row["query"] for row in rows if row["query"]]
            finally:
                await conn.close()

        except Exception as e:
            raise RuntimeError(
                f"Failed to get recent queries from database: {e}\n"
                "Guru Meditation: #COG.00000005.DBQUERIES\n"
                "Check: /health postgres"
            ) from e

    async def _get_recent_swarm_runs(self, days: int = 7) -> list[dict]:
        """Get recent swarm analysis runs."""
        try:
            import asyncpg

            conn = await asyncpg.connect(self.config.database.url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT details
                    FROM activity_events
                    WHERE event_type = 'swarm_run'
                      AND created_at > NOW() - ($1 || ' days')::INTERVAL
                    ORDER BY created_at DESC
                    LIMIT 20
                    """,
                    str(days),
                )
                return [row["details"] for row in rows if row["details"]]
            finally:
                await conn.close()

        except Exception as e:
            raise RuntimeError(
                f"Failed to get recent swarm runs from database: {e}\n"
                "Guru Meditation: #COG.00000006.DBSWARM\n"
                "Check: /health postgres"
            ) from e

    async def _get_active_domains(self) -> list[str]:
        """Get domains with recent activity."""
        try:
            import asyncpg

            conn = await asyncpg.connect(self.config.database.url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT DISTINCT domain
                    FROM activity_events
                    WHERE created_at > NOW() - INTERVAL '7 days'
                      AND domain IS NOT NULL
                    """,
                )
                return [row["domain"] for row in rows]
            finally:
                await conn.close()

        except Exception as e:
            raise RuntimeError(
                f"Failed to get active domains from database: {e}\n"
                "Guru Meditation: #COG.00000007.DBDOMAINS\n"
                "Check: /health postgres"
            ) from e

    async def _time_since_last_think(self) -> timedelta:
        """Get time since last cognition cycle."""
        try:
            import asyncpg

            conn = await asyncpg.connect(self.config.database.url)
            try:
                result = await conn.fetchval(
                    """
                    SELECT NOW() - completed_at
                    FROM cognition_cycles
                    WHERE profile_name = $1 AND success = TRUE
                    ORDER BY completed_at DESC
                    LIMIT 1
                    """,
                    self.profile,
                )
                return result or timedelta(days=999)
            finally:
                await conn.close()

        except Exception as e:
            raise RuntimeError(
                f"Failed to get time since last cognition from database: {e}\n"
                "Guru Meditation: #COG.00000008.DBLAST\n"
                "Check: /health postgres"
            ) from e

    # ─────────────────────────────────────────────────────────────────────────
    # Thought Generation Strategies
    # ─────────────────────────────────────────────────────────────────────────

    async def _detect_patterns(self, context: CognitionContext) -> list[Thought]:
        """Detect patterns in recent content using LLM."""
        if not context.recent_kb_entries:
            return []

        from gaius.client import get_grpc_client

        # Build entry list
        entry_summaries = []
        for entry in context.recent_kb_entries[:30]:
            entry_summaries.append(
                f"- [{entry['domain']}] {entry['title']}: {entry['preview'][:100]}..."
            )

        prompt = f"""Analyze these recent knowledge base entries for patterns.

Recent entries ({len(context.recent_kb_entries)} total):
{chr(10).join(entry_summaries)}

Identify 1-2 emerging patterns (recurring themes, topic clusters, or trends).

For each pattern, provide:
1. A concise title (5-10 words)
2. A 1-sentence summary
3. Evidence (which entries support this)
4. A salience score 0.0-1.0 (how interesting/important)

Format as JSON array: [{{"title": "...", "summary": "...", "evidence": ["..."], "salience": 0.7}}]"""

        try:
            client = await get_grpc_client()
            result = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": prompt,
                    "agent": "fast",
                    "max_tokens": 500,
                    "temperature": 0.6,
                },
            )

            # Parse response
            import json

            content = result.get("content", "").strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            patterns = json.loads(content)

            thoughts = []
            for p in patterns[:2]:
                thoughts.append(Thought(
                    thought_type=ThoughtType.PATTERN,
                    title=p.get("title", "Pattern detected"),
                    content=f"{p.get('summary', '')}\n\nEvidence: {', '.join(p.get('evidence', []))}",
                    summary=p.get("summary", ""),
                    salience=float(p.get("salience", 0.5)),
                    confidence=0.6,
                    novelty=0.7,
                    domains=list(set(e["domain"] for e in context.recent_kb_entries[:10])),
                ))

            return thoughts

        except Exception as e:
            raise RuntimeError(
                f"Pattern detection failed during inference: {e}\n"
                "Guru Meditation: #COG.00000010.LLMPATTERN\n"
                "Check: /health endpoints"
            ) from e

    async def _find_connections(self, context: CognitionContext) -> list[Thought]:
        """Find cross-domain connections using LLM."""
        if len(context.domains_active) < 2:
            return []

        from gaius.client import get_grpc_client

        # Group entries by domain
        by_domain: dict[str, list[str]] = {}
        for entry in context.recent_kb_entries[:50]:
            domain = entry.get("domain", "general")
            if domain not in by_domain:
                by_domain[domain] = []
            by_domain[domain].append(f"{entry['title']}: {entry['preview'][:80]}")

        domain_summaries = []
        for domain, entries in list(by_domain.items())[:5]:
            domain_summaries.append(f"\n**{domain}:**\n" + "\n".join(f"- {e}" for e in entries[:5]))

        prompt = f"""Look for surprising connections between these different domains:

{chr(10).join(domain_summaries)}

Find 1 non-obvious connection that links concepts across domains.
The connection should be intellectually interesting, not trivial.

Provide:
1. A concise title describing the connection
2. An explanation of the link (2-3 sentences)
3. Why this is interesting or useful
4. The domains connected

Format as JSON: {{"title": "...", "explanation": "...", "significance": "...", "domains": ["...", "..."]}}"""

        try:
            client = await get_grpc_client()
            result = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": prompt,
                    "agent": "fast",
                    "max_tokens": 400,
                    "temperature": 0.7,
                },
            )

            # Parse response
            import json

            content = result.get("content", "").strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            conn = json.loads(content)

            return [Thought(
                thought_type=ThoughtType.CONNECTION,
                title=conn.get("title", "Cross-domain connection"),
                content=f"{conn.get('explanation', '')}\n\n{conn.get('significance', '')}",
                summary=conn.get("explanation", "")[:100],
                domains=conn.get("domains", []),
                salience=0.8,  # Connections are valuable
                confidence=0.5,
                novelty=0.9,
            )]

        except Exception as e:
            raise RuntimeError(
                f"Connection finding failed during inference: {e}\n"
                "Guru Meditation: #COG.00000011.LLMCONNECT\n"
                "Check: /health endpoints"
            ) from e

    async def _generate_curiosities(self, context: CognitionContext) -> list[Thought]:
        """Generate curiosity-driven questions."""
        from gaius.client import get_grpc_client

        # Combine recent activity
        topics = []
        for entry in context.recent_kb_entries[:20]:
            topics.append(entry["title"])
        for query in context.queries_today[:10]:
            topics.append(query)

        if not topics:
            return []

        prompt = f"""Based on this recent knowledge work, generate 1-2 curiosity-driven questions.

Recent topics/queries:
{chr(10).join(f'- {t}' for t in topics[:15])}

Generate questions that:
- Cannot be answered by simple lookup
- Connect multiple ideas or domains
- Have practical or theoretical significance
- Are tractable (not hopelessly vague)

Format as JSON array: [{{"question": "...", "context": "...", "significance": "..."}}]"""

        try:
            client = await get_grpc_client()
            result = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": prompt,
                    "agent": "fast",
                    "max_tokens": 400,
                    "temperature": 0.7,
                },
            )

            # Parse response
            import json

            content = result.get("content", "").strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            questions = json.loads(content)

            thoughts = []
            for q in questions[:2]:
                thoughts.append(Thought(
                    thought_type=ThoughtType.CURIOSITY,
                    title=q.get("question", "An interesting question"),
                    content=f"{q.get('context', '')}\n\n{q.get('significance', '')}",
                    summary=q.get("context", ""),
                    salience=0.7,
                    confidence=0.5,
                    novelty=0.8,
                ))

            return thoughts

        except Exception as e:
            raise RuntimeError(
                f"Curiosity generation failed during inference: {e}\n"
                "Guru Meditation: #COG.00000012.LLMCURIOSITY\n"
                "Check: /health endpoints"
            ) from e

    async def _track_momentum(self, context: CognitionContext) -> list[Thought]:
        """Track topic momentum (what's gaining attention)."""
        if not context.recent_kb_entries:
            return []

        # Count topics by domain in recent vs older entries
        recent_cutoff = datetime.now() - timedelta(days=3)

        recent_domains: dict[str, int] = {}
        older_domains: dict[str, int] = {}

        for entry in context.recent_kb_entries:
            domain = entry.get("domain", "general")
            if entry["mtime"] > recent_cutoff:
                recent_domains[domain] = recent_domains.get(domain, 0) + 1
            else:
                older_domains[domain] = older_domains.get(domain, 0) + 1

        # Find domains with momentum
        thoughts = []
        for domain, recent_count in recent_domains.items():
            older_count = older_domains.get(domain, 0)
            if older_count > 0:
                ratio = recent_count / older_count
                if ratio > 2.0 and recent_count >= 3:
                    thoughts.append(Thought(
                        thought_type=ThoughtType.MOMENTUM,
                        title=f"Momentum in {domain}",
                        content=f"Activity in '{domain}' is up {ratio:.1f}x this week ({recent_count} entries vs {older_count} previously).",
                        summary=f"{domain} activity up {ratio:.1f}x",
                        domains=[domain],
                        salience=min(0.5 + (ratio - 2) * 0.1, 0.9),
                        confidence=0.8,
                        novelty=0.6,
                    ))

        return thoughts[:1]  # At most 1 momentum thought

    async def _observe_own_thoughts(self, context: CognitionContext) -> list[Thought]:
        """Generate SELF_OBSERVATION thoughts by analyzing recent thought patterns.

        This is the core of recursive self-observation - thoughts about thoughts.
        Leaning into the recursion: we intentionally allow thoughts to observe
        and build on previous thoughts, including self-observations.
        """
        if len(context.active_thoughts) < 3:
            return []

        from gaius.client import get_grpc_client

        # Analyze thought patterns
        thought_types = {}
        domains_covered = set()
        total_salience = 0.0
        generations = []

        for t in context.active_thoughts:
            thought_types[t.thought_type.value] = thought_types.get(t.thought_type.value, 0) + 1
            domains_covered.update(t.domains)
            total_salience += t.salience
            generations.append(t.generation)

        avg_salience = total_salience / len(context.active_thoughts) if context.active_thoughts else 0.5
        max_generation = max(generations) if generations else 0

        # Format recent thoughts for LLM
        thought_summaries = []
        for t in context.active_thoughts[:10]:
            gen_marker = f" [gen {t.generation}]" if t.generation > 0 else ""
            thought_summaries.append(
                f"- [{t.thought_type.value}]{gen_marker} {t.title}: {t.summary or t.content[:100]}..."
            )

        prompt = f"""You are observing your own thought patterns. Reflect on these recent thoughts:

Recent thoughts ({len(context.active_thoughts)} total):
{chr(10).join(thought_summaries)}

Thought type distribution: {thought_types}
Domains covered: {list(domains_covered)[:5]}
Average salience: {avg_salience:.2f}
Deepest generation: {max_generation}

Generate 1-2 SELF_OBSERVATION thoughts about:
1. What patterns are emerging in your thinking?
2. Are there blind spots or gaps in your observations?
3. How is your understanding evolving over time?
4. Any meta-cognitive observations about the thinking process itself?

Be introspective and specific. Reference actual thoughts when relevant.

Format as JSON array: [{{"title": "...", "observation": "...", "insight": "...", "salience": 0.7}}]"""

        try:
            client = await get_grpc_client()
            result = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": prompt,
                    "agent": "fast",
                    "max_tokens": 600,
                    "temperature": 0.7,
                },
            )

            # Parse response
            import json

            content = result.get("content", "").strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            observations = json.loads(content)

            thoughts = []
            for obs in observations[:2]:
                # Find a predecessor thought to link to (for chain building)
                predecessor = None
                predecessor_id = None
                chain_id = None

                # Link to the most recent SELF_OBSERVATION if one exists
                for t in context.active_thoughts:
                    if t.thought_type == ThoughtType.SELF_OBSERVATION:
                        predecessor = t
                        predecessor_id = t.id
                        chain_id = t.thought_chain_id or t.id
                        break

                thoughts.append(Thought(
                    thought_type=ThoughtType.SELF_OBSERVATION,
                    title=obs.get("title", "Self-observation"),
                    content=f"{obs.get('observation', '')}\n\n{obs.get('insight', '')}",
                    summary=obs.get("observation", "")[:100],
                    salience=float(obs.get("salience", 0.6)),
                    confidence=0.7,
                    novelty=0.8,
                    domains=list(domains_covered)[:3],
                    predecessor_id=predecessor_id,
                    generation=(predecessor.generation + 1) if predecessor else 0,
                    thought_chain_id=chain_id,
                ))

            return thoughts

        except Exception as e:
            raise RuntimeError(
                f"Self-observation failed during inference: {e}\n"
                "Guru Meditation: #COG.00000013.LLMSELFOBS\n"
                "Check: /health endpoints"
            ) from e

    async def _audit_engine_health(self, context: CognitionContext) -> list[Thought]:
        """Generate ENGINE_AUDIT thoughts by observing engine processes.

        Monitors evolution cycles, GPU health, scheduler metrics, and detects anomalies.
        """
        thoughts = []

        # Gather engine metrics from database
        try:
            import asyncpg

            conn = await asyncpg.connect(self.config.database.url)
            try:
                # Get recent evolution cycles
                evolution_rows = await conn.fetch(
                    """
                    SELECT agent_id, success, improvement_percent, duration_ms, error,
                           started_at, preempted
                    FROM evolution_cycles
                    ORDER BY started_at DESC
                    LIMIT 20
                    """,
                )
                evolution_cycles = [dict(r) for r in evolution_rows]

                # Get recent engine observations
                obs_rows = await conn.fetch(
                    """
                    SELECT source, observation_type, metrics, anomalies, observed_at
                    FROM engine_observations
                    WHERE observed_at > NOW() - INTERVAL '24 hours'
                    ORDER BY observed_at DESC
                    LIMIT 50
                    """,
                )
                observations = [dict(r) for r in obs_rows]

            finally:
                await conn.close()

        except Exception as e:
            logger.debug(f"Could not fetch engine metrics: {e}")
            evolution_cycles = []
            observations = []

        # Analyze evolution patterns
        if evolution_cycles:
            recent_failures = [c for c in evolution_cycles[:10] if not c.get("success", True)]
            consecutive_failures = 0
            for c in evolution_cycles:
                if not c.get("success", True):
                    consecutive_failures += 1
                else:
                    break

            if consecutive_failures >= 3:
                # Identify which agents are failing
                failing_agents = list(set(c.get("agent_id", "unknown") for c in recent_failures))
                thoughts.append(Thought(
                    thought_type=ThoughtType.ENGINE_AUDIT,
                    title=f"Evolution struggling: {consecutive_failures} consecutive failures",
                    content=f"The evolution daemon has failed {consecutive_failures} cycles in a row. "
                           f"Affected agents: {', '.join(failing_agents)}. "
                           f"Recent errors: {recent_failures[0].get('error', 'unknown') if recent_failures else 'none'}",
                    summary=f"{consecutive_failures} evolution failures for {', '.join(failing_agents[:2])}",
                    salience=min(0.5 + consecutive_failures * 0.1, 0.9),
                    confidence=0.9,
                    novelty=0.7,
                    domains=["evolution", "engine"],
                ))

            # Check for improvement stagnation
            recent_improvements = [
                c.get("improvement_percent", 0)
                for c in evolution_cycles[:10]
                if c.get("success", False) and c.get("improvement_percent") is not None
            ]
            if len(recent_improvements) >= 5 and all(i <= 0 for i in recent_improvements):
                thoughts.append(Thought(
                    thought_type=ThoughtType.ENGINE_AUDIT,
                    title="Evolution stagnating: no improvements detected",
                    content=f"The last {len(recent_improvements)} successful evolution cycles "
                           f"showed no improvement. This may indicate that agents have reached "
                           f"a local optimum or that training examples need refreshing.",
                    summary="No evolution improvement in recent cycles",
                    salience=0.7,
                    confidence=0.8,
                    novelty=0.6,
                    domains=["evolution", "engine"],
                ))

        # Analyze anomalies from observations
        anomaly_count = sum(
            len(obs.get("anomalies", []))
            for obs in observations
        )
        if anomaly_count > 0:
            anomaly_summary = []
            for obs in observations[:10]:
                for anomaly in obs.get("anomalies", []):
                    anomaly_summary.append(f"- [{obs.get('source')}] {anomaly}")

            if anomaly_summary:
                thoughts.append(Thought(
                    thought_type=ThoughtType.ENGINE_AUDIT,
                    title=f"Engine anomalies detected: {anomaly_count} issues",
                    content=f"Recent anomalies observed:\n\n{chr(10).join(anomaly_summary[:10])}",
                    summary=f"{anomaly_count} anomalies across engine components",
                    salience=min(0.5 + anomaly_count * 0.05, 0.85),
                    confidence=0.85,
                    novelty=0.75,
                    domains=["engine"],
                ))

        return thoughts[:2]  # At most 2 audit thoughts

    async def _generate_interesting_title(self, content: str, thought_type: ThoughtType) -> str:
        """Generate an evocative, content-specific title using LLM.

        Avoids generic titles like "Pattern Detected" in favor of
        specific, intriguing titles that reference the actual content.
        """
        from gaius.client import get_grpc_client

        prompt = f"""Generate an interesting, specific title for this {thought_type.value} thought.

Content: {content[:500]}...

The title should be:
- Specific and evocative (NOT generic like "Pattern Detected" or "Interesting Connection")
- Reference actual concepts from the content
- Be intriguing, hint at the insight
- 5-12 words typically

Examples of GOOD titles:
- "Raft mentions triple this week - consensus fatigue?"
- "LDI frameworks echo climate risk models"
- "Byzantine fault tolerance resurges post-outage"
- "The engine dreams while we sleep"
- "Evolution stalls when examples stale"

Return ONLY the title, no quotes or explanation."""

        try:
            client = await get_grpc_client()
            result = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": prompt,
                    "agent": "fast",
                    "max_tokens": 30,
                    "temperature": 0.7,
                },
            )
            return result.get("content", "").strip().strip('"').strip("'")

        except Exception as e:
            logger.warning(f"Title generation failed: {e}")
            return f"{thought_type.value.replace('_', ' ').title()}"

    def _filter_for_novelty(
        self,
        new_thoughts: list[Thought],
        existing_thoughts: list[Thought],
    ) -> list[Thought]:
        """Filter out thoughts too similar to existing ones."""
        if not existing_thoughts:
            return new_thoughts

        existing_titles = {t.title.lower() for t in existing_thoughts}

        filtered = []
        for thought in new_thoughts:
            title_lower = thought.title.lower()
            # Simple check: skip if title is very similar
            is_duplicate = any(
                self._similarity(title_lower, existing) > 0.8
                for existing in existing_titles
            )
            if not is_duplicate:
                filtered.append(thought)

        return filtered

    def _similarity(self, a: str, b: str) -> float:
        """Simple word overlap similarity."""
        words_a = set(a.split())
        words_b = set(b.split())
        if not words_a or not words_b:
            return 0.0
        intersection = len(words_a & words_b)
        union = len(words_a | words_b)
        return intersection / union if union > 0 else 0.0

    # ─────────────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────────────

    async def _save_thought(self, thought: Thought) -> str | None:
        """Save thought to database, Qdrant, and optionally as project note."""
        import hashlib

        # Generate content hash for exact duplicate detection
        content_hash = hashlib.sha256(
            (thought.title + thought.content).encode()
        ).hexdigest()[:32]
        thought.content_hash = content_hash

        try:
            import asyncpg

            # Check for semantic duplicates using KB VectorSearch
            try:
                from ..inference.search.vector import get_vector_search

                vector_search = get_vector_search(self.config.kb.root)
                is_dup, similar = vector_search.is_duplicate_thought(
                    content=f"{thought.title}\n\n{thought.content}",
                    threshold=0.95,  # Very high = nearly identical
                )
                if is_dup and similar:
                    logger.debug(
                        f"Rejecting near-duplicate thought (similarity={similar.score:.2f}): {thought.title}"
                    )
                    return None
            except Exception as e:
                logger.debug(f"Vector search duplicate check unavailable: {e}")

            conn = await asyncpg.connect(self.config.database.url)
            try:
                # Check for exact hash duplicates (fallback/belt-and-suspenders)
                duplicate_count = await conn.fetchval(
                    """
                    SELECT count_exact_duplicates($1, $2, 7)
                    """,
                    content_hash,
                    self.profile,
                )

                # Allow some repetition but reject spam (>= 3 identical thoughts)
                if duplicate_count >= 3:
                    logger.debug(f"Rejecting exact duplicate thought: {thought.title}")
                    return None

                result = await conn.fetchval(
                    """
                    INSERT INTO cognition_thoughts
                        (thought_type, status, title, content, summary,
                         domains, kb_paths, source_entries,
                         salience, confidence, novelty, profile_name,
                         predecessor_id, generation, thought_chain_id, content_hash)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                            $13::uuid, $14, $15::uuid, $16)
                    RETURNING id
                    """,
                    thought.thought_type.value,
                    thought.status.value,
                    thought.title,
                    thought.content,
                    thought.summary,
                    thought.domains,
                    thought.kb_paths,
                    thought.source_entries,
                    thought.salience,
                    thought.confidence,
                    thought.novelty,
                    self.profile,
                    thought.predecessor_id,
                    thought.generation,
                    thought.thought_chain_id,
                    content_hash,
                )
                thought.id = str(result)

                # Save as project note with prev:/next: linking
                note_path = await self._save_thought_as_note(thought)
                if note_path:
                    thought.note_path = note_path
                    # Update the DB with the note path
                    await conn.execute(
                        "UPDATE cognition_thoughts SET note_path = $1 WHERE id = $2",
                        note_path,
                        result,
                    )

                # Note: Thought will be indexed in Qdrant when KB is re-indexed
                # The note file is saved with doc_type metadata for filtering

                return thought.id

            finally:
                await conn.close()

        except Exception as e:
            raise RuntimeError(
                f"Failed to save thought to database: {e}\n"
                "Guru Meditation: #COG.00000014.DBSAVE\n"
                "Check: /health postgres"
            ) from e

    async def _save_thought_as_note(self, thought: Thought) -> str | None:
        """Save thought as a project note with bidirectional prev:/next: linking."""
        try:
            from ..core.project_notes import find_previous_project_note, _update_next_link

            kb_root = Path(self.config.kb.root)
            note_type = f"thought_{thought.thought_type.value}"

            # Find previous note of this type
            prev_note = find_previous_project_note(kb_root, note_type)

            # Create today's scratch directory
            now = datetime.now()
            date_str = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H%M%S")
            scratch_dir = kb_root / "scratch" / date_str
            scratch_dir.mkdir(parents=True, exist_ok=True)

            # Build prev: link
            prev_link = ""
            if prev_note:
                try:
                    prev_rel = prev_note.relative_to(kb_root)
                    prev_link = f"[[{prev_rel}]]"
                except ValueError:
                    # Fallback: use just the filename stem to avoid absolute paths in links
                    prev_link = f"[[{prev_note.stem}]]"

            # Build note content
            note_content = f"""[[current/agents/cognition]]
prev: {prev_link}
next:

# {thought.title}

---
created: {now.isoformat()}
type: {thought.thought_type.value}
thought_id: {thought.id}
salience: {thought.salience:.2f}
generation: {thought.generation}
---

{thought.content}

## Metadata

- **Domains:** {', '.join(thought.domains) if thought.domains else 'general'}
- **Confidence:** {thought.confidence:.2f}
- **Novelty:** {thought.novelty:.2f}
"""
            if thought.predecessor_id:
                note_content += f"- **Predecessor:** {thought.predecessor_id}\n"

            if thought.kb_paths:
                note_content += "\n## Related\n\n"
                for path in thought.kb_paths[:5]:
                    note_content += f"- [[{path}]]\n"

            note_content += "\n---\n\n*This note is part of the knowledge base. Edit, link, or dismiss as you wish.*\n"

            # Write the note
            note_path = scratch_dir / f"{time_str}_{note_type}.md"
            note_path.write_text(note_content)

            # Update previous note's next: field
            if prev_note and prev_note.exists():
                _update_next_link(prev_note, kb_root, note_path)

            return str(note_path.relative_to(kb_root))

        except Exception as e:
            raise RuntimeError(
                f"Failed to save thought as note: {e}\n"
                "Guru Meditation: #COG.00000015.KBWRITE\n"
                "Check: KB scratch directory is writable"
            ) from e

    async def _record_cycle(self, result: CognitionResult) -> None:
        """Record cognition cycle to database."""
        try:
            import asyncpg

            conn = await asyncpg.connect(self.config.database.url)
            try:
                cycle_id = await conn.fetchval(
                    """
                    INSERT INTO cognition_cycles
                        (profile_name, completed_at, duration_ms, trigger_reason,
                         thoughts_generated, patterns_detected, connections_found,
                         model_used, tokens_used, content_items_analyzed, kb_entries_scanned,
                         success)
                    VALUES ($1, NOW(), $2, $3, $4, $5, $6, $7, $8, $9, $10, TRUE)
                    RETURNING id
                    """,
                    self.profile,
                    result.duration_ms,
                    result.trigger_reason,
                    len(result.thoughts),
                    result.patterns_detected,
                    result.connections_found,
                    result.model_used,
                    result.tokens_used,
                    result.content_analyzed,
                    result.kb_entries_scanned,
                )
                result.cycle_id = cycle_id

            finally:
                await conn.close()

        except Exception as e:
            raise RuntimeError(
                f"Failed to record cognition cycle: {e}\n"
                "Guru Meditation: #COG.00000016.DBCYCLE\n"
                "Check: /health postgres"
            ) from e


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_agent: CognitionAgent | None = None


def get_cognition_agent(profile: str = "default") -> CognitionAgent:
    """Get or create the cognition agent singleton."""
    global _agent
    if _agent is None or _agent.profile != profile:
        _agent = CognitionAgent(profile)
    return _agent


async def trigger_cognition(
    reason: str = "manual",
    max_thoughts: int = 5,
    profile: str = "default",
) -> CognitionResult:
    """Convenience function to trigger a cognition cycle."""
    agent = get_cognition_agent(profile)
    return await agent.think(max_thoughts=max_thoughts, trigger_reason=reason)
