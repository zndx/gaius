"""Structured decisions client for the ``decisions`` capability.

Metaflow asks for the capability ``decisions``. In Gaius that request is
the deployment ``thinking`` + ``dual-d3-flash``: Qwen3.8-27B stays on vLLM
on the heavy queue, and two ``vllm-sr/d3-flash`` replicas fill the light
queue. Each replica is the checkpoint's own ``d3_server.py``, which reads
``readout.safetensors``. This client posts ``{model, state, questions}``
to ``POST /v1/systemone``. It does not start a replica and it does not
fall back to thinking.

``/v1/decisions`` is the OpenAI-shaped name some gateways publish. The
d3 server's route is ``/v1/systemone``. Unknown body fields are HTTP 422,
so ``instructions`` are folded into a string state and a non-empty
``cache_salt`` is refused here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from gaius.engine.backends.vllm_controller import GURU_VLLM_TIMEOUT

GURU_NODECISION = "#EP.00000023.NODECISION"
GURU_BADDECISION = "#EP.00000024.BADDECISION"
GURU_NOTREADY = "#EP.00000016.NOTREADY"

DECISIONS_CAPABILITY = "decisions"
DECISIONS_MODEL_ID = "vllm-sr/d3-flash"
D3_DEPLOYMENT = "dual-d3-flash"
D3_FLASH_REPLICAS = ("d3-flash-0", "d3-flash-1")
THINKING_ENDPOINT = "thinking"
THINKING_MODEL_ID = "Qwen/Qwen3.8-27B"
SYSTEMONE_PATH = "/v1/systemone"

# d3_runtime bounds (d3_format.MAX_OPTIONS, SCORE_LEVELS). The 64-question
# cap is the client's sanity bound; the server enforces its own.
MAX_QUESTIONS = 64
MAX_CHOICE_OPTIONS = 255
MIN_SCORE_LEVELS = 2
MAX_SCORE_LEVELS = 10
QUESTION_TYPES = frozenset({"choice", "noul", "score"})
_HEALTHY = frozenset({"healthy", "running", "ready"})

_NOT_READY = (
    f"{GURU_NOTREADY} decisions endpoint is not healthy.\n"
    "  decisions keeps thinking on the heavy queue and serves "
    f"{D3_DEPLOYMENT} ({DECISIONS_MODEL_ID}, two light replicas).\n"
    "  Begin a workload that requires the decisions capability. "
    "Do not stop thinking. Decide does not start the model.\n"
    "  Try: /gpu status"
)


class DecisionError(RuntimeError):
    """A decision read that cannot be served or is not a valid request."""

    def __init__(self, guru: str, message: str, *, retryable: bool = False) -> None:
        self.guru = guru
        self.retryable = retryable
        super().__init__(message if message.startswith(guru) else f"{guru} {message}")


@dataclass(frozen=True)
class DecisionResult:
    id: str
    model: str
    answers: dict[str, Any]
    diagnostics: dict[str, Any]
    input_tokens: int
    output_tokens: int
    raw: dict[str, Any]


def systemone_url(base: str) -> str:
    """Join a replica origin or ``.../v1`` base to the systemone route."""
    b = (base or "").strip().rstrip("/")
    if not b:
        raise DecisionError(GURU_NODECISION, "decisions base URL is empty")
    if b.endswith("/v1"):
        return b + "/systemone"
    return b + SYSTEMONE_PATH


def parse_state_json(raw: str) -> Any:
    """Decode ``DecideRequest.state_json``.

    A JSON string, object, or array is the state. Invalid JSON is a
    caller error.
    """
    text = (raw or "").strip()
    if not text:
        raise DecisionError(
            GURU_BADDECISION,
            "state_json is empty.\n"
            '  A string state is a JSON string, e.g. "\\"the parcel arrived\\"".',
        )
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise DecisionError(
            GURU_BADDECISION,
            f"state_json is not JSON: {e}",
        ) from e


def criteria_from_json(raw: str, *, qid: str) -> Any:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise DecisionError(
            GURU_BADDECISION,
            f"question {qid!r} criteria_json is not JSON: {e}",
        ) from e


def validate_question(qid: str, qtype: str, instructions: str, criteria: Any) -> dict[str, Any]:
    """Return one System One question object, or raise ``DecisionError``.

    Instructions may be omitted. The d3 server rejects unknown question
    fields, so an empty instruction is left out of the object.
    """
    if not qid or not str(qid).strip():
        raise DecisionError(GURU_BADDECISION, "a question id is empty")
    kind = (qtype or "").strip().lower()
    if kind not in QUESTION_TYPES:
        raise DecisionError(
            GURU_BADDECISION,
            f"question {qid!r} type {qtype!r} is not one of "
            f"{sorted(QUESTION_TYPES)}",
        )
    body: dict[str, Any] = {"type": kind}
    gloss = (instructions or "").strip()
    if gloss:
        body["instructions"] = gloss
    if kind == "choice":
        if not isinstance(criteria, dict) or not criteria:
            raise DecisionError(
                GURU_BADDECISION,
                f"question {qid!r} choice criteria must be a non-empty "
                "object of option name to a description or null",
            )
        if len(criteria) > MAX_CHOICE_OPTIONS:
            raise DecisionError(
                GURU_BADDECISION,
                f"question {qid!r} has {len(criteria)} options; "
                f"the limit is {MAX_CHOICE_OPTIONS}",
            )
        for name, desc in criteria.items():
            if not isinstance(name, str) or not name.strip():
                raise DecisionError(
                    GURU_BADDECISION,
                    f"question {qid!r} has an empty choice option name",
                )
            if desc is not None and not isinstance(desc, str):
                raise DecisionError(
                    GURU_BADDECISION,
                    f"question {qid!r} option {name!r} description must be "
                    "a string or null",
                )
        body["criteria"] = criteria
    elif kind == "noul":
        if criteria is not None:
            if not isinstance(criteria, dict):
                raise DecisionError(
                    GURU_BADDECISION,
                    f"question {qid!r} noul criteria must be null or an object",
                )
            extra = set(criteria) - {"true", "false"}
            if extra:
                raise DecisionError(
                    GURU_BADDECISION,
                    f"question {qid!r} noul criteria has {sorted(extra)}; "
                    "only true and false are allowed",
                )
            for key, desc in criteria.items():
                if desc is not None and not isinstance(desc, str):
                    raise DecisionError(
                        GURU_BADDECISION,
                        f"question {qid!r} noul {key} description must be "
                        "a string or null",
                    )
        body["criteria"] = criteria
    else:
        levels = criteria if isinstance(criteria, list) else None
        distinct = (
            levels is not None
            and MIN_SCORE_LEVELS <= len(levels) <= MAX_SCORE_LEVELS
            and all(isinstance(level, str) and level.strip() for level in levels)
            and len({level.strip() for level in levels}) == len(levels)
        )
        if not distinct:
            raise DecisionError(
                GURU_BADDECISION,
                f"question {qid!r} score criteria must be an ordered list "
                f"of {MIN_SCORE_LEVELS} to {MAX_SCORE_LEVELS} distinct level names",
            )
        body["criteria"] = criteria
    return body


def _fold_instructions(state: Any, instructions: str) -> Any:
    text = (instructions or "").strip()
    if not text:
        return state
    if not isinstance(state, str):
        raise DecisionError(
            GURU_BADDECISION,
            "instructions can only be folded into a string state. "
            "d3_server rejects a top-level instructions field (HTTP 422).",
        )
    return text + "\n\n" + state


def build_systemone_body(
    state: Any,
    questions: list[tuple[str, str, str, Any]] | dict[str, dict[str, Any]],
    *,
    instructions: str = "",
    cache_salt: str = "",
    model: str = "",
) -> dict[str, Any]:
    """Build a d3 ``/v1/systemone`` body: ``model``, ``state``, ``questions``.

    ``questions`` is either an ordered list of
    ``(id, type, instructions, criteria)`` or a dict in ask order whose
    values are ``{type, instructions, criteria}``.
    """
    if (cache_salt or "").strip():
        raise DecisionError(
            GURU_BADDECISION,
            "cache_salt is not a d3_server field. The server rejects unknown "
            "fields with HTTP 422. Leave cache_salt empty.",
        )
    if isinstance(questions, dict):
        items: list[tuple[str, str, str, Any]] = []
        for qid, spec in questions.items():
            if not isinstance(spec, dict):
                raise DecisionError(
                    GURU_BADDECISION,
                    f"question {qid!r} must be an object with type, "
                    "instructions, and criteria",
                )
            extra = set(spec) - {"type", "instructions", "criteria"}
            if extra:
                raise DecisionError(
                    GURU_BADDECISION,
                    f"question {qid!r} has {sorted(extra)}; only type, "
                    "instructions, and criteria are allowed",
                )
            items.append(
                (
                    str(qid),
                    str(spec.get("type") or ""),
                    str(spec.get("instructions") or ""),
                    spec.get("criteria"),
                )
            )
    else:
        items = list(questions)

    if not items or len(items) > MAX_QUESTIONS:
        raise DecisionError(
            GURU_BADDECISION,
            f"a decision request has 1 to {MAX_QUESTIONS} questions "
            f"(got {len(items)})",
        )
    seen: set[str] = set()
    encoded: dict[str, Any] = {}
    for qid, qtype, q_instructions, criteria in items:
        if qid in seen:
            raise DecisionError(
                GURU_BADDECISION,
                f"question id {qid!r} is repeated",
            )
        seen.add(qid)
        encoded[qid] = validate_question(qid, qtype, q_instructions, criteria)

    body: dict[str, Any] = {
        "state": _fold_instructions(state, instructions),
        "questions": encoded,
    }
    if model:
        body["model"] = model
    return body


def parse_decision_response(payload: Any) -> DecisionResult:
    """Accept the d3 server shape ``{model, answers, usage}``.

    A vLLM ``object: structured_decision`` body is also accepted. A
    missing ``diagnostics`` object is ``{}``.
    """
    if not isinstance(payload, dict):
        raise DecisionError(
            GURU_NODECISION,
            f"systemone response is {type(payload).__name__}, not an object",
        )
    answers = payload.get("answers")
    obj = payload.get("object")
    if obj is not None and obj != "structured_decision":
        raise DecisionError(
            GURU_NODECISION,
            f"systemone response object is {obj!r}, not structured_decision",
        )
    if not isinstance(answers, dict) or not answers:
        raise DecisionError(
            GURU_NODECISION,
            "systemone response has no answers",
        )
    diagnostics = payload.get("diagnostics")
    if diagnostics is None:
        diagnostics = {}
    if not isinstance(diagnostics, dict):
        raise DecisionError(
            GURU_NODECISION,
            "systemone diagnostics is not an object",
        )
    usage = payload.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    return DecisionResult(
        id=str(payload.get("id") or ""),
        model=str(payload.get("model") or ""),
        answers=answers,
        diagnostics=diagnostics,
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        raw=payload,
    )


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code in (400, 422):
        raise DecisionError(
            GURU_BADDECISION,
            f"d3_server rejected the decision read ({response.status_code}): "
            f"{response.text[:500]}",
        )
    if response.status_code == 503:
        raise DecisionError(
            GURU_NODECISION,
            f"d3_server /v1/systemone returned 503: {response.text[:500]}\n"
            "  Try: /gpu status",
            retryable=True,
        )
    if response.status_code == 501:
        raise DecisionError(
            GURU_NODECISION,
            "the replica returned 501 for /v1/systemone. "
            f"decisions is served by d3_server ({DECISIONS_MODEL_ID}), "
            "not a vLLM logprobs route.\n"
            "  Try: /gpu logs d3-flash-0",
        )
    if response.status_code >= 400:
        raise DecisionError(
            GURU_NODECISION,
            f"d3_server /v1/systemone returned {response.status_code}: "
            f"{response.text[:500]}",
        )


def post_systemone(
    base: str,
    body: dict[str, Any],
    *,
    timeout_s: float = 180.0,
    client: httpx.Client | None = None,
) -> DecisionResult:
    """Blocking ``POST /v1/systemone``. ``client`` is for tests."""
    url = systemone_url(base)
    try:
        if client is None:
            with httpx.Client(timeout=timeout_s) as owned:
                response = owned.post(url, json=body)
        else:
            response = client.post(url, json=body, timeout=timeout_s)
    except httpx.TimeoutException as e:
        raise DecisionError(
            GURU_VLLM_TIMEOUT,
            f"decision read timed out after {timeout_s:.0f}s at {url}: {e}\n"
            "  Try: /health fix endpoints",
        ) from e
    except httpx.HTTPError as e:
        raise DecisionError(
            GURU_NODECISION,
            f"decision read failed at {url}: {e}\n  Try: /gpu status",
            retryable=True,
        ) from e
    _raise_for_status(response)
    try:
        payload = response.json()
    except json.JSONDecodeError as e:
        raise DecisionError(
            GURU_NODECISION,
            f"systemone response is not JSON: {e}",
        ) from e
    return parse_decision_response(payload)


async def apost_systemone(
    base: str,
    body: dict[str, Any],
    *,
    timeout_s: float = 180.0,
) -> DecisionResult:
    url = systemone_url(base)
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(url, json=body)
    except httpx.TimeoutException as e:
        raise DecisionError(
            GURU_VLLM_TIMEOUT,
            f"decision read timed out after {timeout_s:.0f}s at {url}: {e}\n"
            "  Try: /health fix endpoints",
        ) from e
    except httpx.HTTPError as e:
        raise DecisionError(
            GURU_NODECISION,
            f"decision read failed at {url}: {e}\n  Try: /gpu status",
            retryable=True,
        ) from e
    _raise_for_status(response)
    try:
        payload = response.json()
    except json.JSONDecodeError as e:
        raise DecisionError(
            GURU_NODECISION,
            f"systemone response is not JSON: {e}",
        ) from e
    return parse_decision_response(payload)


def _status_kind(status: Any) -> str:
    return str(getattr(status, "status", "") or "").lower().replace(
        "process_status_", ""
    )


def decisions_replicas(services: Any) -> list[tuple[str, str]]:
    """Healthy ``(base_url, alias)`` pairs, flash replicas first.

    Does not start anything. A live replica while the other is down is
    the other copy of the same model. Zero healthy replicas is NOTREADY.
    """
    orch = getattr(services, "orchestrator_service", None) if services else None
    if orch is None:
        raise DecisionError(GURU_NOTREADY, _NOT_READY)
    ordered: list[str] = list(D3_FLASH_REPLICAS)
    cap_map = getattr(orch, "_capability_map", None) or {}
    for alias in cap_map.get(DECISIONS_CAPABILITY) or []:
        name = str(alias)
        if name not in ordered and name not in ("cap_decisions", "decisions", THINKING_ENDPOINT):
            ordered.append(name)
    found: list[tuple[str, str]] = []
    for alias in ordered:
        status = orch.get_endpoint_status(alias)
        if status is None:
            continue
        port = int(getattr(status, "port", 0) or 0)
        if _status_kind(status) in _HEALTHY and port:
            found.append((f"http://127.0.0.1:{port}", alias))
    if not found:
        raise DecisionError(GURU_NOTREADY, _NOT_READY)
    return found


def decisions_base_url(services: Any) -> tuple[str, str]:
    """First healthy replica. Prefer ``decisions_replicas`` for fan-out."""
    return decisions_replicas(services)[0]


async def post_decision_replicas(
    replicas: list[tuple[str, str]],
    body: dict[str, Any],
    *,
    cursor: int = 0,
    timeout_s: float = 180.0,
    poster: Any = None,
) -> tuple[DecisionResult, str, str, int]:
    """Round-robin one systemone call across replicas.

    Fail over only when ``DecisionError.retryable`` is set (transport
    error or HTTP 503). A bad request, a timeout, or a 501 stays on the
    replica that answered it. Returns ``(result, base, alias, next_cursor)``.
    """
    if not replicas:
        raise DecisionError(GURU_NOTREADY, _NOT_READY)
    post = poster or apost_systemone
    n = len(replicas)
    start = cursor % n
    last: DecisionError | None = None
    for offset in range(n):
        base, alias = replicas[(start + offset) % n]
        try:
            result = await post(base, body, timeout_s=timeout_s)
        except DecisionError as e:
            last = e
            if e.retryable:
                continue
            raise
        return result, base, alias, start + offset + 1
    assert last is not None
    raise last
