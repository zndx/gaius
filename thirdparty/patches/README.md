# Local patches to thirdparty submodules

These patches live in submodule working trees and are NOT committed to the
submodules (no writable upstream). Re-apply after any submodule re-checkout:

```bash
cd thirdparty/src/LuxCore
git apply ../../patches/luxcore-make-deps-ld-library-path.patch
```

| Patch | Target | Purpose |
|-------|--------|---------|
| `luxcore-make-deps-ld-library-path.patch` | LuxCore `build-helpers/make/make_deps.py` | Strip Nix gcc libstdc++ from LD_LIBRARY_PATH in conan subprocesses — host binaries (dpkg-query, apt-get) crash with "GLIBC_2.38 not found" otherwise |
