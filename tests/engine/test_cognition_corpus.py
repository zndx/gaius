"""Unit tests for the cognition corpus reader (pure parts, no Iceberg)."""

from datetime import datetime, timezone

from gaius.engine.services.cognition_corpus import (
    GURU_NOTRACE,
    _parse_layers,
    _row_item,
)


def test_parse_layers_roundtrip():
    raw = (
        '[{"layer": "model", "producer": "vllm:8101", "tokens": 0, "text": "deep"},'
        ' {"layer": "method", "producer": "cot_reflection@engine", "tokens": 5244,'
        ' "text": "scaffold"}]'
    )
    layers = _parse_layers(raw)
    assert [layer["layer"] for layer in layers] == ["model", "method"]
    assert layers[1]["tokens"] == 5244
    assert layers[0]["text"] == "deep"


def test_parse_layers_tolerant():
    assert _parse_layers(None) == []
    assert _parse_layers("") == []
    assert _parse_layers("not json") == []
    assert _parse_layers('{"layer": "model"}') == []  # dict, not list
    assert _parse_layers('[42, {"layer": "model"}]') == [
        {"layer": "model", "producer": "", "tokens": 0, "text": ""}
    ]


def test_row_item_maps_and_flags_layers():
    gen = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
    item = _row_item(
        {
            "id": "abc",
            "flow_name": "ArticleCurationFlow",
            "step_name": "select_article",
            "run_id": "1729",
            "subject": "cyber-physical-systems",
            "technique": "cot_reflection",
            "model_name": "Qwen/Qwen3.8-27B",
            "decision": None,
            "confidence": None,
            "input_tokens": 1000,
            "output_tokens": 5244,
            "latency_ms": 90000,
            "generated_at": gen,
            "reasoning_layers": '[{"layer": "model", "text": "x"}]',
        }
    )
    assert item["generated_at_ms"] == int(gen.timestamp() * 1000)
    assert item["has_layers"] is True
    assert item["layer_count"] == 1
    assert item["decision"] == ""
    assert item["confidence"] == 0.0
    assert item["output_tokens"] == 5244


def test_row_item_no_layers():
    item = _row_item({"id": "x", "generated_at": None, "reasoning_layers": None})
    assert item["has_layers"] is False
    assert item["layer_count"] == 0
    assert item["generated_at_ms"] == 0


def test_fetch_trace_rejects_empty_id():
    import pytest

    from gaius.engine.services.cognition_corpus import fetch_trace

    with pytest.raises(ValueError) as exc:
        fetch_trace("")
    assert GURU_NOTRACE in str(exc.value)
