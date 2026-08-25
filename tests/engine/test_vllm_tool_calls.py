"""Native vLLM tool_calls → `<tool_call>` markup for Engine/Complete.

Complete is text-in/text-out, but the Web Terminal harness needs OpenAI
`tool_calls`. vLLM's engine-level Qwen3 parser empties `content` when it
extracts a call, so the controller writes the markup back into the body
for the gaius-ui façade to re-parse.
"""

from __future__ import annotations

import json

import pytest

from gaius.engine.backends.vllm_controller import (
    ProcessStatus,
    VLLMController,
    VLLMProcess,
    VLLMRequest,
    parse_qwen_tool_call_markup,
    qwen_tool_call_markup,
)


def _decode(markup: str) -> list[dict]:
    out = []
    rest = markup
    while "<tool_call>" in rest:
        start = rest.index("<tool_call>") + len("<tool_call>")
        end = rest.index("</tool_call>", start)
        out.append(json.loads(rest[start:end]))
        rest = rest[end:].replace("</tool_call>", "", 1)
    return out


class TestQwenToolCallMarkup:
    def test_string_arguments_are_decoded(self):
        calls = [
            {
                "id": "chatcmpl-tool-1",
                "type": "function",
                "function": {
                    "name": "run_terminal_command",
                    "arguments": '{"command": "ss -ltnp"}',
                },
            }
        ]
        decoded = _decode(qwen_tool_call_markup(calls))
        assert decoded == [
            {"name": "run_terminal_command", "arguments": {"command": "ss -ltnp"}}
        ]

    def test_parallel_calls_each_get_a_block(self):
        calls = [
            {"function": {"name": "read_file", "arguments": '{"path": "a"}'}},
            {"function": {"name": "read_file", "arguments": '{"path": "b"}'}},
        ]
        markup = qwen_tool_call_markup(calls)
        assert markup.count("<tool_call>") == 2
        assert [c["arguments"]["path"] for c in _decode(markup)] == ["a", "b"]

    def test_dict_arguments_pass_through(self):
        calls = [{"function": {"name": "grep", "arguments": {"pattern": "vllm"}}}]
        assert _decode(qwen_tool_call_markup(calls))[0]["arguments"] == {
            "pattern": "vllm"
        }

    def test_unparsable_arguments_are_preserved_not_dropped(self):
        calls = [{"function": {"name": "grep", "arguments": "{oops"}}]
        assert _decode(qwen_tool_call_markup(calls))[0]["arguments"] == {
            "_raw": "{oops"
        }

    def test_nameless_and_empty_inputs_yield_nothing(self):
        assert qwen_tool_call_markup(None) == ""
        assert qwen_tool_call_markup([]) == ""
        assert qwen_tool_call_markup("tool_calls") == ""
        assert qwen_tool_call_markup([{"function": {"arguments": "{}"}}]) == ""


class TestToolSupportGate:
    """tools[] on an endpoint without --enable-auto-tool-choice is a 400."""

    @pytest.mark.asyncio
    async def test_endpoint_without_the_flag_fails_fast(self):
        controller = VLLMController.__new__(VLLMController)
        controller._client = object()
        controller._processes = {
            "interpretable": VLLMProcess(
                agent_alias="interpretable",
                model="Qwen/Qwen3-1.7B",
                port=8090,
                gpu_ids=[5],
                status=ProcessStatus.HEALTHY,
                supports_tool_calls=False,
            )
        }
        resp = await controller.complete(
            VLLMRequest(
                messages=[{"role": "user", "content": "hi"}],
                model="Qwen/Qwen3-1.7B",
                agent_alias="interpretable",
                extra_body={"tools": [{"type": "function"}], "tool_choice": "auto"},
            )
        )
        assert not resp.success
        assert "#VLLM.00000004.NOTOOLCALL" in resp.error
        assert "--enable-auto-tool-choice" in resp.error
        assert "interpretable" in resp.error

    def test_support_defaults_closed(self):
        """An endpoint that never recorded its argv must not be sent tools."""
        assert VLLMProcess(
            agent_alias="x", model="m", port=1, gpu_ids=[]
        ).supports_tool_calls is False

    @pytest.mark.asyncio
    async def test_tools_reach_the_openai_body_and_come_back_as_markup(self):
        sent: dict = {}

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "model": "Qwen/Qwen3.8-27B",
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "content": None,
                                "reasoning_content": "check the ports",
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "run_terminal_command",
                                            "arguments": '{"command": "ss -ltnp"}',
                                        }
                                    }
                                ],
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 22},
                }

        class _Client:
            async def post(self, url, json=None, timeout=None):
                sent["url"] = url
                sent["json"] = json
                return _Resp()

        controller = VLLMController.__new__(VLLMController)
        controller._client = _Client()
        controller._processes = {
            "thinking": VLLMProcess(
                agent_alias="thinking",
                model="Qwen/Qwen3.8-27B",
                port=8081,
                gpu_ids=[0, 1, 2, 3],
                status=ProcessStatus.HEALTHY,
                supports_tool_calls=True,
            )
        }
        tools = [
            {
                "type": "function",
                "function": {"name": "run_terminal_command", "parameters": {}},
            }
        ]
        resp = await controller.complete(
            VLLMRequest(
                messages=[{"role": "user", "content": "what port?"}],
                model="Qwen/Qwen3.8-27B",
                agent_alias="thinking",
                extra_body={"tools": tools, "tool_choice": "required"},
            )
        )

        assert sent["json"]["tools"] == tools
        assert sent["json"]["tool_choice"] == "required"
        # Thinking stays on alongside tools.
        assert sent["json"]["chat_template_kwargs"]["enable_thinking"] is True

        assert resp.success
        assert resp.finish_reason == "tool_calls"
        assert resp.reasoning_content == "check the ports"
        assert _decode(resp.content) == [
            {
                "name": "run_terminal_command",
                "arguments": {"command": "ss -ltnp"},
            }
        ]


class TestMarkupRoundTrip:
    """Encoder and decoder must agree — the CLI gate reads what Complete writes."""

    def test_round_trip_preserves_names_and_arguments(self):
        calls = [
            {"function": {"name": "run_terminal_command", "arguments": '{"command": "ss -ltnp"}'}},
            {"function": {"name": "read_file", "arguments": {"path": "devenv.nix"}}},
        ]
        text, decoded = parse_qwen_tool_call_markup(qwen_tool_call_markup(calls))
        assert text == ""
        assert decoded == [
            {"name": "run_terminal_command", "arguments": {"command": "ss -ltnp"}},
            {"name": "read_file", "arguments": {"path": "devenv.nix"}},
        ]

    def test_prose_around_a_call_survives(self):
        markup = qwen_tool_call_markup(
            [{"function": {"name": "grep", "arguments": {"pattern": "vllm"}}}]
        )
        text, decoded = parse_qwen_tool_call_markup(f"Checking the ports.\n{markup}")
        assert text == "Checking the ports."
        assert decoded[0]["name"] == "grep"

    def test_plain_text_decodes_to_no_calls(self):
        assert parse_qwen_tool_call_markup("port 8081") == ("port 8081", [])
        assert parse_qwen_tool_call_markup("") == ("", [])

    def test_unterminated_block_is_kept_visible(self):
        text, decoded = parse_qwen_tool_call_markup('tail <tool_call>{"name":"x"}')
        assert decoded == []
        assert "<tool_call>" in text
