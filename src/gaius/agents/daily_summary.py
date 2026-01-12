"""Daily Summary Agent for Gaius.

Generates end-of-day or morning summaries that synthesize:
- Activity from the day
- New KB entries
- Key insights and patterns
- Recommendations for next focus

Can be run manually or scheduled via pg_cron.

Usage:
    from gaius.agents.daily_summary import DailySummaryAgent, generate_daily_summary

    agent = DailySummaryAgent()
    summary = await agent.generate()
    print(summary.to_markdown())
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from ..core.config import get_config


@dataclass
class DailySummaryNote:
    """A daily summary note in Zettelkasten format."""

    summary_date: date
    profile: str

    # Content sections
    overview: str = ""
    activity_summary: str = ""
    key_entries: list[str] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    tomorrow_focus: str = ""

    # Metadata
    total_entries: int = 0
    total_queries: int = 0
    total_swarm_runs: int = 0
    total_tokens: int = 0
    domains_active: list[str] = field(default_factory=list)

    # Generation info
    generated_at: datetime = field(default_factory=datetime.now)
    generator_model: str = ""

    def to_markdown(self) -> str:
        """Format as Zettelkasten markdown note."""
        lines = [
            f"# Daily Summary: {self.summary_date}",
            "",
            "---",
            f"date: {self.summary_date}",
            f"profile: {self.profile}",
            f"type: daily-summary",
            f"generated: {self.generated_at.isoformat()}",
            "---",
            "",
        ]

        # Overview
        if self.overview:
            lines.append("## Overview")
            lines.append(self.overview)
            lines.append("")

        # Activity
        lines.append("## Activity Metrics")
        lines.append(f"- **Queries:** {self.total_queries}")
        lines.append(f"- **Swarm runs:** {self.total_swarm_runs}")
        lines.append(f"- **KB entries:** {self.total_entries}")
        lines.append(f"- **Tokens used:** {self.total_tokens:,}")

        if self.domains_active:
            lines.append(f"- **Domains:** {', '.join(self.domains_active)}")

        lines.append("")

        # Key entries
        if self.key_entries:
            lines.append("## Key Entries")
            for entry in self.key_entries:
                lines.append(f"- {entry}")
            lines.append("")

        # Insights
        if self.insights:
            lines.append("## Insights")
            for insight in self.insights:
                lines.append(f"- {insight}")
            lines.append("")

        # Tomorrow focus
        if self.tomorrow_focus:
            lines.append("## Tomorrow's Focus")
            lines.append(self.tomorrow_focus)
            lines.append("")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "summary_date": self.summary_date.isoformat(),
            "profile": self.profile,
            "overview": self.overview,
            "activity_summary": self.activity_summary,
            "key_entries": self.key_entries,
            "insights": self.insights,
            "tomorrow_focus": self.tomorrow_focus,
            "metrics": {
                "total_entries": self.total_entries,
                "total_queries": self.total_queries,
                "total_swarm_runs": self.total_swarm_runs,
                "total_tokens": self.total_tokens,
                "domains_active": self.domains_active,
            },
            "generated_at": self.generated_at.isoformat(),
            "generator_model": self.generator_model,
        }


class DailySummaryAgent:
    """Agent that generates daily summaries.

    Combines activity data, KB entries, and LLM synthesis
    to produce end-of-day summaries.
    """

    def __init__(self, profile: str = "default"):
        """Initialize daily summary agent.

        Args:
            profile: Profile name for context
        """
        self.profile = profile
        self.config = get_config()

    async def generate(
        self,
        target_date: date | None = None,
        use_llm: bool = True,
    ) -> DailySummaryNote:
        """Generate daily summary.

        Args:
            target_date: Date to summarize (default: today)
            use_llm: If True, use LLM for synthesis

        Returns:
            DailySummaryNote with summary
        """
        if target_date is None:
            target_date = date.today()

        note = DailySummaryNote(
            summary_date=target_date,
            profile=self.profile,
        )

        # Get activity summary
        try:
            from ..core.activity import get_activity_tracker

            tracker = get_activity_tracker()

            if target_date == date.today():
                activity = await tracker.get_today()
            else:
                # Get specific date (would need a new method)
                activity = await tracker.get_today()

            note.total_queries = activity.queries
            note.total_swarm_runs = activity.swarm_runs
            note.total_tokens = activity.total_tokens
            note.domains_active = activity.domains_active
            note.activity_summary = activity.to_markdown()

        except Exception:
            pass

        # Get KB entries from the day
        key_entries = await self._get_day_entries(target_date)
        note.key_entries = [e["title"] for e in key_entries[:10]]
        note.total_entries = len(key_entries)

        # Generate LLM synthesis
        if use_llm and (note.key_entries or note.total_queries > 0):
            try:
                synthesis = await self._synthesize(note, key_entries)
                note.overview = synthesis.get("overview", "")
                note.insights = synthesis.get("insights", [])
                note.tomorrow_focus = synthesis.get("tomorrow_focus", "")
                note.generator_model = synthesis.get("model", "")
            except Exception:
                # Fallback to simple summary
                note.overview = self._generate_simple_overview(note)

        else:
            note.overview = self._generate_simple_overview(note)

        note.generated_at = datetime.now()

        # Save to database
        await self._save_summary(note)

        return note

    async def _get_day_entries(self, target_date: date) -> list[dict]:
        """Get KB entries created on target date."""
        entries = []
        kb_path = self.config.kb.current_path

        if not kb_path.exists():
            return entries

        # Date range for the target day
        start = datetime.combine(target_date, datetime.min.time())
        end = datetime.combine(target_date + timedelta(days=1), datetime.min.time())

        try:
            for md_file in kb_path.rglob("*.md"):
                stat = md_file.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime)

                if start <= mtime < end:
                    title = md_file.stem.replace("-", " ").replace("_", " ").title()

                    # Try to read first line as title
                    try:
                        content = md_file.read_text()
                        first_line = content.split("\n")[0].strip()
                        if first_line.startswith("#"):
                            title = first_line.lstrip("#").strip()

                        entries.append({
                            "title": title,
                            "path": str(md_file),
                            "mtime": mtime,
                            "preview": content[:200] if content else "",
                        })
                    except Exception:
                        entries.append({
                            "title": title,
                            "path": str(md_file),
                            "mtime": mtime,
                            "preview": "",
                        })

            entries.sort(key=lambda e: e["mtime"], reverse=True)

        except Exception:
            pass

        return entries

    async def _synthesize(
        self,
        note: DailySummaryNote,
        entries: list[dict],
    ) -> dict[str, Any]:
        """Use LLM to synthesize daily summary."""
        from gaius.client import get_grpc_client

        client = await get_grpc_client()

        # Build context
        entry_list = "\n".join(
            f"- {e['title']}: {e['preview'][:100]}..." if e.get('preview') else f"- {e['title']}"
            for e in entries[:10]
        )

        prompt = f"""Generate a daily summary for {note.summary_date}.

