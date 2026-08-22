# HX catalog is Polarisfork

Gaius `get_catalog()` uses Iceberg REST at
`http://127.0.0.1:8181/api/catalog` (catalog `signals`, warehouse
`s3://signals-dataproducts/iceberg`). SqlCatalog is tests-only.

Polarisfork is `signals-polaris.service` on `signals.target`, not a
Gaius process. `#HX.00000002.NOPOLARIS` if `:8181` is down.
