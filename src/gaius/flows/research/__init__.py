"""Research Flow Package - SOTA deep research with MemRL.

Implements multi-pass research with Q-value learning on episodic memory:
- Two-phase retrieval (semantic filter -> Q-value ranking)
- 7-agent swarm for perspective diversity
- Drift-based convergence detection
- KB-embedded memory with zettelkasten frontmatter

Guru Meditation Codes:
- #RF.00000001.MEMRETRIEVE: Memory retrieval failed
- #RF.00000002.SWARMFAIL: Swarm agent execution failed
- #RF.00000003.GROKFAIL: XAI API error
- #RF.00000004.EVALFAIL: Reward computation failed
- #RF.00000005.QUPDATE: Q-value update failed
- #RF.00000006.CONVERGEFAIL: Convergence check failed
- #RF.00000007.FLOWFAIL: Metaflow execution failed
- #RF.00000008.BM25FAIL: BM25 search failed
- #RF.00000009.VECSEARCHFAIL: Vector search failed
- #RF.00000010.WEBSEARCHFAIL: Web search failed
- #RF.00000011.FINALSYNTHFAIL: Final Grok synthesis failed
- #RF.00000012.LLMSCOREFAIL: LLM scoring failed
- #RF.00000013.FRONTMATTERFAIL: YAML frontmatter parsing failed
- #RF.00000014.MEMORYPARSEFAIL: Research memory parsing failed
"""

from __future__ import annotations


class ResearchError(Exception):
    """Base exception for ResearchFlow failures.

    All errors include:
    - Guru Meditation code for debugging
    - Remediation hint for user
    """

    def __init__(self, message: str, guru_code: str, hint: str = ""):
        self.guru_code = guru_code
        self.hint = hint
        full_msg = f"{message}\n  Guru Meditation: {guru_code}"
        if hint:
            full_msg += f"\n  Try: {hint}"
        super().__init__(full_msg)


class RewardError(ResearchError):
    """Reward computation failed."""

    pass


class MemoryError(ResearchError):
    """Memory retrieval/storage failed."""

    pass


class SearchError(ResearchError):
    """Search (BM25/Vector/Web) failed."""

    pass


class SynthesisError(ResearchError):
    """LLM synthesis (swarm/Grok) failed."""

    pass


__all__ = [
    "ResearchFlow",
    "ResearchMemory",
    "RewardComponents",
    "ConvergenceTracker",
    # Exceptions
    "ResearchError",
    "RewardError",
    "MemoryError",
    "SearchError",
    "SynthesisError",
]


def __getattr__(name: str):
    """Lazy import to avoid circular dependencies."""
    if name == "ResearchFlow":
        from .flow import ResearchFlow

        return ResearchFlow
    if name == "ResearchMemory":
        from .memory import ResearchMemory

        return ResearchMemory
    if name == "RewardComponents":
        from .reward import RewardComponents

        return RewardComponents
    if name == "ConvergenceTracker":
        from .convergence import ConvergenceTracker

        return ConvergenceTracker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
