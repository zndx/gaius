"""CFDG-inspired recursive procedural grammar for card visualizations.

Generates a flat list of (shape_type, transform) tuples from card topology
features. No rendering dependencies -- this module is pure Python + stdlib.

The grammar borrows core ideas from Context Free Design Grammars:
  - Weighted rule alternatives (probabilistic choice)
  - Recursive expansion with transform accumulation
  - Termination by minimum scale
  - Seeded RNG for reproducible-but-unique results per card

Card topology features control rule weights, so different cards produce
genuinely different recursive structures.
"""

from __future__ import annotations

import hashlib
import math
import random

# Shape type constants (grammar primitives)
PETAL = "petal"
SHELL = "shell"
TORUS = "torus"
VOID = "void"
FILAMENT = "filament"
CORE = "core"

# Expansion limits
MIN_SCALE = 0.08
MAX_SHAPES = 35


def weighted_choice(alternatives: list[tuple[float, object]], rng: random.Random) -> object:
    """Pick from [(weight, value), ...] proportional to weights."""
    total = sum(w for w, _ in alternatives)
    if total <= 0:
        return alternatives[-1][1]
    r = rng.random() * total
    cumulative = 0.0
    for weight, value in alternatives:
        cumulative += weight
        if r <= cumulative:
            return value
    return alternatives[-1][1]


def xf_child(
    parent: dict,
    dx: float = 0,
    dy: float = 0,
    dz: float = 0,
    drx: float = 0,
    dry: float = 0,
    drz: float = 0,
    dscale: float = 1.0,
) -> dict:
    """Create child transform: offsets in parent scale, rotations additive."""
    return {
        "x": parent["x"] + dx * parent["scale"],
        "y": parent["y"] + dy * parent["scale"],
        "z": parent["z"] + dz * parent["scale"],
        "rx": parent["rx"] + drx,
        "ry": parent["ry"] + dry,
        "rz": parent["rz"] + drz,
        "scale": parent["scale"] * dscale,
        "depth": parent["depth"] + 1,
    }


def xf_root() -> dict:
    """Root transform at origin, unit scale."""
    return {"x": 0, "y": 0, "z": 0, "rx": 0, "ry": 0, "rz": 0,
            "scale": 1.0, "depth": 0}


