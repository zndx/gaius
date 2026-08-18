from gaius.engine.services.feature_probe import _collapse_features


def test_collapse_keeps_max_per_layer_feature() -> None:
    raw = [
        {"layer_idx": 0, "feature_idx": 1, "activation": 0.2},
        {"layer_idx": 0, "feature_idx": 1, "activation": 0.9},
        {"layer_idx": 12, "feature_idx": 5, "activation": 0.4},
    ]
    rows = _collapse_features(raw)
    by = {(l, i): a for l, i, a in rows}
    assert by[(0, 1)] == 0.9
    assert by[(12, 5)] == 0.4
