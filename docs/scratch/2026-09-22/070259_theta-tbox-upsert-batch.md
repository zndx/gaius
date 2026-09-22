# Theta W38 retry: YK floor held, TBox upsert did not

The retry `theta_w38_retry_20260922` (task 53893, Metaflow 7493) was admitted on `root.internal.inference.light` with floor 1 after agent-rtc's guarantee dropped to 0. Encode then failed inside `materialize_tbox`: one upsert of 905 ColBERT multivectors is ~45MiB, and Qdrant rejects bodies over 32MiB. The collection `sdg_tbox` was left existing and empty. Infer saw no class groundings and reported `#THETA.00000011.NOPAIRS`, which hid the upsert error.

`upsert_in_batches` writes 64 points at a time. An empty or short collection is not treated as a ready index.
