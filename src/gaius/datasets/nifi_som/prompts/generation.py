"""Generation prompts for diverse instruction generation.

Uses 5 style dimensions to generate varied instructions:
1. Technical - precise, uses NiFi terminology
2. Conversational - casual, natural language
3. Brief - minimal, action-focused
4. Detailed - includes context and reasoning
5. Action-oriented - imperative, direct commands
"""

SYSTEM_PROMPT = """You are an expert at writing natural language instructions for UI interactions.
You generate instructions that a user might give to an AI assistant to perform actions in Apache NiFi.

Key principles:
- Instructions should be clear and unambiguous
- Reference specific UI elements by their visible names
- Avoid mentioning internal IDs or technical identifiers
- Write as if speaking to an intelligent assistant who can see the screen"""

GENERATION_PROMPTS = {
    "technical": """Generate a TECHNICAL instruction for clicking on the "{processor_name}" processor.

Context:
- This is a {processor_type} processor in a NiFi flow
- The processor is located at position ({x:.0f}, {y:.0f}) on the canvas
- It is part of a flow that {flow_description}

Write a precise, technical instruction using NiFi terminology. Include the processor type and purpose.
The instruction should sound like it comes from a NiFi administrator.

Output only the instruction text, nothing else.""",

    "conversational": """Generate a CONVERSATIONAL instruction for clicking on the "{processor_name}" processor.

Context:
- This is a {processor_type} processor
- It is part of a flow that {flow_description}

Write a casual, natural-sounding instruction as if chatting with a helpful assistant.
Use everyday language, avoid jargon.

Output only the instruction text, nothing else.""",

    "brief": """Generate a BRIEF instruction for clicking on "{processor_name}".

This should be a short, direct command - ideally under 10 words.
Just tell the assistant what to click.

Output only the instruction text, nothing else.""",

    "detailed": """Generate a DETAILED instruction for clicking on the "{processor_name}" processor.

Context:
- This is a {processor_type} processor in Apache NiFi
- Position on canvas: ({x:.0f}, {y:.0f})
- The processor {processor_purpose}
- It is part of a flow that {flow_description}

Write a comprehensive instruction that includes:
1. What to click
2. Why (the purpose)
3. What to expect after clicking

Output only the instruction text, nothing else.""",

    "action_oriented": """Generate an ACTION-ORIENTED instruction for clicking the "{processor_name}" processor.

This should be a direct imperative command. Start with an action verb.
Examples of action verbs: Select, Click, Open, Access, Navigate to

Output only the instruction text, nothing else.""",
}


def get_generation_prompt(
    style: str,
    processor_name: str,
    processor_type: str,
    position: tuple[float, float],
    flow_description: str = "processes data",
    processor_purpose: str = "handles data transformation",
) -> tuple[str, str]:
    """Get system and user prompts for instruction generation.

    Args:
        style: One of 'technical', 'conversational', 'brief', 'detailed', 'action_oriented'
        processor_name: Display name of the processor
        processor_type: NiFi processor type (e.g., 'GetFile', 'PutS3Object')
        position: (x, y) position on canvas
        flow_description: Brief description of what the flow does
        processor_purpose: What this specific processor does

    Returns:
        Tuple of (system_prompt, user_prompt)
    """
    if style not in GENERATION_PROMPTS:
        style = "conversational"  # Default fallback

    user_prompt = GENERATION_PROMPTS[style].format(
        processor_name=processor_name,
        processor_type=processor_type,
        x=position[0],
        y=position[1],
        flow_description=flow_description,
        processor_purpose=processor_purpose,
    )

    return SYSTEM_PROMPT, user_prompt


# Connection-specific prompts
CONNECTION_PROMPTS = {
    "technical": """Generate a TECHNICAL instruction for clicking the connection from "{source_name}" to "{dest_name}".

Context:
- This connection carries {relationships} relationships
- Source: {source_type} processor
- Destination: {dest_type} processor

Write a precise instruction using NiFi terminology about connections and relationships.

Output only the instruction text, nothing else.""",

    "conversational": """Generate a CONVERSATIONAL instruction for clicking the connection between "{source_name}" and "{dest_name}".

Write a natural-sounding instruction for selecting this data flow connection.

Output only the instruction text, nothing else.""",

    "brief": """Generate a BRIEF instruction for clicking the connection from "{source_name}" to "{dest_name}".

Short and direct - under 10 words.

Output only the instruction text, nothing else.""",
}


def get_connection_prompt(
    style: str,
    source_name: str,
    dest_name: str,
    source_type: str = "processor",
    dest_type: str = "processor",
    relationships: str = "success",
) -> tuple[str, str]:
    """Get prompts for connection instruction generation."""
    if style not in CONNECTION_PROMPTS:
        style = "conversational"

    user_prompt = CONNECTION_PROMPTS[style].format(
        source_name=source_name,
        dest_name=dest_name,
        source_type=source_type,
        dest_type=dest_type,
        relationships=relationships,
    )

    return SYSTEM_PROMPT, user_prompt


# Trajectory prompts for ToM
TRAJECTORY_PROMPT = """Generate an instruction for a multi-step navigation task.

The task involves visiting these processors in order:
{step_list}

Context:
- This is part of a {flow_name} flow
- The flow {flow_description}

Write a natural instruction that describes the entire navigation task.
Focus on the goal, not individual clicks.

Output only the instruction text, nothing else."""


def get_trajectory_prompt(
    steps: list[str],
    flow_name: str,
    flow_description: str = "processes data through multiple stages",
) -> tuple[str, str]:
    """Get prompts for trajectory instruction generation."""
    step_list = "\n".join(f"{i+1}. {step}" for i, step in enumerate(steps))

    user_prompt = TRAJECTORY_PROMPT.format(
        step_list=step_list,
        flow_name=flow_name,
        flow_description=flow_description,
    )

    return SYSTEM_PROMPT, user_prompt
