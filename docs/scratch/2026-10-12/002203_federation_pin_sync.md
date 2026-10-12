# Federation pin sync

`signals-protocol` trunk is `09e234a`. That merge puts the decisions
handover (`334bde3`) on the same commit as the OIP proto (`fa0c09e`).
Gaius pins that SHA. `gaius/dual-d3-flash` fast-forwards to it, so the
side branch is not a second pin.

`sdg-corpora` trunk is `0bba666f` (four CLT prefLabels, rebased onto
`924973ae`). Gaius pins that SHA.

Gaius trunk now pushes to `internal`, `share`, and the raid `origin`
mirror together. The LuxCore devenv patch, semantics Eclipse files,
`uv.lock`, and the two session logs stay uncommitted.

Still behind this trunk SHA, and not moved in this slice because their
trees have other uncommitted work: atelier `cb67c77`, aegir `3fcb820`,
synth `4433547`, metabase `99426c7`, oss-modin `5db2f9f`.
