"""Reflection Agent for Gaius.

Performs deep, quality thinking on demand - not just summarizing activity,
but synthesizing understanding, generating questions, and calibrating confidence.

Key Capabilities:
- Cross-domain pattern synthesis
- Question generation (what should we explore next?)
- Confidence calibration (what do we really know?)
- Perspective evolution tracking

This is the agent that makes Gaius feel thoughtful rather than just reactive.

Usage:
    from gaius.agents.reflection import ReflectionAgent, get_reflection_agent

    agent = get_reflection_agent()
    result = await agent.reflect(depth="deep")
    print(result.synthesis)
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any
import logging

from ..core.config import get_config

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Enums and Data Classes
# ═══════════════════════════════════════════════════════════════════════════════


class ReflectionDepth(str, Enum):
    """Depth of reflection."""

    QUICK = "quick"      # Fast, surface-level (< 5s)
    MODERATE = "moderate"  # Balanced depth (5-15s)
    DEEP = "deep"        # Thorough analysis (15-60s)


class InsightType(str, Enum):
    """Types of insights from reflection."""

    SYNTHESIS = "synthesis"        # Consolidated understanding
    GAP = "gap"                    # Knowledge gap identified
    QUESTION = "question"          # Question worth exploring
    EVOLUTION = "evolution"        # How understanding has changed
    CONFIDENCE = "confidence"      # Confidence assessment
    RECOMMENDATION = "recommendation"  # Suggested action


@dataclass
class Insight:
    """A single insight from reflection."""

    insight_type: InsightType
    title: str
    content: str

    # Scoring
    importance: float = 0.5  # 0-1
    actionable: bool = False

    # Context
    domains: list[str] = field(default_factory=list)
    related_entries: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.insight_type.value,
            "title": self.title,
            "content": self.content,
            "importance": self.importance,
            "actionable": self.actionable,
            "domains": self.domains,
            "related_entries": self.related_entries,
        }

    def to_markdown(self) -> str:
        """Format as markdown."""
        indicator = {
            InsightType.SYNTHESIS: "[SYNTH]",
            InsightType.GAP: "[GAP]",
            InsightType.QUESTION: "[?]",
            InsightType.EVOLUTION: "[EVOL]",
            InsightType.CONFIDENCE: "[CONF]",
            InsightType.RECOMMENDATION: "[REC]",
        }.get(self.insight_type, "[*]")

        lines = [f"### {indicator} {self.title}"]
        lines.append(self.content)

        if self.related_entries:
            lines.append("")
            lines.append("**Related:**")
            for entry in self.related_entries[:3]:
                lines.append(f"- [[{entry}]]")

        return "\n".join(lines)


@dataclass
class ReflectionResult:
    """Result of a reflection session."""

    depth: ReflectionDepth
    insights: list[Insight] = field(default_factory=list)

    # Main outputs
    synthesis: str = ""           # Main synthesis paragraph
    questions: list[str] = field(default_factory=list)  # Generated questions
    confidence_notes: str = ""    # What we're certain/uncertain about
    recommendations: list[str] = field(default_factory=list)

    # Metrics
    domains_analyzed: list[str] = field(default_factory=list)
    entries_considered: int = 0
    duration_ms: int = 0
    model_used: str = ""
    tokens_used: int = 0

    # Timestamp
    generated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "depth": self.depth.value,
            "insights": [i.to_dict() for i in self.insights],
            "synthesis": self.synthesis,
            "questions": self.questions,
            "confidence_notes": self.confidence_notes,
            "recommendations": self.recommendations,
            "domains_analyzed": self.domains_analyzed,
            "entries_considered": self.entries_considered,
            "duration_ms": self.duration_ms,
            "model_used": self.model_used,
            "tokens_used": self.tokens_used,
            "generated_at": self.generated_at.isoformat(),
        }

    def to_markdown(self) -> str:
        """Format as Zettelkasten markdown."""
        lines = [
            "## Reflection",
            "",
            f"*Depth: {self.depth.value} | "
            f"Domains: {', '.join(self.domains_analyzed) or 'general'} | "
            f"{self.generated_at.strftime('%Y-%m-%d %H:%M')}*",
            "",
        ]

        # Main synthesis
        if self.synthesis:
            lines.append("### Synthesis")
            lines.append(self.synthesis)
            lines.append("")

        # Questions
        if self.questions:
            lines.append("### Questions Worth Exploring")
            for q in self.questions:
                lines.append(f"1. {q}")
            lines.append("")

        # Confidence
        if self.confidence_notes:
            lines.append("### Confidence Assessment")
            lines.append(self.confidence_notes)
            lines.append("")

        # Recommendations
        if self.recommendations:
            lines.append("### Recommendations")
            for r in self.recommendations:
                lines.append(f"- {r}")
            lines.append("")

        # Detailed insights
        if self.insights:
            lines.append("### Detailed Insights")
            for insight in self.insights:
                lines.append(insight.to_markdown())
                lines.append("")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Reflection Agent
# ═══════════════════════════════════════════════════════════════════════════════


class ReflectionAgent:
    """Agent that performs deep reflection on accumulated knowledge.

    Unlike CognitionAgent (which runs in background), ReflectionAgent
    is triggered on demand for quality synthesis.
    """

    def __init__(self, profile: str = "default"):
        self.profile = profile
        self.config = get_config()

    async def reflect(
        self,
        depth: ReflectionDepth | str = ReflectionDepth.MODERATE,
        focus_domains: list[str] | None = None,
        focus_topic: str | None = None,
    ) -> ReflectionResult:
        """Perform reflection on accumulated knowledge.

        Args:
            depth: How deep to reflect (quick, moderate, deep)
            focus_domains: Limit to specific domains
            focus_topic: Focus on specific topic

        Returns:
            ReflectionResult with insights and synthesis
        """
        import time

        start_time = time.time()

        if isinstance(depth, str):
            depth = ReflectionDepth(depth)

        result = ReflectionResult(depth=depth)

        # Gather context based on depth
        context = await self._gather_context(depth, focus_domains, focus_topic)
        result.entries_considered = len(context.get("entries", []))
        result.domains_analyzed = context.get("domains", [])

        # Generate synthesis
        synthesis = await self._synthesize(context, depth)
        result.synthesis = synthesis.get("synthesis", "")
        result.model_used = synthesis.get("model", "")
        result.tokens_used = synthesis.get("tokens", 0)

        # Generate questions
        if depth in (ReflectionDepth.MODERATE, ReflectionDepth.DEEP):
            result.questions = await self._generate_questions(context, result.synthesis)

        # Assess confidence
        if depth == ReflectionDepth.DEEP:
            result.confidence_notes = await self._assess_confidence(context, result.synthesis)
            result.recommendations = await self._generate_recommendations(context, result)

        # Extract insights
        result.insights = self._extract_insights(result)

        result.duration_ms = int((time.time() - start_time) * 1000)
        result.generated_at = datetime.now()

        return result

    async def quick_thought(self, topic: str) -> str:
        """Generate a quick thought on a specific topic.

        Args:
            topic: Topic to think about

        Returns:
            Brief reflection paragraph
        """
        from gaius.client import get_grpc_client

        # Get relevant KB entries
        entries = await self._get_relevant_entries(topic)

        entry_context = ""
        if entries:
            entry_context = "\n".join(
                f"- {e['title']}: {e['preview'][:100]}..."
                for e in entries[:5]
            )

        prompt = f"""Generate a brief, thoughtful reflection on: {topic}

