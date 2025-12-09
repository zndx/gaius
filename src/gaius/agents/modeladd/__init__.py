"""Agent-orchestrated model addition workflow.

This package provides the ModelAddOrchestrator that uses Orchestrator-8B
to coordinate the model addition workflow via tool calls.

Usage:
    from gaius.agents.modeladd import ModelAddOrchestrator

    orchestrator = ModelAddOrchestrator()
    result = await orchestrator.run("mistralai/Mistral-7B-Instruct-v0.3")
"""

from .orchestrator import ModelAddOrchestrator

__all__ = ["ModelAddOrchestrator"]
