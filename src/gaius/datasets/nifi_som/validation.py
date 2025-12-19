"""Instruction-action alignment validation using COT reflection.

Validates that instructions unambiguously map to expected UI elements.
Uses Chain-of-Thought reflection for systematic alignment checking.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from .prompts.validation import (
    get_alignment_prompt,
    parse_alignment_response,
    get_trajectory_alignment_prompt,
)

logger = logging.getLogger(__name__)


@dataclass
class AlignmentResult:
    """Result of alignment validation."""

    is_aligned: bool
    predicted_element: Optional[int]
    expected_element: Optional[int]
    confidence: str  # "high", "medium", "low"
    reasoning: str
    raw_response: str = ""


class InstructionValidator:
    """Validate instruction-action alignment via COT reflection.

    Uses Chain-of-Thought prompting to verify that:
    1. The instruction clearly identifies a target element
    2. The identified element matches the expected target
    3. There's no ambiguity that could lead to wrong actions

    This helps filter out instructions that:
    - Are too vague
    - Could match multiple elements
    - Use incorrect element names
    - Have ambiguous references

    Usage:
        validator = InstructionValidator()
        result = await validator.check_alignment(
            instruction="Click on the fetch_pdf processor",
            elements=[
                {"id": 1, "name": "fetch_pdf", "type": "GetHTTP"},
                {"id": 2, "name": "convert_to_markdown", "type": "ExecuteScript"},
            ],
            expected_mark=1,
        )
        if result.is_aligned:
            print("Instruction is valid")
    """

    def __init__(self, temperature: float = 0.3, max_tokens: int = 512):
        """Initialize the validator.

        Args:
            temperature: Low temperature for deterministic alignment checking
            max_tokens: Maximum tokens for response (includes reasoning)
        """
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = None

    async def _get_client(self):
        """Lazy-load inference client."""
        if self._client is None:
            from ...inference.client import InferenceClient
            self._client = InferenceClient()
        return self._client

    async def check_alignment(
        self,
        instruction: str,
        elements: list[dict],
        expected_mark: Optional[int],
    ) -> AlignmentResult:
        """Check if an instruction aligns with the expected element.

        Args:
            instruction: The natural language instruction
            elements: List of visible UI elements with 'id', 'name', 'type'
            expected_mark: The mark ID the instruction should refer to

        Returns:
            AlignmentResult with alignment status and reasoning
        """
        client = await self._get_client()
        from ...inference.client import Message

        system_prompt, user_prompt = get_alignment_prompt(instruction, elements)

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

        try:
            result = await client.complete(
                messages=messages,
                technique="cot_reflection",  # Chain-of-thought with reflection
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            parsed = parse_alignment_response(result.content)

            # Check if prediction matches expected
            is_aligned = parsed["is_aligned"]
            if expected_mark is not None and parsed["predicted_element"] is not None:
                is_aligned = (
                    parsed["predicted_element"] == expected_mark
                    and parsed["confidence"] in ("high", "medium")
                )

            return AlignmentResult(
                is_aligned=is_aligned,
                predicted_element=parsed["predicted_element"],
                expected_element=expected_mark,
                confidence=parsed["confidence"],
                reasoning=parsed["reasoning"],
                raw_response=result.content,
            )

        except Exception as e:
            logger.error(f"Alignment check failed: {e}")
            # Return uncertain result on failure
            return AlignmentResult(
                is_aligned=False,
                predicted_element=None,
                expected_element=expected_mark,
                confidence="low",
                reasoning=f"Alignment check failed: {e}",
            )

    async def check_trajectory_alignment(
        self,
        instruction: str,
        elements: list[dict],
        expected_marks: list[int],
    ) -> AlignmentResult:
        """Check if an instruction aligns with a multi-step trajectory.

        Args:
            instruction: The natural language instruction
            elements: List of visible UI elements
            expected_marks: Sequence of mark IDs the instruction should cover

        Returns:
            AlignmentResult with alignment status
        """
        client = await self._get_client()
        from ...inference.client import Message

        system_prompt, user_prompt = get_trajectory_alignment_prompt(
            instruction, expected_marks, elements
        )

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

        try:
            result = await client.complete(
                messages=messages,
                technique="cot_reflection",
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            # Parse trajectory-specific response
            lines = result.content.strip().split("\n")
            sequence_aligned = "no"
            confidence = "low"
            reasoning = ""

            for line in lines:
                line = line.strip()
                if line.upper().startswith("SEQUENCE_ALIGNED:"):
                    sequence_aligned = line.split(":", 1)[1].strip().lower()
                elif line.upper().startswith("CONFIDENCE:"):
                    confidence = line.split(":", 1)[1].strip().lower()
                elif line.upper().startswith("REASONING:"):
                    reasoning = line.split(":", 1)[1].strip()

            is_aligned = (
                sequence_aligned in ("yes", "partial")
                and confidence in ("high", "medium")
            )

            return AlignmentResult(
                is_aligned=is_aligned,
                predicted_element=None,  # N/A for trajectories
                expected_element=None,
                confidence=confidence,
                reasoning=reasoning,
                raw_response=result.content,
            )

        except Exception as e:
            logger.error(f"Trajectory alignment check failed: {e}")
            return AlignmentResult(
                is_aligned=False,
                predicted_element=None,
                expected_element=None,
                confidence="low",
                reasoning=f"Trajectory alignment check failed: {e}",
            )

    async def validate_batch(
        self,
        candidates: list[tuple[str, int]],  # (instruction, expected_mark)
        elements: list[dict],
    ) -> list[tuple[str, AlignmentResult]]:
        """Validate a batch of instruction candidates.

        Args:
            candidates: List of (instruction, expected_mark) tuples
            elements: Visible UI elements

        Returns:
            List of (instruction, AlignmentResult) tuples
        """
        import asyncio

        async def check_one(instruction: str, expected_mark: int):
            result = await self.check_alignment(instruction, elements, expected_mark)
            return (instruction, result)

        tasks = [check_one(inst, mark) for inst, mark in candidates]
        return await asyncio.gather(*tasks)


class VLMAlignmentValidator:
    """Visual alignment validation using VLM (if available).

    Uses a Vision-Language Model to verify that instructions
    correctly reference visible UI elements in a screenshot.

    This provides stronger visual grounding verification than
    text-only alignment checking.
    """

    def __init__(self, vlm_endpoint: Optional[str] = None):
        """Initialize VLM validator.

        Args:
            vlm_endpoint: Endpoint for VLM inference (optional)
        """
        self.vlm_endpoint = vlm_endpoint
        self._available = None

    async def is_available(self) -> bool:
        """Check if VLM is available for validation."""
        if self._available is not None:
            return self._available

        # Check for VLM endpoint availability
        if self.vlm_endpoint:
            try:
                import httpx
                async with httpx.AsyncClient() as client:
                    r = await client.get(f"{self.vlm_endpoint}/health", timeout=5)
                    self._available = r.status_code == 200
            except Exception:
                self._available = False
        else:
            self._available = False

        return self._available

    async def check_visual_alignment(
        self,
        instruction: str,
        screenshot_path: str,
        expected_bbox: list[float],  # [x1, y1, x2, y2] normalized
    ) -> AlignmentResult:
        """Check if instruction aligns with visual element in screenshot.

        Args:
            instruction: The natural language instruction
            screenshot_path: Path to screenshot image
            expected_bbox: Expected bounding box [x1, y1, x2, y2]

        Returns:
            AlignmentResult with visual alignment status
        """
        if not await self.is_available():
            logger.warning("VLM not available, skipping visual alignment check")
            return AlignmentResult(
                is_aligned=True,  # Pass through if VLM unavailable
                predicted_element=None,
                expected_element=None,
                confidence="low",
                reasoning="VLM not available for visual validation",
            )

        # TODO: Implement VLM-based visual grounding check
        # This would:
        # 1. Send instruction + screenshot to VLM
        # 2. Ask VLM to identify the target element
        # 3. Compare predicted bbox with expected bbox
        # 4. Return alignment result

        logger.info("VLM visual alignment check not yet implemented")
        return AlignmentResult(
            is_aligned=True,
            predicted_element=None,
            expected_element=None,
            confidence="medium",
            reasoning="VLM visual alignment check pending implementation",
        )