Relevant knowledge:
{entry_context or 'No specific entries found'}

Write 2-3 sentences that:
- Synthesize what we know about this topic
- Note any interesting connections or gaps
- Are specific, not generic

Be direct and insightful."""

        try:
            client = await get_grpc_client()
            response = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": prompt,
                    "agent": "instruct",
                    "max_tokens": 150,
                    "temperature": 0.6,
                },
            )
            return response.get("content", "").strip()

        except Exception as e:
            logger.warning(f"Quick thought failed: {e}")
            return f"Thinking about {topic}..."

    async def compare_domains(
        self,
        domain1: str,
        domain2: str,
    ) -> dict[str, Any]:
        """Compare two domains for patterns and connections.

        Args:
            domain1: First domain
            domain2: Second domain

        Returns:
            Comparison result with shared patterns, unique aspects, connections
        """
        from gaius.client import get_grpc_client

        # Get entries from each domain
        entries1 = await self._get_domain_entries(domain1)
        entries2 = await self._get_domain_entries(domain2)

        if not entries1 or not entries2:
            return {
                "error": "Insufficient entries for comparison",
                "domain1_entries": len(entries1),
                "domain2_entries": len(entries2),
            }

        # Build context
        context1 = "\n".join(f"- {e['title']}" for e in entries1[:10])
        context2 = "\n".join(f"- {e['title']}" for e in entries2[:10])

        prompt = f"""Compare these two knowledge domains:

