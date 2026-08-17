"""vLLM HTTP error formatting — empty ReadTimeout must stay a failure."""

from __future__ import annotations

import httpx

from gaius.engine.backends.vllm_controller import (
    GURU_VLLM_TIMEOUT,
    format_vllm_http_error,
)


def test_read_timeout_with_empty_message_is_nonempty():
    req = httpx.Request("POST", "http://127.0.0.1:8081/v1/chat/completions")
    exc = httpx.ReadTimeout("", request=req)
    assert str(exc) == ""
    msg = format_vllm_http_error(exc)
    assert msg
    assert GURU_VLLM_TIMEOUT in msg
    assert "ReadTimeout" in msg


def test_generic_exception_uses_type_when_message_empty():
    class Blank(Exception):
        def __str__(self) -> str:
            return ""

    assert format_vllm_http_error(Blank()) == "Blank"


def test_http_status_keeps_detail():
    assert "boom" in format_vllm_http_error(RuntimeError("boom"))
