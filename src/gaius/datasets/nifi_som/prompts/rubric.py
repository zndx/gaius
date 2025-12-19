"""XAI Rubric Evaluation Prompt for 6-Dimension Scoring.

Defines the prompt template that extracts all 6 dimensions in a single
frontier model call. Returns machine-readable JSON with:
- Score (0-4) per dimension
- Evidence (1-2 sentences) per dimension
- Error type if score <= 2

The prompt is designed to maximize signal extraction from expensive
XAI calls while maintaining consistent evaluation standards.
"""

from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# System Prompt
# ─────────────────────────────────────────────────────────────────────────────

RUBRIC_SYSTEM_PROMPT = """You are evaluating a UI instruction for Apache NiFi workflow automation.

Score each dimension INDEPENDENTLY using the 0-4 anchors provided below. For each dimension:
- SCORE: integer 0-4 (use the anchors as reference)
- EVIDENCE: 1-2 sentences referencing specific elements from the instruction/marks
- ERROR_TYPE: required if score <= 2, choose from: misunderstanding, grounding_failure, wrong_action, trace_divergence, constraint_violation, incomplete_task

DIMENSION A - Intent Understanding (weight: 0.15)
Did the instruction correctly capture what the user wants to accomplish?
0 = Task intent misunderstood or contradicted
1 = Partial intent grasp; major ambiguity unresolved
2 = Core intent understood, secondary constraints missed
3 = Intent fully understood, minor phrasing mismatch
4 = Intent fully understood and precisely operationalized

DIMENSION B - SoM Grounding Accuracy (weight: 0.20)
Are the Set-of-Mark references (numbered elements) correctly matched to the instruction?
0 = Marks unrelated to relevant UI elements
1 = Correct region but wrong element
2 = Correct element class, wrong instance
3 = Correct element, imprecise localization
4 = Correct element with precise localization

DIMENSION C - Action Semantics (weight: 0.20)
Are the action types appropriate (click vs type vs drag vs scroll)?
0 = Actions fundamentally inappropriate
1 = Correct category occasionally, mostly wrong
2 = Mostly correct, one major mismatch
3 = Correct actions, suboptimal ordering
4 = Correct actions with optimal ordering

DIMENSION D - ToM Trace Fidelity (weight: 0.15)
For multi-step actions: does the trace match a plausible execution path?
For single actions: score 4/4 automatically (no trajectory to evaluate).
0 = Chaotic / implausible trace
1 = Weak alignment, erratic transitions
2 = Coarse alignment, timing or order issues
3 = Good alignment, minor inefficiencies
4 = Clean, efficient, human-plausible trace

DIMENSION E - Constraint Compliance (weight: 0.15)
Does the instruction respect explicit and implicit constraints?
Examples: "Do not modify other processors", "Stay in current flow", "Use right-click not double-click"
0 = Violated critical constraint
1 = Multiple minor violations
2 = One notable violation
3 = Minor technical deviation
4 = Fully compliant

DIMENSION F - Outcome Correctness (weight: 0.15)
Would following this instruction actually achieve the intended goal?
0 = No progress
1 = Progress but wrong end state
2 = Partial completion
3 = Correct outcome with extra steps
4 = Correct and minimal outcome

Respond with valid JSON only. No markdown code fences."""


# ─────────────────────────────────────────────────────────────────────────────
# User Prompt Template
# ─────────────────────────────────────────────────────────────────────────────

