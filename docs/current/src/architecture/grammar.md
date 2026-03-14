# Grammar Engine

The grammar engine implements a CFDG-inspired recursive expansion system that generates unique 3D scenes from card topology features. It lives in `gaius.viz.grammar` and produces a flat list of positioned shapes that the [LuxCore renderer](./luxcore.md) assembles into scenes.

## Design Principles

From Context Free Design Grammars (Horigan, 2004), the engine borrows three key ideas:

1. **Weighted rule alternatives** -- at each expansion step, the grammar chooses among productions with probabilities derived from the card's feature vector. This is what makes different cards produce different structures.

2. **Recursive expansion with transform accumulation** -- each production can invoke sub-rules with a child transform (translation, rotation, scale) relative to the parent. Transforms compose multiplicatively, producing self-similar structures at decreasing scales.

3. **Termination by minimum scale** -- expansion stops when accumulated scale drops below `MIN_SCALE` (0.08) or when the shape budget (`MAX_SHAPES` = 35) is exhausted.

## Deterministic Seeding

Every card produces the same visualization regardless of when or where it is rendered:

```python
seed = int(hashlib.sha256(card_id.encode()).hexdigest(), 16) % (2**32)
rng = random.Random(seed)
```

## Feature-to-Rule Mapping

Card topology features control rule weights and recursion depth:

| Feature | Grammar Effect |
|---------|---------------|
| curvature | Petal count, recurse-vs-stop weight, dome factor |
| persistence | Max depth (3-7), shell nesting weight, spiral count |
| complexity | Branch-vs-grow weight, surface segments |
| boundary | Emission strength, volume density, core radius |
| b1 | Number of toroidal rings (0-3) |
| b2 | Number of void chambers (0-2) |
| diagram | Filament count, scale, and z-position |
| card_index | Phase offset for rotational variety in collection |

## Shape Primitives

The grammar produces six shape types, all implemented as arbitrary meshes in `meshgen.py` (not geometric primitives):

- **Petals** -- flower-like disk segments arranged in clusters
- **Shells** -- nested recursive enclosures
- **Tori** -- toroidal glass rings driven by H1 (1-cycles)
- **Voids** -- inverted-normal spheres representing H2 (2-cycles)
- **Filaments** -- thin structures whose scale encodes persistence interval lifetime
- **Core** -- central anchor shape

## Arrangement Modes

The root-level grammar selects one of three arrangement modes:

- **Cluster** -- radial arrangement around a center point
- **Spiral** -- logarithmic spiral placement
- **Branches** -- tree-like recursive branching

The arrangement mode is selected probabilistically based on the card's curvature and complexity features.

## Extensibility

Adding a new shape primitive requires three changes:

1. A mesh generator function in `meshgen.py`: `(parameters) -> (vertices, faces)`
2. A shape constant in `grammar.py`
3. A renderer case in `luxcore_renderer.py`

The grammar and renderer are agnostic to the geometry they receive -- any mesh generator that returns numpy vertex and face arrays works.

## Future Directions

The grammar is currently expressed as Python functions with hardcoded rule structures. A text-based grammar format (closer to CFDG's declarative syntax) would allow grammar definitions to be version-controlled and iterated without modifying Python code.
