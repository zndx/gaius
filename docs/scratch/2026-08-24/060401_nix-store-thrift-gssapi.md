# Nix store: only Thrift 0.22; shim kudu GSSAPI

Follow-up to `055703_hs2-gssapi-fdw-union.md`. Searched `/nix/store`:

- **Thrift:** Nix has `thrift-0.22.0` only. `libthrift-0.16.0.so` lives in the Impala toolchain, not Nix. That 0.16 link is what SIGSEGV'd OpenSession.
- **GSSAPI:** `libgssapi_krb5.so.2` is in `krb5-*-lib`. Toolchain `libkudu_client` NEEDED it but `.devenv/impala/lib` only shimmed `libsasl2.so.2`.
- FDW now uses **DT_RPATH** plus shims for gssapi/krb5/ssl. `ldd` without `LD_LIBRARY_PATH` resolves `libgssapi_krb5.so.2`. Build fails if Thrift 0.16 is linked.

FDW UNION + `INSERT` tier0 re-verified after the relink. Closed Kudu ranges still not dropped.