**{domain1}:**
{context1}

**{domain2}:**
{context2}

Analyze:
1. Shared patterns or themes between domains
2. What's unique to each domain
3. Potential connections or cross-pollination opportunities
4. Gaps that one domain could inform the other about

Format as JSON:
{{
  "shared_patterns": ["..."],
  "unique_to_{domain1}": ["..."],
  "unique_to_{domain2}": ["..."],
  "connections": ["..."],
  "cross_pollination": ["..."]
}}"""

        try:
            client = await get_grpc_client()
            response = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": prompt,
                    "agent": "instruct",
                    "max_tokens": 600,
                    "temperature": 0.6,
                },
            )

            import json

            content = response.get("content", "").strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            result = json.loads(content)
            result["domain1"] = domain1
            result["domain2"] = domain2
            result["model"] = response.get("model", "")

            return result

        except Exception as e:
            logger.warning(f"Domain comparison failed: {e}")
            return {"error": str(e)}

    async def calibrate_understanding(
        self,
        topic: str,
    ) -> dict[str, Any]:
        """Calibrate confidence in understanding of a topic.

        Args:
            topic: Topic to assess

        Returns:
            Calibration with high/medium/low confidence areas
        """
        from gaius.client import get_grpc_client

        entries = await self._get_relevant_entries(topic, limit=20)

        if len(entries) < 3:
            return {
                "topic": topic,
                "confidence": "low",
                "reason": f"Only {len(entries)} entries found - insufficient for calibration",
                "entry_count": len(entries),
            }

        # Build context
        entry_list = "\n".join(
            f"- {e['title']}: {e['preview'][:150]}"
            for e in entries[:15]
        )

        prompt = f"""Assess understanding of: {topic}

Available knowledge:
{entry_list}

Calibrate understanding:
1. What aspects do we understand well (high confidence)?
2. What do we partially understand (medium confidence)?
3. What are we uncertain about or is missing (low confidence)?
4. What would deepen understanding?