Activity:
- {note.total_queries} queries
- {note.total_swarm_runs} swarm analyses
- {note.total_entries} KB entries created
- {note.total_tokens:,} tokens used
- Domains: {', '.join(note.domains_active) or 'none'}

Key entries created today:
{entry_list if entry_list else 'None'}

Provide:
1. A brief overview paragraph (2-3 sentences)
2. 2-3 key insights or patterns observed
3. A suggested focus area for tomorrow

Format as JSON with keys: overview, insights (array), tomorrow_focus"""

        result = await client.call(
            service="Scheduler",
            action="complete",
            params={
                "prompt": prompt,
                "agent": "instruct",
                "max_tokens": 500,
                "temperature": 0.6,
            },
        )

        # Parse response
        try:
            import json

            # Try to extract JSON from response
            content = result.get("content", "").strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            data = json.loads(content)
            data["model"] = result.get("model", "")
            return data

        except Exception:
            # Fallback: parse as text
            return {
                "overview": result.get("content", "")[:300],
                "insights": [],
                "tomorrow_focus": "",
                "model": result.get("model", ""),
            }

    def _generate_simple_overview(self, note: DailySummaryNote) -> str:
        """Generate simple overview without LLM."""
        parts = []

        if note.total_entries:
            parts.append(f"Created {note.total_entries} KB entries")
        if note.total_queries:
            parts.append(f"ran {note.total_queries} queries")
        if note.total_swarm_runs:
            parts.append(f"executed {note.total_swarm_runs} swarm analyses")

        if parts:
            return f"Today: {', '.join(parts)}."
        return "No significant activity recorded today."

    async def _save_summary(self, note: DailySummaryNote) -> None:
        """Save summary to database."""
        try:
            import asyncpg
            import json

            config = get_config()
            conn = await asyncpg.connect(config.database.url)

            try:
                await conn.execute(
                    """
                    INSERT INTO daily_summaries
                    (summary_date, profile_name, content, highlights, metrics, generator_model)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (summary_date) DO UPDATE SET
                        content = EXCLUDED.content,
                        highlights = EXCLUDED.highlights,
                        metrics = EXCLUDED.metrics,
                        generated_at = NOW(),
                        generator_model = EXCLUDED.generator_model
                    """,
                    note.summary_date,
                    note.profile,
                    note.to_markdown(),
                    json.dumps(note.insights),
                    json.dumps(note.to_dict()["metrics"]),
                    note.generator_model,
                )
            finally:
                await conn.close()

        except Exception:
            pass  # Silently fail - summary was still generated

    async def generate_summary(
        self,
        target_date: date | None = None,
        use_llm: bool = True,
    ) -> DailySummaryNote:
        """Alias for generate() - used by MCP server."""
        return await self.generate(target_date, use_llm)

    async def write_to_kb(self, note: DailySummaryNote) -> str | None:
        """Write summary to KB as Zettelkasten note.

        Args:
            note: Summary to write

        Returns:
            Path to written file, or None on error
        """
        config = get_config()
        scratch_path = config.kb.scratch_path

        # Create date directory
        date_dir = scratch_path / note.summary_date.isoformat()
        date_dir.mkdir(parents=True, exist_ok=True)

        # Write file
        filename = f"daily-summary-{note.summary_date}.md"
        filepath = date_dir / filename

        try:
            filepath.write_text(note.to_markdown())
            return str(filepath)
        except Exception:
            return None


# Module-level singleton
_agent: DailySummaryAgent | None = None


def get_daily_summary_agent(profile: str = "default") -> DailySummaryAgent:
    """Get or create daily summary agent singleton."""
    global _agent
    if _agent is None or _agent.profile != profile:
        _agent = DailySummaryAgent(profile=profile)
    return _agent


async def generate_daily_summary(
    target_date: date | None = None,
    profile: str = "default",
    use_llm: bool = True,
    write_to_kb: bool = False,
) -> DailySummaryNote:
    """Convenience function to generate daily summary.

    Args:
        target_date: Date to summarize (default: today)
        profile: Profile name
        use_llm: Use LLM for synthesis
        write_to_kb: Also write to KB scratch

    Returns:
        DailySummaryNote
    """
    agent = get_daily_summary_agent(profile)
    note = await agent.generate(target_date, use_llm)

    if write_to_kb:
        await agent.write_to_kb(note)

    return note
