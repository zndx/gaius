"""Task instruction generation for NiFi SoM dataset."""

import random
from typing import Optional

from .models import Processor, Action


# Templates for generating task instructions
INSTRUCTION_TEMPLATES = {
    "click": [
        "Click on the {processor_name} processor",
        "Select the {processor_name} step",
        "Open the {processor_name} processor configuration",
        "Navigate to the {processor_name} component",
    ],
    "configure": [
        "Configure the {processor_name} processor to {purpose}",
        "Update the settings for {processor_name}",
        "Modify the {processor_name} processor properties",
    ],
    "connect": [
        "Connect {source} to {destination}",
        "Create a connection from {source} to {destination}",
        "Link the output of {source} to {destination}",
    ],
    "flow": [
        "Create a data flow that {description}",
        "Build a NiFi pipeline to {description}",
        "Set up a workflow to {description}",
    ],
}

# Purposes for different processor types
PROCESSOR_PURPOSES = {
    "fetch_pdf": "download the PDF from arXiv",
    "convert_to_markdown": "convert the PDF content to markdown format",
    "extract_topics": "extract key topics from the document",
    "score_relevance": "calculate relevance scores",
    "create_zettelkasten": "create knowledge base entries",
    "archive_step": "archive the processed document",
    "start": "initialize the pipeline",
    "end": "complete the workflow",
}


class InstructionGenerator:
    """Generate natural language task instructions."""

    def __init__(self, templates: dict | None = None):
        self.templates = templates or INSTRUCTION_TEMPLATES

    def generate_click_instruction(
        self, processor: Processor, purpose: Optional[str] = None
    ) -> str:
        """Generate an instruction to click on a processor.

        Args:
            processor: The target processor
            purpose: Optional specific purpose for the click

        Returns:
            Natural language instruction
        """
        template = random.choice(self.templates["click"])
        instruction = template.format(processor_name=processor.name)

        if purpose:
            instruction += f" to {purpose}"

        return instruction

    def generate_configure_instruction(
        self, processor: Processor, purpose: Optional[str] = None
    ) -> str:
        """Generate an instruction to configure a processor."""
        if purpose is None:
            purpose = PROCESSOR_PURPOSES.get(
                processor.name, "update the settings"
            )

        template = random.choice(self.templates["configure"])
        return template.format(processor_name=processor.name, purpose=purpose)

    def generate_connect_instruction(
        self, source: Processor, destination: Processor
    ) -> str:
        """Generate an instruction to connect two processors."""
        template = random.choice(self.templates["connect"])
        return template.format(source=source.name, destination=destination.name)

    def generate_flow_instruction(self, flow_name: str, steps: list[str]) -> str:
        """Generate an instruction describing the overall flow."""
        # Create a description from the steps
        if "fetch_pdf" in steps and "convert_to_markdown" in steps:
            description = "process arXiv papers into structured knowledge"
        elif "extract_topics" in steps:
            description = "extract topics and analyze documents"
        else:
            description = f"execute the {flow_name} pipeline"

        template = random.choice(self.templates["flow"])
        return template.format(description=description)

    def generate_for_action(
        self,
        action: Action,
        processors: list[Processor],
        connections: list | None = None,
    ) -> str:
        """Generate an instruction for a specific action.

        Args:
            action: The action to generate instruction for
            processors: List of processors in the flow
            connections: Optional list of connections

        Returns:
            Natural language instruction
        """
        if action.target_mark is None:
            return self.generate_flow_instruction(
                "flow", [p.name for p in processors]
            )

        # Find the target processor
        target_idx = action.target_mark - 1
        if target_idx < 0 or target_idx >= len(processors):
            return "Interact with the NiFi canvas"

        target = processors[target_idx]

        if action.type == "click":
            return self.generate_click_instruction(target)
        elif action.type == "configure":
            return self.generate_configure_instruction(target)
        elif action.type == "connect":
            # Find destination from metadata
            dest_name = action.metadata.get("destination", "")
            dest = next((p for p in processors if p.name == dest_name), None)
            if dest:
                return self.generate_connect_instruction(target, dest)
            return f"Connect {target.name} to the next processor"
        else:
            return self.generate_click_instruction(target)

    def generate_variants(
        self, instruction: str, num_variants: int = 3
    ) -> list[str]:
        """Generate paraphrased variants of an instruction.

        For now, this returns simple template-based variants.
        In the future, this could use an LLM for more diverse paraphrasing.

        Args:
            instruction: The base instruction
            num_variants: Number of variants to generate

        Returns:
            List of instruction variants including the original
        """
        variants = [instruction]

        # Simple rule-based variants
        if instruction.startswith("Click on"):
            variants.append(instruction.replace("Click on", "Select"))
            variants.append(instruction.replace("Click on", "Open"))
        elif instruction.startswith("Configure"):
            variants.append(instruction.replace("Configure", "Update"))
            variants.append(instruction.replace("Configure", "Modify"))
        elif instruction.startswith("Connect"):
            variants.append(instruction.replace("Connect", "Link"))

        return variants[:num_variants]
