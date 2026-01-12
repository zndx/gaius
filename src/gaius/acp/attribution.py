"""Model attribution for ACP-generated GitHub content.

Maps ACP adapter commands to model attribution information for
dynamic credit in GitHub issues and other generated content.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelAttribution:
    """Attribution info for an AI model.

    Attributes:
        name: Display name (e.g., "Mistral")
        emoji: Brand emoji (e.g., "🌀")
        url: Optional link to model provider
    """

    name: str
    emoji: str
    url: str | None = None

    @property
    def full_line(self) -> str:
        """Full attribution line for GitHub issues."""
        base = f"{self.emoji} Analyzed by {self.name} (via Gaius ACP)"
        if self.url:
            return f"{base} | [{self.name}]({self.url})"
        return base


# Map adapter command prefixes to model attribution
MODEL_ATTRIBUTION_MAP: dict[str, ModelAttribution] = {
    "vibe-acp": ModelAttribution("Mistral", "🌀", "https://mistral.ai"),
    "claude-code": ModelAttribution("Claude", "🤖", "https://anthropic.com"),
    "claude": ModelAttribution("Claude", "🤖", "https://anthropic.com"),
    "codex": ModelAttribution("Codex", "🧠", "https://openai.com"),
    "ollama": ModelAttribution("Local LLM", "🏠", None),
    "llamafile": ModelAttribution("Local LLM", "🏠", None),
    "lmstudio": ModelAttribution("Local LLM", "🏠", None),
}

DEFAULT_ATTRIBUTION = ModelAttribution("AI Assistant", "🤖", None)


def get_model_attribution(agent_command: str | None) -> ModelAttribution:
    """Get model attribution based on ACP adapter command.

    Args:
        agent_command: The configured ACP agent command (e.g., "vibe-acp")

    Returns:
        ModelAttribution with name, emoji, and optional URL
    """
    if not agent_command:
        return DEFAULT_ATTRIBUTION

    # Normalize to basename if full path provided
    command = agent_command.split("/")[-1] if "/" in agent_command else agent_command

    # Check for exact match first
    if command in MODEL_ATTRIBUTION_MAP:
        return MODEL_ATTRIBUTION_MAP[command]

    # Check for prefix match (handles versioned commands like "vibe-acp-v2")
    for prefix, attribution in MODEL_ATTRIBUTION_MAP.items():
        if command.startswith(prefix):
            return attribution

    return DEFAULT_ATTRIBUTION
