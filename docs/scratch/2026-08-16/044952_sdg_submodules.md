# Local SDG pins: corpora + strategy

Gaius now vendors the two SHARE-tier SDG products Aegir publishes,
same path convention as Atelier / `external/signals-protocol`:

| submodule | remote | pin (this checkout) | why it is here |
|-----------|--------|---------------------|----------------|
| `external/sdg-corpora` | `zndx/sdg-corpora` `@trunk` | `b24ef9f6` (Aegir `corpora` HEAD) | SKOS vocabulary + realized OWL. Schema *terms*. |
| `external/sdg-strategy` | `zndx/sdg-strategy` `@trunk` | `562169c` (Aegir `strategy` HEAD) | Aperture spec: C, τ, 512-token grain, aiming SKOS. Schema *membrane*. |

```sh
git submodule update --init external/sdg-corpora external/sdg-strategy
```

Aegir remains the owner. Gaius consumes; it does not regenerate the
ontology or re-aim C. Missing checkout is `#SDG.00000001.NOCORPORA` /
`#SDG.00000003.NOSTRATEGY`.

The aperture specification lives at
`external/sdg-strategy/objective/tasks/aperture-selection-for-domain-harvesting.md`.
Registered operating point (this pin): threshold regime, `domain_tau=0.1`,
`colbert_token_limit=512`, `sdg_aperture` n=33.
