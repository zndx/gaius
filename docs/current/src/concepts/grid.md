# The Grid Metaphor

## Origins in Go

The 19×19 grid traces its heritage to the ancient game of Go (围棋/囲碁/바둑). For over four millennia, this board has served as a substrate for strategic reasoning of remarkable depth.

Go's grid has properties that make it ideal for information visualization:

- **Discrete but dense**: 361 points offer fine granularity while remaining visually tractable
- **Symmetric**: No privileged positions (unlike chess's asymmetric opening)
- **Emergent structure**: Corners, edges, and center have different strategic character despite identical local rules
- **Scale-invariant patterns**: The same shapes (eyes, ladders, ko) appear at multiple scales

## The Grid as Projection Surface

In Gaius, the grid serves as a **projection surface** for high-dimensional data. Consider an embedding space with 1536 dimensions (typical for modern text embeddings). How do we make this legible?

```
High-dimensional space          The Grid
      (n=1536)                  (n=361)
         │                         │
         │    PCA / UMAP /         │
         │    custom projection    │
         ▼                         ▼
    ┌─────────┐              ┌───────────┐
    │ ● ● ●   │              │ · · ● · · │
    │   ●   ● │    ────►     │ · ● · · · │
    │ ●     ● │              │ · · · ● · │
    └─────────┘              └───────────┘
```

The projection is necessarily lossy. This is a feature: it forces salience. Points that survive projection and remain distinct are points that matter.

## Addressing

Every grid position has a unique address:

```
   A B C D E F G H J K L M N O P Q R S T
19 · · · · · · · · · · · · · · · · · · · 19
18 · · · · · · · · · · · · · · · · · · · 18
17 · · · + · · · · · · · · · + · · · · · 17
...
 1 · · · · · · · · · · · · · · · · · · ·  1
   A B C D E F G H J K L M N O P Q R S T
```

Note: Column I is skipped (Go convention, to avoid confusion with the numeral 1).

This addressing enables:
- **Precise reference**: "The cluster at D4-F6"
- **Command targeting**: `/analyze K10` or `/mark Q16 critical`
- **Spatial queries**: "What's near the center?" → J10-L10, J9-L11

## Visual Vocabulary

The grid supports a rich visual vocabulary:

### Point Markers
| Symbol | Meaning |
|--------|---------|
| `●` | Black stone / primary entity |
| `○` | White stone / secondary entity |
| `✛` | Cursor position |
| `a-i` | Candidate markers (yellow) |
| `◦` | Neutral / unaffiliated point |

### Density Shading
| Symbol | Density |
|--------|---------|
| `▓` | High (>75%) |
| `▒` | Medium (50-75%) |
| `░` | Low (20-50%) |
| `·` | Minimal (<20%) |

### Overlay Markers
| Symbol | Meaning |
|--------|---------|
| `⚠` | Death loop / H1 feature |
| Colored `●` | Agent position |

## The Grid as Strategic Map

In Go, professionals often describe the board in terms of strategic regions:
- **Corners** (4 points): High-value, easy to secure
- **Edges** (4 sides): Secondary value, harder to defend
- **Center**: Hardest to claim, but dominates late-game influence

Gaius inherits this intuition. Data projected to corners represents stable, well-understood entities. Central positions represent contested or ambiguous terrain. Edge regions represent transitional states.

## Compositional Thinking

The grid invites compositional reasoning:

- **Groups**: Connected points form units (liberty-counting in Go becomes cluster analysis)
- **Territory**: Regions bounded by your stones (areas of control/understanding)
- **Influence**: Distant effects from strong positions (attention propagation)
- **Ko**: Positions that oscillate (unstable equilibria in your data)

These metaphors aren't forced—they emerge naturally when complex systems are projected onto discrete spatial representations.

## Why Not a Larger Grid?

Larger grids (e.g., 100×100) would offer more resolution but sacrifice:
- **Gestalt perception**: Humans can't perceive 10,000 points holistically
- **Addressability**: 100×100 requires two-digit coordinates
- **Strategic depth**: Go on 9×9 is trivial; 19×19 is profound. Scale matters.

The 19×19 board occupies a cognitive sweet spot. Gaius exploits this.
