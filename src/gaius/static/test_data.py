"""Static test data for UI development without live agents."""

import random
from datetime import datetime, timedelta
from typing import Any

# Seed for reproducible test data
random.seed(42)

# Grid state - typed separately for proper type inference
_black_stones: set[tuple[int, int]] = {(3, 3), (15, 15), (10, 10), (4, 16), (16, 4)}
_white_stones: set[tuple[int, int]] = {(4, 4), (14, 14), (9, 9), (3, 15), (15, 3)}
_allocations: list[list[int]] = [[random.randint(0, 100) for _ in range(19)] for _ in range(19)]

GRID_DATA: dict[str, Any] = {
    "black": _black_stones,
    "white": _white_stones,
    "alloc": _allocations,
}

# Agent state with positions and last utterances
AGENT_DATA = [
    {
        "name": "Leader",
        "role": "Strategic oversight",
        "color": "red",
        "pos": (10, 10),
        "last": "Recommend defensive posture in current market conditions. "
                "Liquidity reserves should be maintained at 15% minimum.",
    },
    {
        "name": "Risk",
        "role": "Threat identification",
        "color": "green",
        "pos": (5, 5),
        "last": "Elevated risk detected in emerging market exposure. "
                "Correlation spike between EM debt and commodity prices.",
    },
    {
        "name": "Optimizer",
        "role": "Opportunity seeking",
        "color": "blue",
        "pos": (14, 8),
        "last": "Rebalancing opportunity: shift 3% from fixed income to "
                "infrastructure. Expected Sharpe improvement: 0.12.",
    },
    {
        "name": "Planner",
        "role": "Long-term trajectory",
        "color": "yellow",
        "pos": (8, 14),
        "last": "5-year liability matching on track. Consider extending "
                "duration in Q2 when rates stabilize.",
    },
    {
        "name": "Critic",
        "role": "Assumption challenging",
        "color": "magenta",
        "pos": (12, 4),
        "last": "Optimizer's infrastructure thesis assumes stable regulatory "
                "environment. Political risk underweighted.",
    },
    {
        "name": "Executor",
        "role": "Action simulation",
        "color": "cyan",
        "pos": (6, 12),
        "last": "Simulated rebalancing: 2.3 days to execute at current volumes. "
                "Market impact: 12bps estimated.",
    },
    {
        "name": "Adversary",
        "role": "Plan breaking",
        "color": "white",
        "pos": (16, 16),
        "last": "Stress test: simultaneous EM crisis + rate spike. "
                "Current allocation fails liquidity test by 8%.",
    },
]

# File tree structure
FILE_TREE = {
    "current": {
        "projects": {
            "gaius": ["README.md", "CLAUDE.md", "pyproject.toml"],
            "pension-model": ["model.py", "data/", "reports/"],
        },
        "content": {
            "domains": ["pension.md", "supply-chain.md"],
            "references": ["tda-intro.pdf", "bloomberg-guide.md"],
        },
    },
    "scratch": {
        "2025-11-28": [
            "1732816800.md",  # Morning notes
            "1732831200.md",  # Afternoon session
        ],
        "2025-11-27": [
            "1732730400.md",
            "1732744800.md",
        ],
    },
    "archive": {
        "2025Q3": {
            "projects": ["q3-review/"],
            "attachments": ["chart1.png", "report.pdf"],
        },
    },
}

# Death loops (H1 features) as bounding boxes (x1, y1, x2, y2)
DEATH_LOOPS = [
    (4, 4, 7, 7),      # Small loop near corner
    (12, 11, 15, 14),  # Larger loop in center-right
    (2, 14, 5, 17),    # Loop in top-left
]