RUBRIC_USER_TEMPLATE = """Evaluate this NiFi UI instruction:

INSTRUCTION: {instruction}

TARGET ELEMENT: {target_name} (type: {target_type})

ACTION: {action_type}

AVAILABLE MARKS: {marks_description}

SCREENSHOT CONTEXT: {screenshot_context}

{constraints_section}

{trajectory_section}

Provide your evaluation as JSON:
{{
    "intent": {{
        "score": <0-4>,
        "evidence": "<1-2 sentences>",
        "error_type": "<required if score <= 2, else null>"
    }},
    "som_grounding": {{
        "score": <0-4>,
        "evidence": "<1-2 sentences>",
        "error_type": "<required if score <= 2, else null>"
    }},
    "action_semantics": {{
        "score": <0-4>,
        "evidence": "<1-2 sentences>",
        "error_type": "<required if score <= 2, else null>"
    }},
    "tom_trace": {{
        "score": <0-4>,
        "evidence": "<1-2 sentences>",
        "error_type": "<required if score <= 2, else null>"
    }},
    "constraints": {{
        "score": <0-4>,
        "evidence": "<1-2 sentences>",
        "error_type": "<required if score <= 2, else null>"
    }},
    "outcome": {{
        "score": <0-4>,
        "evidence": "<1-2 sentences>",
        "error_type": "<required if score <= 2, else null>"
    }}
}}"""


# ─────────────────────────────────────────────────────────────────────────────
# Prompt Builder
# ─────────────────────────────────────────────────────────────────────────────


def build_rubric_prompt(
    instruction: str,
    target_name: str,
    target_type: str,
    action_type: str,
    marks: list[dict],
    screenshot_context: str = "",
    constraints: Optional[list[str]] = None,
    trajectory: Optional[list[dict]] = None,
) -> tuple[str, str]:
    """Build the rubric evaluation prompt.

    Args:
        instruction: The instruction text to evaluate
        target_name: Name of the target UI element
        target_type: Type of the target element (e.g., GetHTTP, PutFile)
        action_type: Type of action (e.g., click, right_click, type)
        marks: List of mark dicts with {mark_id, element_name, bbox, ...}
        screenshot_context: Description of the screenshot content
        constraints: Optional list of explicit constraints
        trajectory: Optional list of trajectory steps for multi-action

    Returns:
        Tuple of (system_prompt, user_prompt)
    """
    # Format marks description
    marks_description = _format_marks(marks)

    # Format constraints section
    if constraints:
        constraints_section = "EXPLICIT CONSTRAINTS:\n" + "\n".join(
            f"- {c}" for c in constraints
        )
    else:
        constraints_section = "EXPLICIT CONSTRAINTS: None specified"

    # Format trajectory section
    if trajectory and len(trajectory) > 1:
        trajectory_section = "TRAJECTORY (multi-step):\n" + _format_trajectory(
            trajectory
        )
    else:
        trajectory_section = (
            "TRAJECTORY: Single action (score tom_trace as 4 automatically)"
        )

    user_prompt = RUBRIC_USER_TEMPLATE.format(
        instruction=instruction,
        target_name=target_name,
        target_type=target_type,
        action_type=action_type,
        marks_description=marks_description,
        screenshot_context=screenshot_context or "NiFi flow canvas with processors",
        constraints_section=constraints_section,
        trajectory_section=trajectory_section,
    )

    return RUBRIC_SYSTEM_PROMPT, user_prompt


def _format_marks(marks: list[dict]) -> str:
    """Format marks list into readable description."""
    if not marks:
        return "No marks available"

    lines = []
    for mark in marks:
        mark_id = mark.get("mark_id", mark.get("id", "?"))
        name = mark.get("element_name", mark.get("name", "unknown"))
        element_type = mark.get("element_type", mark.get("type", ""))
        bbox = mark.get("bbox", mark.get("bounding_box", []))

        if bbox:
            bbox_str = f"bbox={bbox}"
        else:
            bbox_str = ""

        type_str = f" ({element_type})" if element_type else ""
        lines.append(f"[{mark_id}] {name}{type_str} {bbox_str}")

    return "\n".join(lines)


