"""ThetaCycleFlow — encode thoughts, CLT incidence, BERTSubs Intra on the TBox.

Airflow DAG ``gaius_theta_cycle`` (Monday 06:00). The engine owns the queue
and EmbedTexts; this child never constructs ThetaService. The TBox is the
HermiT-certified SDG OWL. SKOS names it. CLT links the corpus.

    uv run python -m gaius.flows.theta.cycle run
"""

from __future__ import annotations

import asyncio
import os

import numpy as np
from metaflow import Parameter, current, step

from gaius.flows import register_flow
from gaius.flows.base import GaiusFlow
from gaius.hx.lineage.events import Dataset


@register_flow("theta-cycle")
class ThetaCycleFlow(GaiusFlow):
    """Consolidation vessel. Heavy stages run in this process under YuniKorn."""

    gpu_tokens = 0
    scheduled_task_id = Parameter("scheduled-task-id", default=0, type=int)
    slice_id = Parameter("slice-id", default="", type=str)

    @step
    def start(self):
        from gaius.agents.theta.consolidation import get_previous_week_slice_id
        from gaius.flows.config import apply_metaflow_config
        from gaius.flows.lattice import require_signals_metaflow
        from gaius.storage.database import get_database_url

        apply_metaflow_config()
        require_signals_metaflow()
        self.dsn = os.environ.get("DATABASE_URL") or get_database_url()
        self.week = str(self.slice_id or get_previous_week_slice_id())
        self.run_id = str(getattr(current, "run_id", None) or "")
        print(
            f"theta.cycle.start week={self.week} kb_root={self.kb_root} "
            f"run_id={self.run_id} task={self.scheduled_task_id}"
        )
        self.emit_lineage_start(
            job_name="theta_cycle",
            inputs=[Dataset.from_source("postgres", "cognition_thoughts")],
        )
        self.next(self.prepare)

    @step
    def prepare(self):
        """Supersede stale queue rows; start the current ISO-week job."""
        from gaius.engine.services.theta_cycle import (
            NOTHOUGHTS,
            load_thoughts,
            start_current_job,
        )

        async def _go():
            import asyncpg

            pool = await asyncpg.create_pool(self.dsn)
            try:
                async with pool.acquire() as conn:
                    job_id, superseded = await start_current_job(conn, self.week)
                    thoughts = await load_thoughts(conn, self.week)
                    return job_id, superseded, thoughts
            finally:
                await pool.close()

        job_id, superseded, thoughts = asyncio.run(_go())
        self.job_id = job_id
        self.superseded = superseded
        self.thoughts = thoughts
        self.stage = "prepare"
        print(
            f"theta.cycle.prepare job={job_id} superseded={superseded} "
            f"thoughts={len(thoughts)}"
        )
        if not thoughts:
            self.result = {
                "success": False,
                "slice_id": self.week,
                "error": f"{NOTHOUGHTS} no cognition_thoughts in {self.week}",
                "guru_code": NOTHOUGHTS,
                "stage": "encode",
            }
        self.next(self.encode)

    @step
    def encode(self):
        """Centroid via the engine EmbedTexts RPC — not a local model."""
        from gaius.engine.services.theta_cycle import NOENCODE, embed_texts

        if self.thoughts and not (getattr(self, "result", None) or {}).get("guru_code"):
            texts = [
                f"{t.get('title') or ''}\n{t.get('content') or ''}".strip()
                for t in self.thoughts
            ]
            texts = [t for t in texts if t]
            try:
                vecs = embed_texts(texts)
                if not vecs:
                    raise RuntimeError("empty EmbedTexts response")
                self.centroid = np.mean(np.asarray(vecs, dtype=float), axis=0)
                self.stage = "encode"
                print(f"theta.cycle.encode n={len(vecs)} dim={self.centroid.shape}")
            except Exception as e:
                self.result = {
                    "success": False,
                    "slice_id": self.week,
                    "error": f"{NOENCODE} {e}",
                    "guru_code": NOENCODE,
                    "stage": "encode",
                }
        self.next(self.infer)

    @step
    def infer(self):
        """NVAR + BERTSubs + KG + augmentation in this process (not the engine)."""
        from gaius.agents.theta.agent import ThetaAgent

        if getattr(self, "centroid", None) is not None:
            try:
                from gaius.agents.theta.clt_incidence import load_owl_pairs_for_slice

                owl_pairs = asyncio.run(
                    load_owl_pairs_for_slice(self.dsn, self.week)
                )
                print(f"theta.cycle.infer clt_pairs={len(owl_pairs)}")
                agent = ThetaAgent(kb_root=self.kb_root)
                result = asyncio.run(
                    agent.run_consolidation(
                        temporal_slice=self.week,
                        centroid=self.centroid,
                        documents=self.thoughts,
                        owl_pairs=owl_pairs,
                    )
                )
                err = result.error
            except Exception as e:
                err = str(e)
                result = None
            guru = ""
            if err:
                if "THINCABI" in err:
                    guru = "#THETA.00000012.THINCABI"
                elif "ONTOLOGY_INVALID" in err:
                    guru = "#THETA.00000005.ONTOLOGY_INVALID"
                elif "DEEPONTO" in err:
                    guru = "#THETA.00000001.DEEPONTO"
                elif err.startswith("#THETA"):
                    guru = err.split()[0]
            if result is None:
                self.stage = guru or "infer"
                self.result = {
                    "success": False,
                    "slice_id": self.week,
                    "error": err,
                    "guru_code": guru,
                    "stage": self.stage,
                }
            else:
                self.stage = "augment" if result.error is None else (guru or "infer")
                self.result = {
                    "success": result.error is None,
                    "slice_id": result.slice_id,
                    "signal": result.signal.to_dict() if result.signal else None,
                    "candidates_evaluated": result.candidates_evaluated,
                    "candidates_selected": result.candidates_selected,
                    "documents_augmented": result.documents_augmented,
                    "effectiveness": result.effectiveness,
                    "error": result.error,
                    "guru_code": guru,
                    "stage": self.stage,
                }
            print(
                f"theta.cycle.infer success={self.result['success']} "
                f"eval={self.result.get('candidates_evaluated')} "
                f"aug={self.result.get('documents_augmented')}"
            )
        self.next(self.complete)

    @step
    def complete(self):
        """Write the queue row: stage reached, never a silent miss."""
        from gaius.engine.services.theta_cycle import complete_job

        result = getattr(self, "result", {}) or {}
        job_id = getattr(self, "job_id", None)
        if job_id:
            asyncio.run(complete_job(self.dsn, int(job_id), result))
        print(f"theta.cycle.complete job={job_id} stage={result.get('stage')}")
        self.emit_lineage_complete(
            outputs=[Dataset.from_source("postgres", "theta_consolidation_runs")]
        )
        self.next(self.end)

    @step
    def end(self):
        result = getattr(self, "result", {}) or {}
        print(f"theta.cycle.end job={getattr(self, 'job_id', None)}")
        if not result.get("success"):
            raise RuntimeError(
                result.get("error")
                or result.get("guru_code")
                or "#THETA.00000013.CONSFAIL"
            )


if __name__ == "__main__":
    from gaius.flows.config import apply_metaflow_config

    apply_metaflow_config()
    ThetaCycleFlow()
