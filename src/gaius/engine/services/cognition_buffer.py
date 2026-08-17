"""Universal agent context, continuously optimized for one next question.

The generative space of questions is open. Answers here inform
*decisions*, which is the constraint that makes "infinite" tractable:
given where the user is and what they are doing, keep what could
change the next move — not unbounded rumination.

Continuous compaction is not session management. It does not make
room for a conversation or a coding session. It holds a slot for
**one next question** that can arrive at any hour. Day or night is
the same readiness problem.

Two layers, one object:

* **Scratchpad** — always-on merge (any stream) of full content.
  Instantaneous decisions start here, not from a from-zero search.
* **Attention schema** — layered on that scratchpad. Vocabulary from
  ``sdg-corpora``; membrane from ``sdg-strategy``. Schema *form* will
  be refined. What it *does* (steer compaction) and *where it lives*
  (on this buffer) are the fixed claims.

Harvest admission is the **threshold** regime. Scratchpad compaction
is the **budget** regime. Do not confuse the two.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from gaius.engine.services.sdg_aperture import SdgAperture
from gaius.engine.services.sdg_catalog import SdgCatalog

THINKING_CONTEXT_TOKENS = 262_144
# Held empty for one inbound question — not a conversation, not a session.
NEXT_QUESTION_RESERVE_TOKENS = 65_536
DEFAULT_SCRATCH_TOKEN_BUDGET = (
    THINKING_CONTEXT_TOKENS - NEXT_QUESTION_RESERVE_TOKENS
)
CHARS_PER_TOKEN = 4

Stream = Literal["ambient", "prospects"]


@dataclass(frozen=True)
class DecisionSituation:
    """Where the user is and what they are doing.

    Constrains the next-question space to questions whose answers
    could inform a decision *here*. Vacant situation = no such
    prior (closer to true-infinite thinking; worse compaction).

    Form will be refined. The constraint is the fixed claim.
    """

    where: str = ""
    doing: str = ""
    decide: str = ""

    def tokens(self) -> tuple[str, ...]:
        raw = f"{self.where} {self.doing} {self.decide}".lower()
        return tuple(part for part in raw.split() if part)

    def vacant(self) -> bool:
        return not self.tokens()


@dataclass
class ScratchEntry:
    """One merged item: full content plus optional schema annotation."""

    stream: Stream
    source_id: str
    content: str
    role: str = ""
    ts: float = field(default_factory=time.time)
    sdg_code: str = ""
    aperture: str = ""
    margin: float = 0.0
    admitted: bool = False
    suppressed: bool = False
    review: bool = False
    review_reason: str = ""

    def token_cost(self) -> int:
        body = (
            f"{self.stream} {self.source_id} {self.role} {self.sdg_code} "
            f"{self.review_reason} {self.content}"
        )
        return max(1, (len(body) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


class AttentionSchema:
    """SDG-grounded model of attention, layered on the scratchpad.

    Does not replace merge contents. Informs ``CognitionBuffer.compact``.
    """

    def __init__(self, catalog: SdgCatalog, aperture: SdgAperture) -> None:
        self.catalog = catalog
        self.aperture = aperture

    @classmethod
    def load(
        cls,
        corpora_root: Path | None = None,
        strategy_root: Path | None = None,
    ) -> AttentionSchema:
        return cls(SdgCatalog.load(corpora_root), SdgAperture.load(strategy_root))

    def resolve(self, token: str) -> str:
        """Canonical schema token: corpora code or aiming IRI."""
        if not token:
            return ""
        if token in self.catalog:
            return token
        anchor = self.aperture.resolve(token)
        if anchor is not None:
            return anchor.iri
        raise ValueError(
            f"Unknown attention token {token!r} — not in sdg-corpora "
            "vocabulary and not in sdg-strategy aiming C.\n"
            "  Guru: #SDG.00000002.UNKCODE\n"
            "  Try: git submodule update --init external/sdg-corpora "
            "external/sdg-strategy"
        )

    def keep_score(
        self,
        entry: ScratchEntry,
        situation: DecisionSituation | None = None,
    ) -> float:
        """Higher survives budget compaction. Review is last to go.

        Situated boost is a first crude prior: token overlap with
        where / doing / decide. Not a model of the decision itself.
        """
        if entry.review:
            return 1.0
        if entry.suppressed:
            base = 0.08
        elif entry.admitted and entry.sdg_code:
            base = 0.50 + min(0.40, max(0.0, entry.margin))
        elif entry.admitted:
            base = 0.30 + min(0.20, max(0.0, entry.margin))
        else:
            base = 0.05
        if situation is None or situation.vacant():
            return base
        hay = f"{entry.content} {entry.sdg_code} {entry.role} {entry.source_id}".lower()
        if any(tok in hay for tok in situation.tokens()):
            return min(0.99, base + 0.25)
        return base


class CognitionBuffer:
    """Always-on scratchpad. Compaction keeps a slot for one next question."""

    def __init__(
        self,
        schema: AttentionSchema,
        token_budget: int = DEFAULT_SCRATCH_TOKEN_BUDGET,
    ) -> None:
        ceiling = THINKING_CONTEXT_TOKENS - NEXT_QUESTION_RESERVE_TOKENS
        if token_budget <= 0 or token_budget > ceiling:
            raise ValueError(
                f"token_budget must be in (0, {ceiling}] so "
                f"{NEXT_QUESTION_RESERVE_TOKENS} tokens stay free for "
                "one next question (not a conversation or session)"
            )
        self.schema = schema
        self.token_budget = token_budget
        self.situation = DecisionSituation()
        self._entries: list[ScratchEntry] = []
        self._tokens = 0

    def situate(self, situation: DecisionSituation) -> None:
        """Stamp where / doing / decide and re-compact under that prior."""
        self.situation = situation
        self.compact()

    def merge(
        self,
        stream: Stream,
        source_id: str,
        content: str,
        *,
        role: str = "",
        ts: float | None = None,
        code: str = "",
        aperture: str = "",
        margin: float = 0.0,
        admitted: bool = False,
        suppressed: bool = False,
        review: bool = False,
        review_reason: str = "",
    ) -> ScratchEntry:
        """Append full content. Optional schema fields apply before compact."""
        entry = ScratchEntry(
            stream=stream,
            source_id=source_id,
            content=content,
            role=role,
            ts=time.time() if ts is None else ts,
            sdg_code=self.schema.resolve(code) if code else "",
            aperture=aperture or (self.schema.aperture.collection if code else ""),
            margin=margin,
            admitted=admitted,
            suppressed=suppressed,
            review=review,
            review_reason=review_reason,
        )
        self._entries.append(entry)
        self._tokens += entry.token_cost()
        self.compact()
        return entry

    def record_attention(
        self,
        source_id: str,
        *,
        code: str = "",
        aperture: str = "",
        margin: float = 0.0,
        admitted: bool = False,
        suppressed: bool = False,
        review: bool = False,
        review_reason: str = "",
    ) -> ScratchEntry:
        """Layer schema annotation onto an existing merge entry."""
        entry = self._by_id(source_id)
        if entry is None:
            raise KeyError(
                f"No scratchpad entry {source_id!r} — merge first, then "
                "annotate.\n"
                "  Guru: #SDG.00000005.NOENTRY"
            )
        before = entry.token_cost()
        entry.sdg_code = self.schema.resolve(code) if code else ""
        entry.aperture = aperture or self.schema.aperture.collection
        entry.margin = margin
        entry.admitted = admitted
        entry.suppressed = suppressed
        entry.review = review
        entry.review_reason = review_reason
        self._tokens += entry.token_cost() - before
        self.compact()
        return entry

    def compact(self) -> None:
        """Evict to keep the one-next-question reserve. Not a session trim."""
        while self._tokens > self.token_budget and self._entries:
            ranked = sorted(
                range(len(self._entries)),
                key=lambda i: (
                    self.schema.keep_score(self._entries[i], self.situation),
                    self._entries[i].ts,
                ),
            )
            dead = self._entries.pop(ranked[0])
            self._tokens -= dead.token_cost()
        if self._tokens < 0:
            self._tokens = 0

    def get(self, source_id: str) -> ScratchEntry | None:
        return self._by_id(source_id)

    def admitted(self) -> list[ScratchEntry]:
        return [e for e in self._entries if e.admitted and not e.suppressed]

    def review_worklist(self) -> list[ScratchEntry]:
        return [e for e in self._entries if e.review]

    def assemble(self) -> str:
        """Pre-conditioned context for one next question."""
        ap = self.schema.aperture
        sit = self.situation
        lines = [
            "# Cognition scratchpad",
            (
                f"strategy={ap.strategy_id} aperture={ap.collection} "
                f"C={ap.n} regime={ap.regime} tau={ap.tau} "
                f"tokens~{self._tokens}/{self.token_budget} "
                f"reserve={self.reserve_tokens} purpose=one-next-question"
            ),
            "",
            "## Situation",
            f"where: {sit.where or '—'}",
            f"doing: {sit.doing or '—'}",
            f"decide: {sit.decide or '—'}",
            "",
            "## Attention",
        ]
        for e in self._entries:
            flag = "HOLD"
            if e.review:
                flag = "REVIEW"
            elif e.suppressed:
                flag = "SUPPRESS"
            elif e.admitted:
                flag = "ADMIT"
            code = e.sdg_code or "—"
            lines.append(
                f"- {flag} {e.stream} {code} margin={e.margin:.3f} "
                f"{e.aperture or ap.collection} {e.source_id}"
            )
            if e.review_reason:
                lines.append(f"  review: {e.review_reason}")
        lines.append("")
        lines.append("## Scratchpad")
        for e in self._entries:
            heading = e.role or e.stream
            lines.append(f"### [{heading} {e.source_id}]")
            lines.append(e.content)
            lines.append("")
        return "\n".join(lines)

    def _by_id(self, source_id: str) -> ScratchEntry | None:
        for e in self._entries:
            if e.source_id == source_id:
                return e
        return None

    @property
    def tokens(self) -> int:
        return self._tokens

    @property
    def reserve_tokens(self) -> int:
        return THINKING_CONTEXT_TOKENS - self.token_budget

    def __len__(self) -> int:
        return len(self._entries)