def expand_grammar(data: dict) -> list[tuple[str, dict]]:
    """Expand the CFDG-inspired grammar into a flat shape list.

    Returns list of (shape_type, transform_dict) tuples.
    Card features control rule weights -- different cards diverge.
    hash(card_id) seeds the RNG -- same card always reproduces.
    """
    curvature = data.get("curvature", 0.5)
    persistence = data.get("persistence", 0.5)
    complexity = data.get("complexity", 0.5)
    b1 = data.get("b1", 0)
    b2 = data.get("b2", 0)
    card_index = data.get("card_index", 0)
    collection_size = max(data.get("collection_size", 1), 1)

    # Deterministic seed: hashlib instead of hash() which is randomized per-process
    card_id = data.get("card_id", "default")
    seed = int(hashlib.sha256(card_id.encode()).hexdigest(), 16) % (2**63)
    rng = random.Random(seed)

    # Phase offset -- cards in same collection get rotational variety
    phase = (2 * math.pi * card_index) / collection_size

    # Max recursion depth driven by persistence (3-7)
    max_depth = 3 + int(persistence * 4)

    shapes: list[tuple[str, dict]] = []

    def _can_expand(xf: dict) -> bool:
        return (len(shapes) < MAX_SHAPES
                and xf["scale"] >= MIN_SCALE
                and xf["depth"] <= max_depth)

    # -- Rule: petal -------------------------------------------------------
    def rule_petal(xf: dict) -> None:
        """Petal with recursive sub-petals or branching."""
        if not _can_expand(xf):
            return
        shapes.append((PETAL, xf))

        action = weighted_choice([
            (15 + curvature * 10, "recurse"),
            (5, "stop"),
            (2 + complexity * 3, "branch"),
        ], rng)

        if action == "recurse":
            shrink = rng.uniform(0.6, 0.82)
            child = xf_child(xf,
                dy=rng.uniform(0.1, 0.3),
                dz=rng.gauss(0, 0.03),
                drx=rng.gauss(0, 0.15),
                drz=rng.gauss(0, 0.4),
                dscale=shrink,
            )
            rule_petal(child)
        elif action == "branch":
            for sign in (-1, 1):
                child = xf_child(xf,
                    dy=rng.uniform(0.08, 0.18),
                    drz=sign * rng.uniform(0.3, 0.8),
                    dscale=rng.uniform(0.5, 0.7),
                )
                rule_petal(child)

    # -- Rule: shell -------------------------------------------------------
    def rule_shell(xf: dict) -> None:
        """Nested glass shell with possible recursion."""
        if not _can_expand(xf):
            return
        shapes.append((SHELL, xf))

        action = weighted_choice([
            (8 + persistence * 12, "nest"),
            (5, "stop"),
        ], rng)

        if action == "nest":
            child = xf_child(xf, dscale=rng.uniform(0.55, 0.75))
            rule_shell(child)

    # -- Rule: branch ------------------------------------------------------
    def rule_branch(xf: dict) -> None:
        """Branching structure that spawns petals."""
        if not _can_expand(xf):
            return
        shapes.append((PETAL, xf))

        action = weighted_choice([
            (12, "grow"),
            (3 + complexity * 4, "fork"),
            (2, "stop"),
        ], rng)

        if action == "grow":
            child = xf_child(xf,
                dy=rng.uniform(0.15, 0.3),
                drz=rng.gauss(0, 0.1),
                dscale=rng.uniform(0.82, 0.93),
            )
            rule_branch(child)
        elif action == "fork":
            for sign in (-1, 1):
                child = xf_child(xf,
                    dy=rng.uniform(0.1, 0.2),
                    drz=sign * rng.uniform(0.3, 0.7),
                    dscale=rng.uniform(0.55, 0.72),
                )
                rule_branch(child)

    # -- Rule: manifold (root) ---------------------------------------------
    def rule_manifold(xf: dict) -> None:
        """Root rule: overall structure arrangement."""
        # Always: plasma core
        shapes.append((CORE, xf))

        # Choose arrangement style
        arrangement = weighted_choice([
            (10, "cluster"),
            (5 + persistence * 10, "spiral"),
            (3 + complexity * 5, "branches"),
        ], rng)

        if arrangement == "cluster":
            # Flower-like cluster: petals fan outward with tilt
            n = 5 + int(curvature * 5)
            for i in range(n):
                angle = phase + (2 * math.pi * i) / n + rng.gauss(0, 0.15)
                # Three layers like old code: inner/middle/outer
                layer = i % 3
                dist = 0.08 + layer * 0.1 + rng.uniform(0, 0.05)
                # Outward tilt -- the signature flower-petal spread
                tilt = math.pi / 5 + layer * 0.2 + rng.gauss(0, 0.12)
                child = xf_child(xf,
                    dx=dist * math.cos(angle),
                    dy=dist * math.sin(angle),
                    dz=rng.gauss(0, 0.03) - 0.03 * layer,
                    drx=tilt * math.cos(angle + 0.3),
                    dry=tilt * math.sin(angle + 0.3),
                    drz=angle + math.pi / 7 + rng.gauss(0, 0.2),
                    dscale=rng.uniform(0.55, 0.85),
                )
                rule_petal(child)

        elif arrangement == "spiral":
            # Fibonacci-like spiral outward
            n = 4 + int(persistence * 4)
            for i in range(n):
                t = i / max(n - 1, 1)
                angle = phase + t * math.pi * (2 + curvature * 2)
                dist = 0.06 + t * 0.18
                tilt = math.pi / 5 + t * 0.4
                child = xf_child(xf,
                    dx=dist * math.cos(angle),
                    dy=dist * math.sin(angle),
                    dz=t * 0.08 - 0.04,
                    drx=tilt * math.cos(angle),
                    dry=tilt * math.sin(angle),
                    drz=angle,
                    dscale=0.8 - t * 0.25,
                )
                rule_petal(child)

        else:  # branches
            n_branches = 2 + int(complexity * 2)
            for i in range(n_branches):
                angle = phase + (2 * math.pi * i) / n_branches
                child = xf_child(xf,
                    drx=math.pi / 5 + rng.uniform(0, 0.3),
                    drz=angle,
                    dscale=rng.uniform(0.6, 0.8),
                )
                rule_branch(child)

        # Shell wrapping (persistence-driven)
        if persistence > 0.15:
            shell_xf = xf_child(xf, dscale=0.45 + persistence * 0.15)
            rule_shell(shell_xf)

        # Ribbons (b1-driven)
        for i in range(min(b1, 3)):
            angle = phase + rng.uniform(0, 2 * math.pi)
            tilt = rng.uniform(math.pi / 6, math.pi / 2)
            shapes.append((TORUS, xf_child(xf,
                drx=tilt * math.cos(angle),
                dry=tilt * math.sin(angle),
                drz=angle,
                dscale=rng.uniform(0.8, 1.2),
            )))

        # Voids (b2-driven)
        for i in range(min(b2, 2)):
            angle = phase + rng.uniform(0, 2 * math.pi)
            dist = rng.uniform(0.2, 0.4)
            shapes.append((VOID, xf_child(xf,
                dx=dist * math.cos(angle),
                dy=dist * math.sin(angle),
                dz=rng.gauss(0, 0.05),
                dscale=rng.uniform(0.3, 0.6),
            )))

        # Filaments from persistence diagram
        diagram = data.get("persistence_diagram", [])
        for i, interval in enumerate(diagram[:6]):
            if len(interval) < 2:
                continue
            birth, death = interval[0], interval[1]
            lifetime = death - birth
            if lifetime < 0.05:
                continue
            angle = phase + (2 * math.pi * i) / max(len(diagram[:6]), 1)
            shapes.append((FILAMENT, xf_child(xf,
                dx=0.25 * math.cos(angle),
                dy=0.25 * math.sin(angle),
                dz=birth - 0.5,
                drx=rng.uniform(0.3, 1.0),
                dry=rng.uniform(0, 0.5),
                drz=angle,
                dscale=max(0.2, lifetime * 2),
            )))

    # Expand from root
    rule_manifold(xf_root())

    return shapes
