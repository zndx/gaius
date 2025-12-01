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

    PATTERN = "pattern"
    CONNECTION = "connection"
    CURIOSITY = "curiosity"
    MOMENTUM = "momentum"
    OBSERVATION = "observation"
    SYNTHESIS = "synthesis"


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

    def to_markdown(self) -> str:
        """Format thought as markdown section."""
        emoji = {
            ThoughtType.PATTERN: "📊",
            ThoughtType.CONNECTION: "🔗",
            ThoughtType.CURIOSITY: "❓",
            ThoughtType.MOMENTUM: "📈",
            ThoughtType.OBSERVATION: "👁️",
            ThoughtType.SYNTHESIS: "🧩",
        }.get(self.thought_type, "💭")

        lines = [f"### {emoji} {self.title}"]

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
        }


@dataclass
class CognitionContext:
    """All context available for a cognition cycle."""

    # Recent content
    recent_kb_entries: list[dict] = field(default_factory=list)
    recent_content_items: list[dict] = field(default_factory=list)

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


@dataclass
class CognitionResult:
    """Result of a cognition cycle."""

    thoughts: list[Thought]
    cycle_id: int | None = None

    # Metrics
    patterns_detected: int = 0
    connections_found: int = 0
    curiosities_generated: int = 0

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
            logger.warning(f"Failed to get active thoughts: {e}")
            return []

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
            logger.warning(f"Failed to mark thoughts surfaced: {e}")

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
            logger.warning(f"Failed to scan KB entries: {e}")

        return entries[:100]  # Limit for performance

    async def _get_recent_content_items(self, days: int = 7) -> list[dict]:
        """Get recently fetched content items."""
        try:
            import asyncpg

            conn = await asyncpg.connect(self.config.database.url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT id, title, source_name, kb_path, fetched_at
                    FROM content_items
                    WHERE fetched_at > NOW() - ($1 || ' days')::INTERVAL
                    ORDER BY fetched_at DESC
                    LIMIT 100
                    """,
                    str(days),
                )
                return [dict(row) for row in rows]
            finally:
                await conn.close()

        except Exception:
            return []

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

        except Exception:
            return []

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

        except Exception:
            return []

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

        except Exception:
            return []

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

        except Exception:
            return timedelta(days=999)

    # ─────────────────────────────────────────────────────────────────────────
    # Thought Generation Strategies
    # ─────────────────────────────────────────────────────────────────────────

    async def _detect_patterns(self, context: CognitionContext) -> list[Thought]:
        """Detect patterns in recent content using LLM."""
        if not context.recent_kb_entries:
            return []

        from ..inference import get_client, Message

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
            client = get_client()
            result = await client.complete(
                [Message(role="user", content=prompt)],
                max_tokens=500,
                temperature=0.6,
            )

            # Parse response
            import json

            content = result.content.strip()
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
            logger.warning(f"Pattern detection failed: {e}")
            return []

    async def _find_connections(self, context: CognitionContext) -> list[Thought]:
        """Find cross-domain connections using LLM."""
        if len(context.domains_active) < 2:
            return []

        from ..inference import get_client, Message

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
            client = get_client()
            result = await client.complete(
                [Message(role="user", content=prompt)],
                max_tokens=400,
                temperature=0.7,  # Higher for creative connections
            )

            # Parse response
            import json

            content = result.content.strip()
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
            logger.warning(f"Connection finding failed: {e}")
            return []

    async def _generate_curiosities(self, context: CognitionContext) -> list[Thought]:
        """Generate curiosity-driven questions."""
        from ..inference import get_client, Message

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
            client = get_client()
            result = await client.complete(
                [Message(role="user", content=prompt)],
                max_tokens=400,
                temperature=0.7,
            )

            # Parse response
            import json

            content = result.content.strip()
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
            logger.warning(f"Curiosity generation failed: {e}")
            return []

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
        """Save thought to database, return ID."""
        try:
            import asyncpg

            conn = await asyncpg.connect(self.config.database.url)
            try:
                result = await conn.fetchval(
                    """
                    INSERT INTO cognition_thoughts
                        (thought_type, status, title, content, summary,
                         domains, kb_paths, source_entries,
                         salience, confidence, novelty, profile_name)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
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
                )
                thought.id = str(result)
                return thought.id

            finally:
                await conn.close()

        except Exception as e:
            logger.warning(f"Failed to save thought: {e}")
            return None

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
            logger.warning(f"Failed to record cognition cycle: {e}")


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
