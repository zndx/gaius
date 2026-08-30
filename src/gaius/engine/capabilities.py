"""Dual-constraint capability planner: method × model conjunction.

A federated ``Engine/Complete`` may name a capability SET, e.g.
``["cot_reasoning", "thinking"]`` — at most ONE *method* capability (an
optillm technique class) plus at most ONE *model* capability. The engine
fulfils the pair or fails fast with ``#EP.00000020.NOMIX``.

Single-call scaffold techniques (cot_reflection) are fulfilled
ENGINE-NATIVELY over the vLLM path so BOTH reasoning layers are captured —
the model's native ``reasoning_content`` and the method's scaffold — which an
optillm proxy hop drops. See signals-protocol
``specification/protocol/capabilities.md``.

This module is pure (no I/O): unit-testable without a GPU or a running
engine. The scaffold constants are byte-faithful copies of the INSTALLED
optillm's ``cot_reflection.py`` so engine-native fulfilment matches the
proxied technique exactly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

GURU_NOMIX = "#EP.00000020.NOMIX"
GURU_METHODTRACE = "#EP.00000021.METHODTRACE"

# Method-capability synonyms → optillm technique value.
METHOD_SYNONYMS = {
    "cot_reasoning": "cot_reflection",
    "reflection": "cot_reflection",
}

# Techniques the INSTALLED optillm actually serves: the intersection of the
# gaius OptillmTechnique enum and optillm's ``known_approaches`` (server.py).
# Never advertise or plan outside this set — optillm folds an unknown prefix
# into the model name and fails obscurely.
SERVABLE_METHODS = (
    "cot_reflection",
    "bon",
    "moa",
    "pvg",
    "re2",
    "self_consistency",
    "rstar",
    "plansearch",
)

# Single-call scaffold techniques the engine fulfils natively over vLLM
# (capturing the model layer an optillm hop drops).
ENGINE_NATIVE_TECHNIQUES = frozenset({"cot_reflection"})

DEFAULT_MODEL_CAPABILITY = "thinking"

# optillm's own request defaults for technique calls (cot_reflection.py) —
# used for parity when a capabilities[] request leaves them unset.
METHOD_DEFAULT_TEMPERATURE = 0.6
METHOD_DEFAULT_MAX_TOKENS = 4096


class CapabilityMixError(ValueError):
    """Unsatisfiable capabilities conjunction (#EP.00000020.NOMIX)."""


@dataclass(frozen=True)
class CapabilityPlan:
    """The engine's fulfilment plan for a capabilities[] conjunction."""

    method: Optional[str]  # optillm technique value; None = model-only plan
    model_capability: str  # requested (or defaulted) model capability
    model_alias: str  # resolved endpoint/agent alias
    engine_native: bool  # True: engine applies the scaffold itself over vLLM
    fulfilled_by: str  # provisional label; the router finalizes model/port


def offered_methods() -> list[str]:
    """Method capabilities this engine can serve (advertised on the wire)."""
    return list(SERVABLE_METHODS)


def offered_model_capabilities(services: Any = None) -> dict[str, list[str]]:
    """Model capability → candidate aliases.

    Union of ``sentinel_claim.DEPLOYMENT_PROFILES`` (what WORKLOADS
    advertises; the optillm proxy profile is excluded from alias candidacy —
    it serves methods, not models) and the orchestrator's live capability map
    when available.
    """
    out: dict[str, list[str]] = {}
    try:
        from gaius.engine.sentinel_claim import DEPLOYMENT_PROFILES

        for p in DEPLOYMENT_PROFILES.values():
            wrk = str(getattr(p, "wrk", "") or "")
            is_proxy = str(getattr(p, "model", "") or "") == "proxy"
            for cap in getattr(p, "capabilities", ()) or ():
                aliases = out.setdefault(str(cap), [])
                if wrk and not is_proxy and wrk not in aliases:
                    aliases.append(wrk)
    except Exception:  # pragma: no cover — profile import must not break planning
        pass

    orch = getattr(services, "orchestrator_service", None) if services else None
    cap_map = getattr(orch, "_capability_map", None) or {}
    for cap, aliases in cap_map.items():
        merged = out.setdefault(str(cap), [])
        for alias in aliases or []:
            if str(alias) not in merged:
                merged.append(str(alias))
    return out


def _resolve_alias(
    capability: str, offered: dict[str, list[str]], services: Any = None
) -> str:
    """Resolve a model capability to an alias, healthy-preferred when the
    orchestrator exposes a sync resolver; profile order otherwise."""
    orch = getattr(services, "orchestrator_service", None) if services else None
    resolver = getattr(orch, "get_healthy_endpoint_for_capability", None)
    if callable(resolver):
        try:
            result = resolver(capability)
            if hasattr(result, "__await__"):  # async resolver — planner is sync
                closer = getattr(result, "close", None)
                if callable(closer):
                    closer()
            elif result:
                return str(result)
        except Exception:  # pragma: no cover — health lookup must not break planning
            pass
    aliases = offered.get(capability) or []
    return aliases[0] if aliases else ""


def _nomix(
    caps: list[str],
    methods: list[str],
    models: list[str],
    unknown: list[str],
    services: Any = None,
) -> CapabilityMixError:
    offered = offered_model_capabilities(services)
    models_txt = (
        " ".join(
            f"{cap}[{','.join(aliases) or '-'}]" for cap, aliases in sorted(offered.items())
        )
        or "-"
    )
    method_desc = ", ".join(methods) or "-"
    model_desc = ", ".join(models) or "-"
    unknown_desc = f"  unknown: {', '.join(unknown)}\n" if unknown else ""
    return CapabilityMixError(
        f"{GURU_NOMIX} unsatisfiable capabilities {caps!r}:\n"
        f"  method caps: {method_desc}  model caps: {model_desc}\n"
        f"{unknown_desc}"
        f"  offered methods: {', '.join(SERVABLE_METHODS)}\n"
        f"  offered models:  {models_txt}\n"
        "  A request is a conjunction: at most ONE method capability + ONE model capability.\n"
        '  Try: capabilities=["cot_reasoning","thinking"]'
    )


def resolve_capabilities(
    caps: list[str] | None, services: Any = None
) -> Optional[CapabilityPlan]:
    """Plan the fulfilment of a capabilities[] conjunction.

    Returns None when ``caps`` is empty (legacy single-capability path).
    Raises CapabilityMixError (#EP.00000020.NOMIX) when the mix is
    unsatisfiable: ≥2 method caps, ≥2 model caps, any unknown/unservable
    token, or an unresolvable model capability.
    """
    cleaned = [str(c).strip() for c in (caps or []) if str(c or "").strip()]
    if not cleaned:
        return None

    offered_models = offered_model_capabilities(services)
    methods: list[str] = []
    models: list[str] = []
    unknown: list[str] = []

    for cap in cleaned:
        key = cap.lower()
        technique = METHOD_SYNONYMS.get(key, key)
        if technique in SERVABLE_METHODS and key not in offered_models:
            methods.append(technique)
        elif cap in offered_models:
            models.append(cap)
        elif key in offered_models:
            models.append(key)
        else:
            unknown.append(cap)

    if unknown or len(methods) > 1 or len(models) > 1:
        raise _nomix(cleaned, methods, models, unknown, services)

    method = methods[0] if methods else None
    model_capability = models[0] if models else DEFAULT_MODEL_CAPABILITY
    if model_capability not in offered_models:
        raise _nomix(cleaned, methods, [model_capability], [], services)

    model_alias = _resolve_alias(model_capability, offered_models, services)
    if not model_alias:
        raise _nomix(cleaned, methods, [model_capability], [], services)

    engine_native = bool(method) and method in ENGINE_NATIVE_TECHNIQUES
    if method:
        fulfilled_by = f"{method}@{'engine' if engine_native else 'optillm'}"
    else:
        fulfilled_by = f"direct@{model_alias}"

    return CapabilityPlan(
        method=method,
        model_capability=model_capability,
        model_alias=model_alias,
        engine_native=engine_native,
        fulfilled_by=fulfilled_by,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Engine-native cot_reflection primitives (byte-faithful to installed optillm)
# ─────────────────────────────────────────────────────────────────────────────

# The exact scaffold from optillm/cot_reflection.py (the f-string body,
# 8-space indentation and trailing spaces included) with {system_prompt} as
# the interpolation point. Fidelity matters: engine-native fulfilment must be
# indistinguishable from the proxied technique, prompt-wise.
COT_REFLECTION_SCAFFOLD = """
        {system_prompt}

        You are an AI assistant that uses a Chain of Thought (CoT) approach with reflection to answer queries. Follow these steps:

        1. Think through the problem step by step within the <thinking> tags.
        2. Reflect on your thinking to check for any errors or improvements within the <reflection> tags.
        3. Make any necessary adjustments based on your reflection.
        4. Provide your final, concise answer within the <output> tags.

        Important: The <thinking> and <reflection> sections are for your internal reasoning process only. 
        Do not include any part of the final answer in these sections. 
        The actual response to the query must be entirely contained within the <output> tags.

        Use the following format for your response:
        <thinking>
        [Your step-by-step reasoning goes here. This is your internal thought process, not the final answer.]
        <reflection>
        [Your reflection on your reasoning, checking for errors or improvements]
        </reflection>
        [Any adjustments to your thinking based on your reflection]
        </thinking>
        <output>
        [Your final, concise answer to the query. This is the only part that will be shown to the user.]
        </output>
        """

_THINKING_RE = re.compile(r"<thinking>(.*?)</thinking>", re.DOTALL)
# optillm's tolerant match: an unclosed </output> still yields the answer.
_OUTPUT_RE = re.compile(r"<output>(.*?)(?:</output>|$)", re.DOTALL)


def compose_cot_reflection_messages(
    system_prompt: Optional[str], prompt: str
) -> list[dict[str, str]]:
    """The exact two-message assembly optillm's cot_reflection makes."""
    scaffold = COT_REFLECTION_SCAFFOLD.format(system_prompt=system_prompt or "")
    return [
        {"role": "system", "content": scaffold},
        {"role": "user", "content": prompt},
    ]


def split_cot_reflection(full_response: str) -> tuple[str, str]:
    """Split a cot_reflection completion into (method_trace, output).

    method_trace is the verbatim ``<thinking>…</thinking>`` block (tags
    included; ``<reflection>`` nested inside) — '' when absent, never
    fabricated. output falls back to the whole response (optillm parity).
    """
    text = full_response or ""
    thinking_match = _THINKING_RE.search(text)
    method_trace = thinking_match.group(0) if thinking_match else ""
    output_match = _OUTPUT_RE.search(text)
    output = output_match.group(1).strip() if output_match else text
    return method_trace, output
