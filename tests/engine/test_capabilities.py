"""Unit tests for the dual-constraint capability planner (pure, no GPU)."""

from types import SimpleNamespace

import pytest

from gaius.engine.capabilities import (
    COT_REFLECTION_SCAFFOLD,
    GURU_NOMIX,
    SERVABLE_METHODS,
    CapabilityMixError,
    compose_cot_reflection_messages,
    offered_methods,
    offered_model_capabilities,
    resolve_capabilities,
    split_cot_reflection,
)


def _services(cap_map=None):
    return SimpleNamespace(
        orchestrator_service=SimpleNamespace(_capability_map=cap_map or {})
    )


class TestResolveCapabilities:
    def test_empty_is_legacy_path(self):
        assert resolve_capabilities([]) is None
        assert resolve_capabilities(None) is None
        assert resolve_capabilities(["", "  "]) is None

    def test_synonym_maps_to_cot_reflection(self):
        plan = resolve_capabilities(["cot_reasoning", "thinking"])
        assert plan is not None
        assert plan.method == "cot_reflection"
        assert plan.model_capability == "thinking"
        assert plan.engine_native is True
        assert plan.fulfilled_by.startswith("cot_reflection@engine")

    def test_reflection_synonym(self):
        plan = resolve_capabilities(["reflection"])
        assert plan.method == "cot_reflection"

    def test_method_only_defaults_model_to_thinking(self):
        plan = resolve_capabilities(["cot_reasoning"])
        assert plan.model_capability == "thinking"
        assert plan.model_alias  # resolvable from DEPLOYMENT_PROFILES

    def test_model_only_plan_has_no_method(self):
        plan = resolve_capabilities(["thinking"])
        assert plan.method is None
        assert plan.engine_native is False
        assert plan.fulfilled_by.startswith("direct@")

    def test_optillm_composed_method_not_engine_native(self):
        plan = resolve_capabilities(["bon", "thinking"])
        assert plan.method == "bon"
        assert plan.engine_native is False
        assert plan.fulfilled_by == "bon@optillm"

    def test_two_methods_nomix(self):
        with pytest.raises(CapabilityMixError, match=GURU_NOMIX):
            resolve_capabilities(["cot_reasoning", "bon"])

    def test_two_models_nomix(self):
        with pytest.raises(CapabilityMixError, match=GURU_NOMIX):
            resolve_capabilities(["thinking", "complete"])

    def test_unknown_capability_nomix_lists_offerings(self):
        with pytest.raises(CapabilityMixError) as exc:
            resolve_capabilities(["cot_reasoning", "sae"])
        msg = str(exc.value)
        assert GURU_NOMIX in msg
        assert "sae" in msg
        assert "offered methods:" in msg
        assert "cot_reflection" in msg
        assert "offered models:" in msg

    def test_unservable_enum_members_nomix(self):
        # gaius' legacy enum "cot" is not in optillm's known_approaches
        with pytest.raises(CapabilityMixError, match=GURU_NOMIX):
            resolve_capabilities(["cot"])
        with pytest.raises(CapabilityMixError, match=GURU_NOMIX):
            resolve_capabilities(["mcts"])  # optillm-known but not in gaius enum

    def test_orchestrator_capability_map_extends_aliases(self):
        plan = resolve_capabilities(
            ["thinking"], _services({"thinking": ["thinking", "fast"]})
        )
        assert plan.model_alias == "thinking"

    def test_healthy_resolver_preferred(self):
        services = SimpleNamespace(
            orchestrator_service=SimpleNamespace(
                _capability_map={"thinking": ["thinking"]},
                get_healthy_endpoint_for_capability=lambda cap: "fast",
            )
        )
        plan = resolve_capabilities(["thinking"], services)
        assert plan.model_alias == "fast"


class TestOffered:
    def test_offered_methods_is_servable_set(self):
        methods = offered_methods()
        assert methods == list(SERVABLE_METHODS)
        assert "cot_reflection" in methods
        assert "pv" not in methods  # legacy enum value, unservable upstream
        assert "cot" not in methods

    def test_offered_model_capabilities_from_profiles(self):
        offered = offered_model_capabilities()
        assert "thinking" in offered
        assert "thinking" in offered["thinking"]
        # the optillm proxy profile advertises "complete" but is not a model alias
        assert "optillm" not in offered.get("complete", [])


class TestScaffold:
    def test_scaffold_interpolates_system_prompt(self):
        messages = compose_cot_reflection_messages("You are a curator.", "Pick one.")
        assert messages[0]["role"] == "system"
        assert messages[1] == {"role": "user", "content": "Pick one."}
        assert "You are a curator." in messages[0]["content"]

    def test_scaffold_is_byte_faithful_to_optillm(self):
        # Load-bearing lines from the installed optillm cot_reflection.py
        # (8-space indent; trailing spaces on the "Important" sentences).
        body = COT_REFLECTION_SCAFFOLD
        assert body.startswith("\n        {system_prompt}\n")
        assert (
            "        You are an AI assistant that uses a Chain of Thought (CoT) "
            "approach with reflection to answer queries. Follow these steps:" in body
        )
        assert "        1. Think through the problem step by step within the <thinking> tags." in body
        assert (
            "        Important: The <thinking> and <reflection> sections are for "
            "your internal reasoning process only. \n" in body
        )
        assert "        Do not include any part of the final answer in these sections. \n" in body
        assert body.rstrip("\n ").endswith("</output>")

    def test_split_round_trip(self):
        full = (
            "<thinking>\nstep 1\n<reflection>\nlooks right\n</reflection>\nadjusted\n</thinking>\n"
            "<output>\nParis\n</output>"
        )
        trace, output = split_cot_reflection(full)
        assert trace.startswith("<thinking>")
        assert trace.endswith("</thinking>")
        assert "<reflection>" in trace
        assert output == "Paris"

    def test_split_tolerates_unclosed_output(self):
        trace, output = split_cot_reflection("<thinking>t</thinking><output>partial answer")
        assert trace == "<thinking>t</thinking>"
        assert output == "partial answer"

    def test_split_without_scaffold_never_fabricates(self):
        trace, output = split_cot_reflection("plain answer, no tags")
        assert trace == ""
        assert output == "plain answer, no tags"

    def test_split_empty(self):
        assert split_cot_reflection("") == ("", "")
