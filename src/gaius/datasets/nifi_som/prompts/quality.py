"""Quality scoring prompts for instruction evaluation.

Rubric-based scoring with 4 dimensions:
- Clarity (30%): Is the instruction unambiguous?
- Naturalness (25%): Does it sound like a real user?
- Specificity (25%): Does it uniquely identify the target?
- Conciseness (20%): Is it appropriately brief?
"""

QUALITY_SYSTEM_PROMPT = """You are evaluating the quality of natural language instructions for UI interactions.

Score each instruction on a rubric with 4 dimensions.
Be consistent and fair - compare against what a typical user might say."""

QUALITY_RUBRIC_PROMPT = """Rate this instruction for clicking on a UI element.

Instruction: "{instruction}"
Target element: {target_name} ({target_type})

Score each dimension from 0.0 to 1.0:

1. CLARITY (30%): Is the instruction clear and unambiguous?
   - 1.0: Crystal clear, no possible confusion
   - 0.7: Clear to most people
   - 0.5: Somewhat ambiguous
   - 0.3: Confusing
   - 0.0: Incomprehensible

2. NATURALNESS (25%): Does it sound like something a real user would say?
   - 1.0: Very natural, conversational
   - 0.7: Sounds human
   - 0.5: Slightly robotic
   - 0.3: Clearly templated
   - 0.0: Unnatural/awkward

3. SPECIFICITY (25%): Does it uniquely identify the target element?
   - 1.0: Uniquely identifies the element
   - 0.7: Very likely to find the right element
   - 0.5: Could match multiple elements
   - 0.3: Vague reference
   - 0.0: No clear target

4. CONCISENESS (20%): Is it appropriately brief?
   - 1.0: Perfect length, no wasted words
   - 0.7: Slightly verbose but fine
   - 0.5: Too long or too short
   - 0.3: Very verbose or cryptically short
   - 0.0: Extremely verbose or just a single word

Output your scores in this exact format:
CLARITY: <score>
NATURALNESS: <score>
SPECIFICITY: <score>
CONCISENESS: <score>
OVERALL: <weighted average>
NOTES: <brief feedback>"""


def get_quality_prompt(
    instruction: str,
    target_name: str,
    target_type: str,
) -> tuple[str, str]:
    """Get prompts for quality scoring.

    Args:
        instruction: The instruction to evaluate
        target_name: Name of the target UI element
        target_type: Type of the target element (processor, connection, etc.)

    Returns:
        Tuple of (system_prompt, user_prompt)
    """
    user_prompt = QUALITY_RUBRIC_PROMPT.format(
        instruction=instruction,
        target_name=target_name,
        target_type=target_type,
    )

    return QUALITY_SYSTEM_PROMPT, user_prompt


def parse_quality_response(response: str) -> dict:
    """Parse the quality scoring response.

    Args:
        response: Raw LLM response

    Returns:
        Dict with dimension scores, overall score, and notes
    """
    result = {
        "clarity": 0.0,
        "naturalness": 0.0,
        "specificity": 0.0,
        "conciseness": 0.0,
        "overall": 0.0,
        "notes": "",
        "raw_response": response,
    }

    weights = {
        "clarity": 0.30,
        "naturalness": 0.25,
        "specificity": 0.25,
        "conciseness": 0.20,
    }

    lines = response.strip().split("\n")
    for line in lines:
        line = line.strip()
        for dim in ["CLARITY", "NATURALNESS", "SPECIFICITY", "CONCISENESS", "OVERALL"]:
            if line.upper().startswith(dim + ":"):
                try:
                    value = float(line.split(":", 1)[1].strip())
                    value = max(0.0, min(1.0, value))  # Clamp to [0, 1]
                    result[dim.lower()] = value
                except ValueError:
                    pass

        if line.upper().startswith("NOTES:"):
            result["notes"] = line.split(":", 1)[1].strip()

    # Compute weighted average if overall wasn't provided
    if result["overall"] == 0.0:
        # weights only references float dimension keys (clarity, naturalness, etc.)
        result["overall"] = sum(
            float(result[dim]) * weight  # type: ignore[arg-type] - result[dim] is numeric str from LLM
            for dim, weight in weights.items()
        )

    return result


# XAI calibration prompt - for frontier model evaluation
XAI_CALIBRATION_PROMPT = """You are a senior AI researcher evaluating instruction quality for a UI grounding dataset.

Instruction: "{instruction}"
Target: {target_name} ({target_type})
Local model score: {local_score:.2f}

Evaluate this instruction critically:
1. Is the local score accurate? (too high, about right, too low)
2. What is the true quality score? (0.0-1.0)
3. What specific improvements would you suggest?

Be rigorous - this is for calibrating a local model against frontier quality standards.

Output:
CALIBRATION: <too_high/about_right/too_low>
TRUE_SCORE: <your score 0.0-1.0>
DELTA: <difference from local score>
FEEDBACK: <specific improvements>"""


def get_calibration_prompt(
    instruction: str,
    target_name: str,
    target_type: str,
    local_score: float,
) -> tuple[str, str]:
    """Get prompts for XAI calibration evaluation."""
    user_prompt = XAI_CALIBRATION_PROMPT.format(
        instruction=instruction,
        target_name=target_name,
        target_type=target_type,
        local_score=local_score,
    )

    return QUALITY_SYSTEM_PROMPT, user_prompt


def parse_calibration_response(response: str) -> dict:
    """Parse the XAI calibration response."""
    result = {
        "calibration": "about_right",
        "true_score": 0.0,
        "delta": 0.0,
        "feedback": "",
        "raw_response": response,
    }

    lines = response.strip().split("\n")
    for line in lines:
        line = line.strip()
        if line.upper().startswith("CALIBRATION:"):
            value = line.split(":", 1)[1].strip().lower()
            if value in ("too_high", "about_right", "too_low"):
                result["calibration"] = value

        elif line.upper().startswith("TRUE_SCORE:"):
            try:
                value = float(line.split(":", 1)[1].strip())
                result["true_score"] = max(0.0, min(1.0, value))
            except ValueError:
                pass

        elif line.upper().startswith("DELTA:"):
            try:
                result["delta"] = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass

        elif line.upper().startswith("FEEDBACK:"):
            result["feedback"] = line.split(":", 1)[1].strip()

    return result