def _format_trajectory(trajectory: list[dict]) -> str:
    """Format trajectory steps into readable sequence."""
    if not trajectory:
        return "Empty trajectory"

    lines = []
    for i, step in enumerate(trajectory, 1):
        action = step.get("action", step.get("action_type", "unknown"))
        target = step.get("target", step.get("element_name", "unknown"))
        value = step.get("value", "")

        value_str = f' "{value}"' if value else ""
        lines.append(f"{i}. {action} on {target}{value_str}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Response Parser
# ─────────────────────────────────────────────────────────────────────────────


def parse_rubric_response(response: str) -> dict:
    """Parse XAI rubric evaluation response.

    Args:
        response: Raw response string from XAI model

    Returns:
        Dict with dimension scores, evidence, and error_types
    """
    import json
    import re

    # Clean response - remove markdown fences if present
    cleaned = response.strip()
    if cleaned.startswith("```"):
        # Remove opening fence
        cleaned = re.sub(r"^```json?\n?", "", cleaned)
        # Remove closing fence
        cleaned = re.sub(r"\n?```$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Try to extract JSON from response
        json_match = re.search(r"\{[\s\S]*\}", cleaned)
        if json_match:
            try:
                data = json.loads(json_match.group())
            except json.JSONDecodeError:
                return _default_parse_error(str(e))
        else:
            return _default_parse_error(str(e))

    # Validate and normalize structure
    result = {}
    dimensions = [
        "intent",
        "som_grounding",
        "action_semantics",
        "tom_trace",
        "constraints",
        "outcome",
    ]

    for dim in dimensions:
        if dim in data and isinstance(data[dim], dict):
            score = data[dim].get("score", 2)
            evidence = data[dim].get("evidence", "No evidence provided")
            error_type = data[dim].get("error_type")

            # Validate score range
            if isinstance(score, (int, float)):
                score = max(0, min(4, int(score)))
            else:
                score = 2

            # Require error_type for low scores
            if score <= 2 and not error_type:
                error_type = "unspecified_error"

            result[dim] = {
                "score": score,
                "evidence": str(evidence),
                "error_type": error_type,
            }
        else:
            # Missing dimension - default to middle score
            result[dim] = {
                "score": 2,
                "evidence": "Dimension not evaluated",
                "error_type": "missing_evaluation",
            }

    return result


def _default_parse_error(error_msg: str) -> dict:
    """Return default scores when parsing fails."""
    dimensions = [
        "intent",
        "som_grounding",
        "action_semantics",
        "tom_trace",
        "constraints",
        "outcome",
    ]

    return {
        dim: {
            "score": 2,
            "evidence": f"Parse error: {error_msg}",
            "error_type": "parse_error",
        }
        for dim in dimensions
    }


# ─────────────────────────────────────────────────────────────────────────────
# Convenience Functions
# ─────────────────────────────────────────────────────────────────────────────


def compute_weighted_reward(parsed_response: dict) -> float:
    """Compute weighted reward from parsed rubric response.

    Uses dimension weights:
    - intent: 0.15
    - som_grounding: 0.20
    - action_semantics: 0.20
    - tom_trace: 0.15
    - constraints: 0.15
    - outcome: 0.15

    Args:
        parsed_response: Dict from parse_rubric_response

    Returns:
        Weighted reward in [0.0, 1.0]
    """
    weights = {
        "intent": 0.15,
        "som_grounding": 0.20,
        "action_semantics": 0.20,
        "tom_trace": 0.15,
        "constraints": 0.15,
        "outcome": 0.15,
    }

    total = 0.0
    for dim, weight in weights.items():
        if dim in parsed_response:
            score = parsed_response[dim].get("score", 2)
            normalized = score / 4.0
            total += normalized * weight

    return total


def extract_errors(parsed_response: dict) -> list[tuple[str, str, str]]:
    """Extract error information from parsed response.

    Returns list of (dimension, error_type, evidence) tuples for scores <= 2.
    """
    errors = []
    for dim, data in parsed_response.items():
        if data.get("score", 4) <= 2:
            errors.append((
                dim,
                data.get("error_type", "unknown"),
                data.get("evidence", ""),
            ))
    return errors
