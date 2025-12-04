"""Evaluation framework for evolution tracking.

Provides:
- HeldOutManager: Rolling window of queries not used for training
- DailyEvaluator: Comprehensive daily evaluation against held-out set
- ReportGenerator: Markdown summaries for human review

The key insight is separating training evaluation from held-out evaluation
to detect overfitting and ensure genuine improvement.
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class HeldOutQuery:
    """A query in the held-out evaluation pool."""

    id: int
    input_prompt: str
    expected_output: Optional[str]
    context: Optional[str]
    domain: str
    category: str
    difficulty: float
    source_type: str
    created_at: datetime


@dataclass
class EvalResult:
    """Result from evaluating an agent on a single query."""

    query_id: int
    agent_id: str
    version_id: str
    overall_score: float
    dimension_scores: dict
    output: str
    latency_ms: int
    eval_type: str  # 'training' or 'held_out'


@dataclass
class DailyEvalSummary:
    """Summary of a day's evaluation results."""

    eval_date: date
    total_cycles: int
    successful_cycles: int
    total_improvement_percent: float
    agent_summaries: dict
    held_out_results: dict
    trend_direction: str  # 'improving', 'stable', 'declining'
    trend_confidence: float
    notes: str = ""


class HeldOutManager:
    """Manages rolling window of held-out evaluation queries.

    Queries are collected from:
    - Swarm runs (questions asked)
    - Research topics
    - Manual additions

    Queries older than window_days are retired. Queries used for
    training are excluded from the held-out pool.
    """

    # Rolling window size
    WINDOW_DAYS = 30

    # Minimum queries to maintain
    MIN_QUERIES = 20

    # Maximum queries to keep
    MAX_QUERIES = 200

    # Sample size for daily eval
    DAILY_SAMPLE_SIZE = 50

    def __init__(self, db_url: Optional[str] = None):
        """Initialize held-out manager.

        Args:
            db_url: PostgreSQL connection URL
        """
        self.db_url = db_url
        self._pool = None

    async def _get_pool(self):
        """Get or create connection pool."""
        if self._pool is None:
            import asyncpg
            import os

            url = self.db_url or os.getenv(
                "DATABASE_URL",
                "postgresql://gaius:gaius@localhost:5432/gaius"
            )
            self._pool = await asyncpg.create_pool(url)
        return self._pool

    def _hash_query(self, prompt: str) -> str:
        """Generate hash for deduplication."""
        return hashlib.sha256(prompt.encode()).hexdigest()[:32]

    async def add_query(
        self,
        input_prompt: str,
        expected_output: Optional[str] = None,
        context: Optional[str] = None,
        domain: str = "",
        category: str = "",
        difficulty: float = 0.5,
        source_type: str = "swarm",
        source_id: Optional[str] = None,
    ) -> Optional[int]:
        """Add a query to the held-out pool.

        Args:
            input_prompt: The query/prompt text
            expected_output: Optional gold standard output
            context: Additional context
            domain: Domain classification
            category: Task category
            difficulty: Estimated difficulty (0-1)
            source_type: Where query came from
            source_id: Source reference

        Returns:
            Query ID if added, None if duplicate
        """
        pool = await self._get_pool()
        query_hash = self._hash_query(input_prompt)

        try:
            result = await pool.fetchval(
                """
                INSERT INTO held_out_queries
                (query_hash, input_prompt, expected_output, context,
                 domain, category, difficulty, source_type, source_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (query_hash) DO NOTHING
                RETURNING id
                """,
                query_hash, input_prompt, expected_output, context,
                domain, category, difficulty, source_type, source_id
            )
            if result:
                logger.debug(f"Added held-out query {result}: {input_prompt[:50]}...")
            return result
        except Exception as e:
            logger.warning(f"Failed to add held-out query: {e}")
            return None

    async def get_sample(
        self,
        size: int = DAILY_SAMPLE_SIZE,
        domain: Optional[str] = None,
        category: Optional[str] = None,
    ) -> list[HeldOutQuery]:
        """Get a random sample of held-out queries.

        Prioritizes queries that haven't been used recently.

        Args:
            size: Number of queries to sample
            domain: Optional domain filter
            category: Optional category filter

        Returns:
            List of HeldOutQuery objects
        """
        pool = await self._get_pool()

        # Build query with filters
        conditions = ["excluded_from_training = TRUE"]
        params = [size]
        param_idx = 2

        if domain:
            conditions.append(f"domain = ${param_idx}")
            params.append(domain)
            param_idx += 1

        if category:
            conditions.append(f"category = ${param_idx}")
            params.append(category)
            param_idx += 1

        where_clause = " AND ".join(conditions)

        rows = await pool.fetch(
            f"""
            SELECT id, input_prompt, expected_output, context,
                   domain, category, difficulty, source_type, created_at
            FROM held_out_queries
            WHERE {where_clause}
            ORDER BY last_used_at NULLS FIRST, RANDOM()
            LIMIT $1
            """,
            *params
        )

        queries = [
            HeldOutQuery(
                id=row["id"],
                input_prompt=row["input_prompt"],
                expected_output=row["expected_output"],
                context=row["context"],
                domain=row["domain"] or "",
                category=row["category"] or "",
                difficulty=row["difficulty"] or 0.5,
                source_type=row["source_type"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

        # Mark as used
        if queries:
            ids = [q.id for q in queries]
            await pool.execute(
                """
                UPDATE held_out_queries
                SET last_used_at = NOW(), use_count = use_count + 1
                WHERE id = ANY($1)
                """,
                ids
            )

        return queries

    async def cleanup_old_queries(self) -> int:
        """Remove queries older than window.

        Returns:
            Number of queries removed
        """
        pool = await self._get_pool()
        cutoff = datetime.now() - timedelta(days=self.WINDOW_DAYS)

        # Keep minimum queries even if old
        count = await pool.fetchval(
            "SELECT COUNT(*) FROM held_out_queries"
        )

        if count <= self.MIN_QUERIES:
            return 0

        result = await pool.execute(
            """
            DELETE FROM held_out_queries
            WHERE created_at < $1
            AND id NOT IN (
                SELECT id FROM held_out_queries
                ORDER BY created_at DESC
                LIMIT $2
            )
            """,
            cutoff, self.MIN_QUERIES
        )

        deleted = int(result.split()[-1]) if result else 0
        logger.info(f"Cleaned up {deleted} old held-out queries")
        return deleted

    async def get_stats(self) -> dict:
        """Get held-out pool statistics."""
        pool = await self._get_pool()

        stats = await pool.fetchrow(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE last_used_at IS NULL) as never_used,
                COUNT(DISTINCT domain) as domains,
                COUNT(DISTINCT category) as categories,
                AVG(difficulty) as avg_difficulty,
                MIN(created_at) as oldest,
                MAX(created_at) as newest
            FROM held_out_queries
            WHERE excluded_from_training = TRUE
            """
        )

        return {
            "total_queries": stats["total"],
            "never_used": stats["never_used"],
            "domains": stats["domains"],
            "categories": stats["categories"],
            "avg_difficulty": round(stats["avg_difficulty"] or 0, 2),
            "oldest": stats["oldest"].isoformat() if stats["oldest"] else None,
            "newest": stats["newest"].isoformat() if stats["newest"] else None,
        }


class DailyEvaluator:
    """Runs comprehensive daily evaluation against held-out set.

    This provides an objective measure of agent performance that's
    independent of the training process.
    """

    def __init__(
        self,
        held_out_manager: Optional[HeldOutManager] = None,
        db_url: Optional[str] = None,
    ):
        """Initialize daily evaluator.

        Args:
            held_out_manager: HeldOutManager instance
            db_url: PostgreSQL connection URL
        """
        self.held_out = held_out_manager or HeldOutManager(db_url)
        self.db_url = db_url
        self._pool = None

    async def _get_pool(self):
        """Get or create connection pool."""
        if self._pool is None:
            import asyncpg
            import os

            url = self.db_url or os.getenv(
                "DATABASE_URL",
                "postgresql://gaius:gaius@localhost:5432/gaius"
            )
            self._pool = await asyncpg.create_pool(url)
        return self._pool

    async def run_daily_evaluation(
        self,
        agents: Optional[list[str]] = None,
        sample_size: int = 50,
        xai_spot_checks: int = 5,
    ) -> DailyEvalSummary:
        """Run comprehensive daily evaluation with tiered strategy.

        Uses local model for all queries, XAI only for spot checks
        to conserve API credits while maintaining evaluation quality.

        Args:
            agents: Agents to evaluate (None = all active)
            sample_size: Number of held-out queries to use
            xai_spot_checks: How many to verify with XAI (budget-aware)

        Returns:
            DailyEvalSummary with results
        """
        from .daemon import get_evolution_daemon
        from ...models.tiered_evaluation import get_tiered_evaluator

        pool = await self._get_pool()
        eval_date = date.today()

        # Get tiered evaluator (local + XAI with budget)
        evaluator = get_tiered_evaluator()

        # Get agents to evaluate
        if agents is None:
            daemon = get_evolution_daemon()
            agents = daemon.config.agents

        # Get held-out sample
        queries = await self.held_out.get_sample(size=sample_size)
        if not queries:
            logger.warning("No held-out queries available for evaluation")
            return DailyEvalSummary(
                eval_date=eval_date,
                total_cycles=0,
                successful_cycles=0,
                total_improvement_percent=0.0,
                agent_summaries={},
                held_out_results={"error": "no_queries"},
                trend_direction="unknown",
                trend_confidence=0.0,
            )

        # Get active versions for each agent
        agent_versions = {}
        for agent_id in agents:
            row = await pool.fetchrow(
                """
                SELECT version_id, config
                FROM agent_versions
                WHERE agent_id = $1 AND is_active = TRUE
                """,
                agent_id
            )
            if row:
                agent_versions[agent_id] = row["version_id"]

        # Evaluate each agent on held-out set
        agent_summaries = {}
        all_scores = []
        xai_comparisons = []

        for agent_id, version_id in agent_versions.items():
            scores = []
            category_scores = {}

            # Prepare batch for tiered evaluation
            eval_batch = []
            for query in queries:
                try:
                    # Generate agent output
                    output = await self._generate_agent_output(
                        agent_id, version_id, query
                    )
                    eval_batch.append({
                        "agent_output": output,
                        "task_prompt": query.input_prompt,
                        "context": query.context or "",
                        "query": query,
                    })
                except Exception as e:
                    logger.warning(f"Output generation failed for {agent_id}: {e}")

            # Run tiered evaluation with spot checks
            if eval_batch:
                results = await evaluator.spot_check_batch(
                    [{"agent_output": e["agent_output"],
                      "task_prompt": e["task_prompt"],
                      "context": e["context"]}
                     for e in eval_batch],
                    sample_size=xai_spot_checks,
                )

                for i, (local_result, xai_result) in enumerate(results):
                    query = eval_batch[i]["query"]
                    output = eval_batch[i]["agent_output"]

                    # Use XAI score if available, else local
                    if xai_result:
                        score = xai_result.overall_score
                        eval_result = xai_result.to_dict()
                        xai_comparisons.append({
                            "local": local_result.overall_score,
                            "xai": xai_result.overall_score,
                            "diff": abs(local_result.overall_score - xai_result.overall_score),
                        })
                    else:
                        score = local_result.overall_score
                        eval_result = local_result.to_dict()

                    scores.append(score)
                    all_scores.append(score)

                    # Track by category
                    cat = query.category or "unknown"
                    if cat not in category_scores:
                        category_scores[cat] = []
                    category_scores[cat].append(score)

                    # Store evaluation
                    await self._store_evaluation(
                        version_id=version_id,
                        query=query,
                        output=output,
                        eval_result=eval_result,
                        eval_type="held_out",
                    )

            # Compute agent summary
            if scores:
                agent_summaries[agent_id] = {
                    "version_id": version_id,
                    "queries_evaluated": len(scores),
                    "avg_score": round(sum(scores) / len(scores), 3),
                    "min_score": round(min(scores), 3),
                    "max_score": round(max(scores), 3),
                    "by_category": {
                        cat: round(sum(s) / len(s), 3)
                        for cat, s in category_scores.items()
                    }
                }

        # Get cycle stats for today
        cycle_stats = await pool.fetchrow(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE success) as successful,
                COALESCE(SUM(improvement_percent) FILTER (WHERE success), 0) as total_improvement
            FROM evolution_cycles
            WHERE DATE(started_at) = $1
            """,
            eval_date
        )

        # Compute trend
        trend_direction, trend_confidence = await self._compute_trend(pool, eval_date)

        # Build held-out results summary
        held_out_results = {
            "queries_used": len(queries),
            "agents_evaluated": len(agent_versions),
            "avg_score": round(sum(all_scores) / len(all_scores), 3) if all_scores else 0.0,
        }

        summary = DailyEvalSummary(
            eval_date=eval_date,
            total_cycles=cycle_stats["total"] if cycle_stats else 0,
            successful_cycles=cycle_stats["successful"] if cycle_stats else 0,
            total_improvement_percent=float(cycle_stats["total_improvement"]) if cycle_stats else 0.0,
            agent_summaries=agent_summaries,
            held_out_results=held_out_results,
            trend_direction=trend_direction,
            trend_confidence=trend_confidence,
        )

        # Store summary
        await self._store_daily_summary(summary)

        return summary

    async def _generate_agent_output(
        self,
        agent_id: str,
        version_id: str,
        query: HeldOutQuery,
    ) -> str:
        """Generate output from agent for evaluation."""
        # Use the agent's active configuration
        pool = await self._get_pool()

        config = await pool.fetchval(
            "SELECT config FROM agent_versions WHERE version_id = $1",
            version_id
        )

        if not config:
            return ""

        # Call inference
        try:
            from ..inference.scheduler import get_scheduler_service

            scheduler = get_scheduler_service()
            result = await scheduler.submit_job(
                prompt=query.input_prompt,
                system_prompt=config.get("system_prompt", ""),
                model=config.get("model", ""),
                max_tokens=config.get("max_tokens", 1024),
                priority="low",  # Don't preempt interactive work
            )
            return result.get("output", "")

        except Exception as e:
            logger.warning(f"Inference failed: {e}")
            return ""

    async def _store_evaluation(
        self,
        version_id: str,
        query: HeldOutQuery,
        output: str,
        eval_result: dict,
        eval_type: str,
    ) -> None:
        """Store evaluation result in database."""
        pool = await self._get_pool()

        await pool.execute(
            """
            INSERT INTO agent_evaluations
            (version_id, overall_score, dimension_scores, summary,
             task_prompt, agent_output, context, eval_type,
             task_category, task_difficulty, evaluator_model)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
            version_id,
            eval_result.get("overall_score", 0.0),
            json.dumps(eval_result.get("dimension_scores", {})),
            eval_result.get("summary", ""),
            query.input_prompt,
            output,
            query.context,
            eval_type,
            query.category,
            query.difficulty,
            eval_result.get("evaluator_model", "xai/grok-3"),
        )

    async def _compute_trend(
        self,
        pool,
        current_date: date,
    ) -> tuple[str, float]:
        """Compute performance trend over recent days.

        Returns:
            (direction, confidence) tuple
        """
        # Get last 7 days of held-out scores
        rows = await pool.fetch(
            """
            SELECT DATE(created_at) as eval_date, AVG(overall_score) as avg_score
            FROM agent_evaluations
            WHERE eval_type = 'held_out'
            AND created_at > $1
            GROUP BY DATE(created_at)
            ORDER BY eval_date
            """,
            current_date - timedelta(days=7)
        )

        if len(rows) < 2:
            return "unknown", 0.0

        scores = [float(r["avg_score"]) for r in rows]

        # Simple linear trend
        n = len(scores)
        x_mean = (n - 1) / 2
        y_mean = sum(scores) / n

        numerator = sum((i - x_mean) * (s - y_mean) for i, s in enumerate(scores))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return "stable", 0.5

        slope = numerator / denominator

        # Determine direction
        if slope > 0.01:
            direction = "improving"
        elif slope < -0.01:
            direction = "declining"
        else:
            direction = "stable"

        # Confidence based on consistency
        variance = sum((s - y_mean) ** 2 for s in scores) / n
        confidence = max(0.0, min(1.0, 1.0 - variance))

        return direction, round(confidence, 2)

    async def _store_daily_summary(self, summary: DailyEvalSummary) -> None:
        """Store daily summary in database."""
        pool = await self._get_pool()

        await pool.execute(
            """
            INSERT INTO daily_eval_summaries
            (eval_date, total_cycles, successful_cycles, total_improvement_percent,
             agent_summaries, held_out_results, trend_direction, trend_confidence, notes)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (eval_date) DO UPDATE SET
                total_cycles = EXCLUDED.total_cycles,
                successful_cycles = EXCLUDED.successful_cycles,
                total_improvement_percent = EXCLUDED.total_improvement_percent,
                agent_summaries = EXCLUDED.agent_summaries,
                held_out_results = EXCLUDED.held_out_results,
                trend_direction = EXCLUDED.trend_direction,
                trend_confidence = EXCLUDED.trend_confidence,
                notes = EXCLUDED.notes
            """,
            summary.eval_date,
            summary.total_cycles,
            summary.successful_cycles,
            summary.total_improvement_percent,
            json.dumps(summary.agent_summaries),
            json.dumps(summary.held_out_results),
            summary.trend_direction,
            summary.trend_confidence,
            summary.notes,
        )


class ReportGenerator:
    """Generates markdown reports from evaluation data."""

    def __init__(self, output_dir: Optional[Path] = None):
        """Initialize report generator.

        Args:
            output_dir: Directory for reports (default: docs/scratch/{date})
        """
        self.output_dir = output_dir

    def _get_output_dir(self, eval_date: date) -> Path:
        """Get output directory for a given date."""
        if self.output_dir:
            return self.output_dir

        base = Path("docs/scratch")
        date_dir = base / eval_date.isoformat()
        date_dir.mkdir(parents=True, exist_ok=True)
        return date_dir

    def _get_next_filename(self, output_dir: Path) -> Path:
        """Get next numbered filename in directory."""
        existing = list(output_dir.glob("*.md"))
        numbers = []
        for f in existing:
            try:
                num = int(f.name.split("_")[0])
                numbers.append(num)
            except (ValueError, IndexError):
                pass

        next_num = max(numbers, default=0) + 1
        return output_dir / f"{next_num:02d}_evolution_report.md"

    def generate_daily_report(self, summary: DailyEvalSummary) -> Path:
        """Generate markdown report for daily evaluation.

        Args:
            summary: DailyEvalSummary to report

        Returns:
            Path to generated report
        """
        output_dir = self._get_output_dir(summary.eval_date)
        output_path = self._get_next_filename(output_dir)

        lines = [
            f"# Evolution Report: {summary.eval_date.isoformat()}",
            "",
            "## Summary",
            "",
            f"- **Evolution Cycles**: {summary.successful_cycles}/{summary.total_cycles} successful",
            f"- **Total Improvement**: {summary.total_improvement_percent:.1f}%",
            f"- **Trend**: {summary.trend_direction} (confidence: {summary.trend_confidence:.0%})",
            "",
            "## Held-Out Evaluation",
            "",
        ]

        hor = summary.held_out_results
        if "error" not in hor:
            lines.extend([
                f"- Queries evaluated: {hor.get('queries_used', 0)}",
                f"- Agents evaluated: {hor.get('agents_evaluated', 0)}",
                f"- Average score: {hor.get('avg_score', 0):.3f}",
                "",
            ])

        lines.extend([
            "## Agent Performance",
            "",
        ])

        for agent_id, stats in summary.agent_summaries.items():
            lines.extend([
                f"### {agent_id}",
                "",
                f"- Version: `{stats.get('version_id', 'unknown')[:8]}...`",
                f"- Queries: {stats.get('queries_evaluated', 0)}",
                f"- Score: {stats.get('avg_score', 0):.3f} (min: {stats.get('min_score', 0):.3f}, max: {stats.get('max_score', 0):.3f})",
                "",
            ])

            by_cat = stats.get("by_category", {})
            if by_cat:
                lines.append("| Category | Score |")
                lines.append("|----------|-------|")
                for cat, score in sorted(by_cat.items()):
                    lines.append(f"| {cat} | {score:.3f} |")
                lines.append("")

        # Trend indicator
        trend_emoji = {
            "improving": "📈",
            "stable": "➡️",
            "declining": "📉",
            "unknown": "❓",
        }

        lines.extend([
            "## Trend Analysis",
            "",
            f"{trend_emoji.get(summary.trend_direction, '❓')} **{summary.trend_direction.title()}**",
            "",
            f"Based on 7-day held-out score trajectory with {summary.trend_confidence:.0%} confidence.",
            "",
        ])

        if summary.notes:
            lines.extend([
                "## Notes",
                "",
                summary.notes,
                "",
            ])

        content = "\n".join(lines)
        output_path.write_text(content)

        logger.info(f"Generated evolution report: {output_path}")
        return output_path


# Module-level singletons
_held_out_manager: Optional[HeldOutManager] = None
_daily_evaluator: Optional[DailyEvaluator] = None
_report_generator: Optional[ReportGenerator] = None


def get_held_out_manager() -> HeldOutManager:
    """Get or create held-out manager singleton."""
    global _held_out_manager
    if _held_out_manager is None:
        _held_out_manager = HeldOutManager()
    return _held_out_manager


def get_daily_evaluator() -> DailyEvaluator:
    """Get or create daily evaluator singleton."""
    global _daily_evaluator
    if _daily_evaluator is None:
        _daily_evaluator = DailyEvaluator()
    return _daily_evaluator


def get_report_generator() -> ReportGenerator:
    """Get or create report generator singleton."""
    global _report_generator
    if _report_generator is None:
        _report_generator = ReportGenerator()
    return _report_generator