# Sample content for files
FILE_CONTENTS = {
    "/scratch/2025-11-28/1732816800.md": """# Morning Session

## Objective
Review Q4 allocation strategy in light of recent volatility.

## Notes
- Risk agent flagged correlation spike
- Optimizer suggests infrastructure tilt
- Need to reconcile with Critic's regulatory concerns

## Links
- [[pension-model]] - current model
- [[2025-11-27/1732744800]] - yesterday's analysis
""",
    "/scratch/2025-11-28/1732831200.md": """# Afternoon Session

## Swarm Round Results

Leader recommended defensive posture. Key points:
1. Maintain 15% liquidity buffer
2. Defer EM rebalancing until Q1
3. Monitor rate trajectory

## Action Items
- [ ] Run stress test with Adversary parameters
- [ ] Update liability model with new mortality tables
- [x] Document swarm consensus
""",
}

# TDA metrics
TDA_METRICS = {
    "entropy": 2.847,
    "h0_count": 12,  # Connected components
    "h1_count": 3,   # Loops (death loops)
    "h2_count": 1,   # Voids
    "persistence_range": (0.12, 0.89),
}

# Mini-grid projections (9x9 each, relative to cursor)
def get_minigrid_data(cursor_x: int, cursor_y: int) -> dict:
    """Generate mini-grid data based on cursor position."""
    # Top mini-grid: H1/H2 density around cursor
    top_grid = [[0.0] * 9 for _ in range(9)]
    for dx in range(9):
        for dy in range(9):
            # Simulate H1 density with some structure
            dist = ((dx - 4) ** 2 + (dy - 4) ** 2) ** 0.5
            top_grid[dy][dx] = max(0, 1 - dist / 6) * random.uniform(0.5, 1.0)

    # Right mini-grid: Embedding neighborhood
    right_grid = [[0.0] * 9 for _ in range(9)]
    for agent in AGENT_DATA:
        pos: tuple[int, int] = agent["pos"]  # type: ignore[assignment] - AGENT_DATA has pos as tuple
        ax, ay = pos
        # Map agent position relative to cursor into 9x9
        rx = 4 + (ax - cursor_x) // 2
        ry = 4 + (ay - cursor_y) // 2
        if 0 <= rx < 9 and 0 <= ry < 9:
            right_grid[ry][rx] = 1.0

    # Bottom mini-grid: Temporal (last 9 time steps)
    bottom_grid = [[random.uniform(0, 0.5)] * 9 for _ in range(9)]
    # Add trend line
    for t in range(9):
        bottom_grid[4][t] = 0.3 + t * 0.05 + random.uniform(-0.1, 0.1)

    return {
        "top": top_grid,
        "right": right_grid,
        "bottom": bottom_grid,
    }


# Semantic position hints based on UMAP projection topology
# These hints describe the Knowledge Gradient interpretation of grid regions
POSITION_HINTS = {
    (3, 3): "Corner: Low-density region, potential exploration target",
    (10, 10): "Center: High-information density cluster (tengen)",
    (9, 9): "Center: Central cluster, high document convergence",
    (16, 16): "Corner: Sparse region, high uncertainty",
    (3, 16): "Edge: Semantic boundary, potential H1 cycle",
    (16, 3): "Edge: Transition zone, negative curvature",
}


def get_position_hint(x: int, y: int) -> str:
    """Get contextual hint for grid position.

    Hints describe the topological/semantic interpretation of the position
    within the UMAP projection space, using Knowledge Gradient framing.
    """
    # Check exact matches
    if (x, y) in POSITION_HINTS:
        return POSITION_HINTS[(x, y)]

    # Generate based on region (topological interpretation)
    if x < 6 and y < 6:
        return "Lower-left quadrant: Sparse embedding region, high exploration value"
    elif x > 12 and y > 12:
        return "Upper-right quadrant: Sparse region, potential knowledge gap"
    elif x < 6 and y > 12:
        return "Upper-left quadrant: Semantic periphery, boundary candidate"
    elif x > 12 and y < 6:
        return "Lower-right quadrant: Semantic periphery, exploration target"
    else:
        return "Central region: High-density knowledge cluster"
