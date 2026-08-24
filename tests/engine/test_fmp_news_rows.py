from gaius.engine.services.fmp_client import _fmp_rows


def test_fmp_rows_list() -> None:
    assert len(_fmp_rows([{"title": "a"}, "x"])) == 1


def test_fmp_rows_wrapped() -> None:
    assert _fmp_rows({"content": [{"title": "a"}]})[0]["title"] == "a"
    assert _fmp_rows({"data": [{"title": "b"}]})[0]["title"] == "b"
    assert _fmp_rows("nope") == []
