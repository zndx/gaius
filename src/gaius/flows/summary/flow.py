"""KnowledgeSummaryFlow — parallel collection pages.

Weekly Signals Summary stays on the in-process ACP path
(``run_weekly_summary``). This flow writes:

- ``current/ontology/summary.md``
- ``current/heuristics/summary.md``
- ``current/articles/summary.md``
- ``current/projects/summary.md``
- ``current/thoughts/summary.md`` (scratch notes in the ISO week)

``start`` fans out with Metaflow foreach so the collections compose
in parallel. Each branch calls ``write_section_summary``.

Usage:
    uv run python -m gaius.flows.summary.flow run
    uv run python -m gaius.flows.summary.flow run --section thoughts
    uv run python -m gaius.flows.summary.flow run --week 2026-W34
"""

from __future__ import annotations

from metaflow import Parameter, step

from gaius.flows import register_flow
from gaius.flows.base import GaiusFlow
from gaius.hx.lineage.events import Dataset


@register_flow("knowledge-summary")
class KnowledgeSummaryFlow(GaiusFlow):
    """Write collection summary.md pages in parallel."""

    week = Parameter(
        "week",
        help="ISO week stamp YYYY-Www (empty = current)",
        default="",
    )
    section = Parameter(
        "section",
        help="ontology | heuristic | articles | projects | thoughts | empty (all)",
        default="",
    )

    @step
    def start(self):
        from gaius.engine.services.knowledge_summary import (
            COLLECTION_REL,
            COLLECTIONS,
            KnowledgeSummaryError,
            validate_section,
        )

        chosen = str(self.section or "").strip()
        if chosen:
            try:
                section = validate_section(chosen)
            except KnowledgeSummaryError as e:
                raise RuntimeError(str(e)) from e
            self.sections = [section]
        else:
            self.sections = list(COLLECTIONS)
        print(
            f"knowledge_summary.start week={self.week or '(current)'} "
            f"sections={self.sections}"
        )
        self.emit_lineage_start(
            job_name="knowledge_summary",
            inputs=[Dataset.from_kb(rel) for rel in COLLECTION_REL.values()],
        )
        self.next(self.compose, foreach="sections")

    @step
    def compose(self):
        from gaius.engine.services.knowledge_summary import (
            KnowledgeSummaryError,
            write_section_summary,
        )

        section = self.input
        try:
            written = write_section_summary(
                self.kb_root, section, week=str(self.week or "")
            )
        except KnowledgeSummaryError as e:
            raise RuntimeError(str(e)) from e
        self.written = written.as_dict()
        print(
            f"knowledge_summary.wrote section={written.section} "
            f"path={written.path} notes={written.notes}"
        )
        self.next(self.join)

    @step
    def join(self, inputs):
        self.written_all = [inp.written for inp in inputs]
        print(f"knowledge_summary.join count={len(self.written_all)}")
        self.next(self.end)

    @step
    def end(self):
        outputs = [
            Dataset.from_kb(str(item.get("path") or ""))
            for item in getattr(self, "written_all", [])
            if item.get("path")
        ]
        if outputs:
            self.emit_lineage_complete(outputs=outputs)
        for item in getattr(self, "written_all", []):
            print(
                f"knowledge_summary.complete {item.get('path')} "
                f"notes={item.get('notes')}"
            )


if __name__ == "__main__":
    from gaius.flows.config import apply_metaflow_config

    apply_metaflow_config()
    KnowledgeSummaryFlow()
