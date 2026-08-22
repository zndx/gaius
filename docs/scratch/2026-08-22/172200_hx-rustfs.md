# HX on Signals RustFS

devenv MinIO (`:9014` `zndx-gaius`) is not a warehouse. HX and product
objects use RustFS `s3://signals-dataproducts/gaius/hx` (`:9010`).
Iceberg SQL catalog rows that pointed at `s3://zndx-gaius/hx` were
dropped so tables recreate on RustFS.
