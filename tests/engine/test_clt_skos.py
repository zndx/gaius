"""CLT SKOS admit + span grounding — no GPU."""

from __future__ import annotations

import pytest

from gaius.engine.services.clt_skos_admit import GURU_NOMAXSIM, admit_text
from gaius.engine.services.clt_skos_ground import GroundError, spans_for_features
from gaius.engine.services.sdg_aperture import SdgAperture


def test_spans_drop_empty_and_map_positions() -> None:
    feats = [
        {"model": "clt", "layer_idx": 0, "feature_idx": 1, "position": 0, "activation": 0.5},
        {"model": "clt", "layer_idx": 2, "feature_idx": 9, "position": 2, "activation": 1.2},
    ]
    offsets = [(0, 0), (0, 3), (4, 8)]
    rows = spans_for_features(feats, offsets)
    assert rows == [("clt", 2, 9, 2, 4, 8, 1.2)]


def test_spans_fail_on_oob_position() -> None:
    feats = [{"layer_idx": 0, "feature_idx": 1, "position": 9, "activation": 1.0}]
    with pytest.raises(GroundError, match="CLT.00000010"):
        spans_for_features(feats, [(0, 1)])


def test_admit_requires_maxsim_when_asked() -> None:
    ap = SdgAperture.load()
    with pytest.raises(RuntimeError, match="NOMAXSIM"):
        admit_text("hello world", aperture=ap, maxsim=None, require_maxsim=True)


def test_admit_windows_with_mock_maxsim() -> None:
    ap = SdgAperture.load()

    def maxsim(chunk: str) -> tuple[str, float]:
        return ("DATAENG", 0.4)

    def fake_offs(text: str) -> list[tuple[int, int]]:
        return [(i, i + 1) for i in range(0, min(len(text), 40))]

    kept = admit_text(
        "distributed systems " * 80,
        aperture=ap,
        maxsim=maxsim,
        require_maxsim=True,
        encode_offsets=fake_offs,
    )
    assert kept
    assert all(w.admitted and w.code == "DATAENG" for w in kept)


def test_write_candidate_ttl(tmp_path) -> None:
    from gaius.engine.services.clt_skos_propose import write_candidate_ttl

    dest = tmp_path / "clt.skos.ttl"
    path = write_candidate_ttl([(0, 1, 3), (20, 5, 2)], dest=dest)
    text = path.read_text()
    assert "skos:notation \"0:1\"" in text
    assert "skos:broader" in text
    assert "band_early" in text and "band_late" in text


def test_parse_align_reply_json() -> None:
    from gaius.engine.services.clt_skos_align import parse_align_reply

    got = parse_align_reply(
        'Sure.\n{"match":"relatedMatch","sdg_uri":"https://signals.zndx.org/sdg#MFG","reason":"spans mention process"}\n'
    )
    assert got["match"] == "relatedMatch"
    assert got["sdg_uri"].endswith("#MFG")


def test_align_prompt_is_sanitized() -> None:
    from gaius.engine.services.clt_skos_align import AmbiguousCase, build_align_prompt

    case = AmbiguousCase(
        layer=0,
        feature_idx=1,
        clt_uri="https://signals.zndx.org/clt/qwen3-1.7b-20k#L0F1",
        notation="0:1",
        pref_label="L0 F1",
        codes=["MFG"],
        item_ids=[1],
        logits=["sk-ant-api03-ABCDEFGHIJKLMNOPQRST"],
        span_glosss=["ok"],
    )
    prompt = build_align_prompt(case)
    assert "ABCDEFGHIJKLMNOPQRST" not in prompt
    assert "REDACTED" in prompt
    assert "relatedMatch" in prompt
    assert "skos:broader" in prompt


def test_guru_string_present() -> None:
    assert "SDG.00000005" in GURU_NOMAXSIM
