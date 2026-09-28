"""A briefing card. Numbers come from the caller. This module does not fetch a market."""
from __future__ import annotations

from gaius.agents.market.catalog import OPTIONS_BLOCK, by_id


def narrative_card(
    *,
    view_id: str,
    finding: str,
    interpretation: str,
    counterevidence: str,
    implication: str,
    invalidation: str,
) -> dict[str, str]:
    view = by_id(view_id)
    if view is None:
        raise KeyError(view_id)
    if view.release == "options":
        raise ValueError(OPTIONS_BLOCK)
    return {
        "view": view.id,
        "question": view.question,
        "finding": finding.strip(),
        "interpretation": interpretation.strip(),
        "counterevidence": counterevidence.strip(),
        "implication": implication.strip(),
        "invalidation": invalidation.strip(),
    }


def render_briefing(cards: list[dict[str, str]]) -> str:
    """Markdown a session can file. Hicks owns the card; this is the body."""
    lines = [
        "# Market briefing",
        "",
        "Design of the card, not a claim about a session's market. "
        "Options are omitted until a quote adapter is verified.",
        "",
    ]
    for card in cards:
        lines.append(f"## {card['view']} ({card['question']})")
        lines.append(f"- Finding: {card['finding']}")
        lines.append(f"- Interpretation: {card['interpretation']}")
        lines.append(f"- Counterevidence: {card['counterevidence']}")
        lines.append(f"- Implication: {card['implication']}")
        lines.append(f"- Invalidation: {card['invalidation']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