Format as JSON:
{{
  "overall_confidence": "high|medium|low",
  "high_confidence": ["specific aspects we understand well"],
  "medium_confidence": ["aspects with partial understanding"],
  "low_confidence": ["uncertain areas or gaps"],
  "to_deepen": ["what would help"]
}}"""

        try:
            client = await get_grpc_client()
            response = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": prompt,
                    "agent": "instruct",
                    "max_tokens": 500,
                    "temperature": 0.4,
                },
            )

            import json

            content = response.get("content", "").strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            result = json.loads(content)
            result["topic"] = topic
            result["entry_count"] = len(entries)
            result["model"] = response.get("model", "")

            return result

        except Exception as e:
            logger.warning(f"Calibration failed: {e}")
            return {"topic": topic, "error": str(e)}

    # ─────────────────────────────────────────────────────────────────────────
    # Private Methods
    # ─────────────────────────────────────────────────────────────────────────

    async def _gather_context(
        self,
        depth: ReflectionDepth,
        focus_domains: list[str] | None,
        focus_topic: str | None,
    ) -> dict[str, Any]:
        """Gather context for reflection."""
        context: dict[str, Any] = {
            "entries": [],
            "domains": [],
            "recent_activity": [],
            "thoughts": [],
        }

        # Determine how many entries to analyze based on depth
        entry_limits = {
            ReflectionDepth.QUICK: 10,
            ReflectionDepth.MODERATE: 30,
            ReflectionDepth.DEEP: 50,
        }
        limit = entry_limits.get(depth, 30)

        # Get KB entries
        if focus_topic:
            context["entries"] = await self._get_relevant_entries(focus_topic, limit)
        elif focus_domains:
            for domain in focus_domains:
                entries = await self._get_domain_entries(domain, limit // len(focus_domains))
                context["entries"].extend(entries)
        else:
            context["entries"] = await self._get_recent_entries(limit)

        # Extract domains
        domains = set()
        for entry in context["entries"]:
            if entry.get("domain"):
                domains.add(entry["domain"])
        context["domains"] = list(domains)

        # Get recent activity
        if depth in (ReflectionDepth.MODERATE, ReflectionDepth.DEEP):
            context["recent_activity"] = await self._get_recent_activity()

        # Get recent cognition thoughts
        if depth == ReflectionDepth.DEEP:
            context["thoughts"] = await self._get_recent_thoughts()

        return context

    async def _synthesize(
        self,
        context: dict[str, Any],
        depth: ReflectionDepth,
    ) -> dict[str, Any]:
        """Generate synthesis from context."""
        from gaius.client import get_grpc_client

        entries = context.get("entries", [])
        if not entries:
            return {"synthesis": "No content available for synthesis.", "tokens": 0}

        # Build entry summary
        entry_summaries = []
        for entry in entries[:30]:
            title = entry.get("title", "Untitled")
            preview = entry.get("preview", "")[:100]
            domain = entry.get("domain", "")
            entry_summaries.append(f"- [{domain}] {title}: {preview}")

        domains = ", ".join(context.get("domains", [])) or "general"

        # Adjust prompt based on depth
        depth_instruction = {
            ReflectionDepth.QUICK: "Write 2-3 sentences capturing the key theme.",
            ReflectionDepth.MODERATE: "Write a paragraph synthesizing the main patterns and insights.",
            ReflectionDepth.DEEP: "Write 2-3 paragraphs with deep analysis of themes, patterns, and implications.",
        }.get(depth, "Write a thoughtful synthesis.")

        prompt = f"""Synthesize understanding from this knowledge base content.

Domains: {domains}

Entries ({len(entries)} total):
{chr(10).join(entry_summaries)}

{depth_instruction}

Focus on:
- Emerging patterns and themes
- Non-obvious connections
- What this collection of knowledge suggests

Be specific and insightful, not generic."""

        try:
            client = await get_grpc_client()
            response = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": prompt,
                    "agent": "instruct",
                    "max_tokens": 400 if depth == ReflectionDepth.DEEP else 200,
                    "temperature": 0.6,
                },
            )

            return {
                "synthesis": response.get("content", "").strip(),
                "model": response.get("model", ""),
                "tokens": response.get("input_tokens", 0) + response.get("output_tokens", 0),
            }

        except Exception as e:
            logger.warning(f"Synthesis failed: {e}")
            return {"synthesis": f"Synthesis unavailable: {e}", "tokens": 0}

    async def _generate_questions(
        self,
        context: dict[str, Any],
        synthesis: str,
    ) -> list[str]:
        """Generate questions worth exploring."""
        from gaius.client import get_grpc_client

        domains = ", ".join(context.get("domains", [])) or "general"

        prompt = f"""Based on this knowledge synthesis, generate 3 questions worth exploring.

Domains: {domains}

Current synthesis:
{synthesis}

Generate questions that:
- Cannot be answered by simple lookup
- Would deepen understanding
- Connect multiple concepts
- Are tractable (not too vague)

Return only the questions, one per line."""

        try:
            client = await get_grpc_client()
            response = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": prompt,
                    "agent": "instruct",
                    "max_tokens": 200,
                    "temperature": 0.7,
                },
            )

            questions = []
            for line in response.get("content", "").strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    # Clean up numbering
                    if line[0].isdigit() and line[1] in ".):":
                        line = line[2:].strip()
                    if line:
                        questions.append(line)

            return questions[:3]

        except Exception as e:
            logger.warning(f"Question generation failed: {e}")
            return []

    async def _assess_confidence(
        self,
        context: dict[str, Any],
        synthesis: str,
    ) -> str:
        """Assess confidence in current understanding."""
        from gaius.client import get_grpc_client

        entry_count = len(context.get("entries", []))
        domains = context.get("domains", [])

        prompt = f"""Assess confidence in this understanding.

