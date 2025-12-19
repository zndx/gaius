"""Validation prompts for instruction-action alignment checking.

Uses Chain-of-Thought reflection to verify that an instruction
unambiguously maps to the expected UI element.
"""

ALIGNMENT_SYSTEM_PROMPT = """You are evaluating whether a natural language instruction clearly and unambiguously refers to a specific UI element.

You will be given:
1. An instruction (what the user wants to do)
2. A list of visible UI elements with their names and types

Your task:
1. Think step-by-step about which element the instruction refers to
2. Consider if there could be any ambiguity
3. Predict which element number the user means
4. Rate your confidence (high/medium/low)

Be strict - if there's genuine ambiguity, say so."""

ALIGNMENT_PROMPT = """Instruction: "{instruction}"

Visible UI Elements:
{element_list}

Think through this step-by-step:
1. What action does the instruction describe?
2. What element name/type does it reference?
3. Which numbered element matches best?
4. Is there any ambiguity?

Then output your answer in this exact format:
PREDICTED_ELEMENT: <number or "ambiguous">
CONFIDENCE: <high/medium/low>
REASONING: <brief explanation>"""


def get_alignment_prompt(
    instruction: str,
    elements: list[dict],
) -> tuple[str, str]:
    """Get prompts for alignment validation.

    Args:
        instruction: The instruction to validate
        elements: List of UI elements with 'id', 'name', 'type' keys

    Returns:
        Tuple of (system_prompt, user_prompt)
    """
    element_list = "\n".join(
        f"  [{e['id']}] {e['name']} ({e['type']})"
        for e in elements
    )

    user_prompt = ALIGNMENT_PROMPT.format(
        instruction=instruction,
        element_list=element_list,
    )

    return ALIGNMENT_SYSTEM_PROMPT, user_prompt


def parse_alignment_response(response: str) -> dict:
    """Parse the alignment validation response.

    Args:
        response: Raw LLM response

    Returns:
        Dict with 'predicted_element', 'confidence', 'reasoning', 'is_aligned'
    """
    result = {
        "predicted_element": None,
        "confidence": "low",
        "reasoning": "",
        "is_aligned": False,
        "raw_response": response,
    }

    lines = response.strip().split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith("PREDICTED_ELEMENT:"):
            value = line.split(":", 1)[1].strip()
            if value.lower() == "ambiguous":
                result["predicted_element"] = None
            else:
                try:
                    result["predicted_element"] = int(value)
                except ValueError:
                    result["predicted_element"] = None

        elif line.startswith("CONFIDENCE:"):
            value = line.split(":", 1)[1].strip().lower()
            if value in ("high", "medium", "low"):
                result["confidence"] = value

        elif line.startswith("REASONING:"):
            result["reasoning"] = line.split(":", 1)[1].strip()

    # Determine alignment: high confidence + valid prediction = aligned
    result["is_aligned"] = (
        result["predicted_element"] is not None
        and result["confidence"] in ("high", "medium")
    )

    return result


# Multi-step alignment for trajectories
TRAJECTORY_ALIGNMENT_PROMPT = """Instruction: "{instruction}"

This is a multi-step task. The expected sequence of elements to visit:
{expected_sequence}

All visible UI Elements:
{element_list}

Analyze whether the instruction clearly describes visiting these elements in this order.

Think through:
1. Does the instruction mention or imply each step?
2. Is the order clear or ambiguous?
3. Could someone misinterpret the intended sequence?

Output your answer:
SEQUENCE_ALIGNED: <yes/partial/no>
STEPS_CLEAR: <number of steps that are clearly identified>
CONFIDENCE: <high/medium/low>
REASONING: <brief explanation>"""


def get_trajectory_alignment_prompt(
    instruction: str,
    expected_marks: list[int],
    elements: list[dict],
) -> tuple[str, str]:
    """Get prompts for trajectory alignment validation."""
    element_list = "\n".join(
        f"  [{e['id']}] {e['name']} ({e['type']})"
        for e in elements
    )

    expected_sequence = " -> ".join(
        f"[{m}]" for m in expected_marks
    )

    user_prompt = TRAJECTORY_ALIGNMENT_PROMPT.format(
        instruction=instruction,
        expected_sequence=expected_sequence,
        element_list=element_list,
    )

    return ALIGNMENT_SYSTEM_PROMPT, user_prompt
