"""Aperture specification from the local ``sdg-strategy`` pin.

sdg-strategy is the content-addressed answer to *why the membrane did
that*: C, τ, encoder grain, and the aiming SKOS. Harvest admission is
the **threshold** regime in
``objective/tasks/aperture-selection-for-domain-harvesting.md``.

Gaius does not invent a second aperture. It loads this spec.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SDG_STRATEGY = _REPO_ROOT / "external" / "sdg-strategy"
_LENS = Path("components") / "lens"
_CURRENT = Path("CURRENT")
_SNAPSHOT = _LENS / "aperture.snapshot.json"
_FILTER = _LENS / "admission_filter.json"
_BINDING = _LENS / "binding.json"


def _local_name(iri: str) -> str:
    if "#" in iri:
        return iri.rsplit("#", 1)[1]
    path = urlparse(iri).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else iri


@dataclass(frozen=True)
class ApertureAnchor:
    """One aiming point in C (strategy lens snapshot)."""

    iri: str
    label: str
    vector_sha: str
    local_name: str


@dataclass(frozen=True)
class SdgAperture:
    """Effective harvest aperture: ``(C, regime, τ, e-grain)``.

    Encoder weights and the live Qdrant index are *not* in this
    checkout — identity is incomplete until those pins exist. The
    registered grain (512-token ColBERT item, ``domain_tau``) is.
    """

    strategy_id: str
    collection: str
    regime: Literal["threshold"]
    tau: float
    window_chars: int
    colbert_token_limit: int
    anchors: tuple[ApertureAnchor, ...]
    root: Path

    @classmethod
    def load(cls, root: Path | None = None) -> SdgAperture:
        checkout = Path(root) if root is not None else DEFAULT_SDG_STRATEGY
        current = checkout / _CURRENT
        snapshot = checkout / _SNAPSHOT
        filt = checkout / _FILTER
        binding = checkout / _BINDING
        missing = [p for p in (current, snapshot, filt) if not p.is_file()]
        if missing:
            shown = ", ".join(str(p.relative_to(checkout)) for p in missing)
            raise FileNotFoundError(
                f"sdg-strategy aperture spec missing: {shown}\n"
                "  Guru: #SDG.00000003.NOSTRATEGY\n"
                "  Try: git submodule update --init external/sdg-strategy"
            )

        strategy_id = current.read_text(encoding="utf-8").strip()
        if not strategy_id:
            raise ValueError(
                "sdg-strategy CURRENT is empty.\n"
                "  Guru: #SDG.00000003.NOSTRATEGY"
            )

        snap = json.loads(snapshot.read_text(encoding="utf-8"))
        policy = json.loads(filt.read_text(encoding="utf-8"))
        bind = (
            json.loads(binding.read_text(encoding="utf-8"))
            if binding.is_file()
            else {}
        )
        registered = policy.get("registered") or {}
        try:
            tau = float(registered["domain_tau"])
            window_chars = int(registered["window_chars"])
            colbert_token_limit = int(registered["colbert_token_limit"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "admission_filter.registered missing domain_tau / "
                "window_chars / colbert_token_limit.\n"
                "  Guru: #SDG.00000004.NOAPERTURE"
            ) from exc

        points = snap.get("points") or []
        if not points:
            raise ValueError(
                f"aperture snapshot has no points: {snapshot}\n"
                "  Guru: #SDG.00000004.NOAPERTURE"
            )

        anchors = tuple(
            ApertureAnchor(
                iri=str(pt["iri"]),
                label=str(pt.get("label") or ""),
                vector_sha=str(pt.get("vector_sha") or ""),
                local_name=_local_name(str(pt["iri"])),
            )
            for pt in points
        )
        collection = str(
            snap.get("collection") or bind.get("aiming_collection") or "sdg_aperture"
        )
        return cls(
            strategy_id=strategy_id,
            collection=collection,
            regime="threshold",
            tau=tau,
            window_chars=window_chars,
            colbert_token_limit=colbert_token_limit,
            anchors=anchors,
            root=checkout,
        )

    def resolve(self, token: str) -> ApertureAnchor | None:
        if not token:
            return None
        if token.startswith("http://") or token.startswith("https://"):
            for a in self.anchors:
                if a.iri == token:
                    return a
            return None
        key = token.removeprefix("SDG.")
        for a in self.anchors:
            if a.local_name == token or a.local_name == key:
                return a
        return None

    @property
    def n(self) -> int:
        return len(self.anchors)