Entry count: {entry_count}
Domains: {', '.join(domains) or 'general'}

Synthesis:
{synthesis}

Write 2-3 sentences about:
- What we can be confident about
- Where uncertainty remains
- What would increase confidence

Be specific and honest about limitations."""

        try:
            client = await get_grpc_client()
            response = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": prompt,
                    "agent": "instruct",
                    "max_tokens": 150,
                    "temperature": 0.4,
                },
            )

            return response.get("content", "").strip()

        except Exception as e:
            logger.warning(f"Confidence assessment failed: {e}")
            return ""

    async def _generate_recommendations(
        self,
        context: dict[str, Any],
        result: ReflectionResult,
    ) -> list[str]:
        """Generate actionable recommendations."""
        from gaius.client import get_grpc_client

        prompt = f"""Based on this reflection, suggest 2-3 actionable next steps.

Synthesis: {result.synthesis}

Questions: {', '.join(result.questions) if result.questions else 'None'}

Confidence: {result.confidence_notes}

Suggest concrete actions like:
- Specific topics to research
- Knowledge gaps to fill
- Connections to explore

Return only the recommendations, one per line."""

        try:
            client = await get_grpc_client()
            response = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": prompt,
                    "agent": "instruct",
                    "max_tokens": 150,
                    "temperature": 0.5,
                },
            )

            recommendations = []
            for line in response.get("content", "").strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    if line[0] in "-•*":
                        line = line[1:].strip()
                    if line:
                        recommendations.append(line)

            return recommendations[:3]

        except Exception as e:
            logger.warning(f"Recommendation generation failed: {e}")
            return []

    def _extract_insights(self, result: ReflectionResult) -> list[Insight]:
        """Extract structured insights from reflection result."""
        insights = []

        # Synthesis insight
        if result.synthesis:
            insights.append(Insight(
                insight_type=InsightType.SYNTHESIS,
                title="Knowledge Synthesis",
                content=result.synthesis,
                importance=0.8,
                domains=result.domains_analyzed,
            ))

        # Question insights
        for q in result.questions:
            insights.append(Insight(
                insight_type=InsightType.QUESTION,
                title=q[:50] + "..." if len(q) > 50 else q,
                content=q,
                importance=0.6,
                actionable=True,
            ))

        # Confidence insight
        if result.confidence_notes:
            insights.append(Insight(
                insight_type=InsightType.CONFIDENCE,
                title="Understanding Confidence",
                content=result.confidence_notes,
                importance=0.7,
            ))

        # Recommendation insights
        for r in result.recommendations:
            insights.append(Insight(
                insight_type=InsightType.RECOMMENDATION,
                title=r[:50] + "..." if len(r) > 50 else r,
                content=r,
                importance=0.7,
                actionable=True,
            ))

        return insights

    async def _get_relevant_entries(
        self,
        topic: str,
        limit: int = 20,
    ) -> list[dict]:
        """Get KB entries relevant to a topic."""
        from pathlib import Path

        entries = []
        kb_root = Path(self.config.kb.root)
        topic_lower = topic.lower()
        keywords = set(topic_lower.split())

        try:
            for path in kb_root.rglob("*.md"):
                try:
                    content = path.read_text(encoding="utf-8")
                    content_lower = content.lower()

                    # Check relevance (simple keyword matching)
                    if topic_lower in content_lower or any(kw in content_lower for kw in keywords):
                        lines = content.split("\n")
                        title = lines[0].lstrip("#").strip() if lines else path.stem

                        rel_path = path.relative_to(kb_root)
                        domain = rel_path.parts[1] if len(rel_path.parts) > 1 else "general"

                        entries.append({
                            "path": str(rel_path),
                            "title": title,
                            "preview": " ".join(lines[1:5]).strip()[:200],
                            "domain": domain,
                            "mtime": datetime.fromtimestamp(path.stat().st_mtime),
                        })

                except Exception:
                    continue

            # Sort by recency
            entries.sort(key=lambda e: e["mtime"], reverse=True)

        except Exception as e:
            logger.warning(f"Failed to get relevant entries: {e}")

        return entries[:limit]

    async def _get_domain_entries(
        self,
        domain: str,
        limit: int = 20,
    ) -> list[dict]:
        """Get entries from a specific domain."""
        from pathlib import Path

        entries = []
        domain_path = Path(self.config.kb.root) / "current" / domain

        if not domain_path.exists():
            # Try without "current" prefix
            domain_path = Path(self.config.kb.root) / domain

        if not domain_path.exists():
            return entries

        try:
            for path in domain_path.rglob("*.md"):
                try:
                    content = path.read_text(encoding="utf-8")
                    lines = content.split("\n")
                    title = lines[0].lstrip("#").strip() if lines else path.stem

                    entries.append({
                        "path": str(path.relative_to(Path(self.config.kb.root))),
                        "title": title,
                        "preview": " ".join(lines[1:5]).strip()[:200],
                        "domain": domain,
                        "mtime": datetime.fromtimestamp(path.stat().st_mtime),
                    })

                except Exception:
                    continue

            entries.sort(key=lambda e: e["mtime"], reverse=True)

        except Exception as e:
            logger.warning(f"Failed to get domain entries: {e}")

        return entries[:limit]

    async def _get_recent_entries(self, limit: int = 30) -> list[dict]:
        """Get recent KB entries across all domains."""
        from pathlib import Path

        entries = []
        kb_root = Path(self.config.kb.root)
        cutoff = datetime.now() - timedelta(days=14)

        try:
            for path in kb_root.rglob("*.md"):
                try:
                    mtime = datetime.fromtimestamp(path.stat().st_mtime)
                    if mtime > cutoff:
                        content = path.read_text(encoding="utf-8")
                        lines = content.split("\n")
                        title = lines[0].lstrip("#").strip() if lines else path.stem

                        rel_path = path.relative_to(kb_root)
                        domain = rel_path.parts[1] if len(rel_path.parts) > 1 else "general"

                        entries.append({
                            "path": str(rel_path),
                            "title": title,
                            "preview": " ".join(lines[1:5]).strip()[:200],
                            "domain": domain,
                            "mtime": mtime,
                        })

                except Exception:
                    continue

            entries.sort(key=lambda e: e["mtime"], reverse=True)

        except Exception as e:
            logger.warning(f"Failed to get recent entries: {e}")

        return entries[:limit]

    async def _get_recent_activity(self) -> list[dict]:
        """Get recent activity events."""
        try:
            import asyncpg

            conn = await asyncpg.connect(self.config.database.url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT event_type, domain, details, created_at
                    FROM activity_events
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                    ORDER BY created_at DESC
                    LIMIT 20
                    """,
                )
                return [dict(row) for row in rows]

            finally:
                await conn.close()

        except Exception:
            return []

    async def _get_recent_thoughts(self) -> list[dict]:
        """Get recent cognition thoughts."""
        try:
            import asyncpg

            conn = await asyncpg.connect(self.config.database.url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT thought_type, title, summary, salience
                    FROM cognition_thoughts
                    WHERE profile_name = $1
                      AND status = 'active'
                    ORDER BY salience DESC, created_at DESC
                    LIMIT 5
                    """,
                    self.profile,
                )
                return [dict(row) for row in rows]

            finally:
                await conn.close()

        except Exception:
            return []


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_agent: ReflectionAgent | None = None


def get_reflection_agent(profile: str = "default") -> ReflectionAgent:
    """Get or create the reflection agent singleton."""
    global _agent
    if _agent is None or _agent.profile != profile:
        _agent = ReflectionAgent(profile)
    return _agent


async def reflect(
    depth: str = "moderate",
    focus_domains: list[str] | None = None,
    focus_topic: str | None = None,
    profile: str = "default",
) -> ReflectionResult:
    """Convenience function to trigger reflection."""
    agent = get_reflection_agent(profile)
    return await agent.reflect(
        depth=ReflectionDepth(depth),
        focus_domains=focus_domains,
        focus_topic=focus_topic,
    )
