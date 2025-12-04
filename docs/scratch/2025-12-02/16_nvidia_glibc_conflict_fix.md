# NVIDIA/glibc Conflict Fix

**Date:** 2025-12-03
**Status:** Fixed

## Problem

Adding `/usr/lib/x86_64-linux-gnu` to `LD_LIBRARY_PATH` in `devenv.nix` caused Nix binaries to crash with glibc version errors:

```
mktemp: /usr/lib/x86_64-linux-gnu/libc.so.6: version `GLIBC_2.38' not found
mkdir: /usr/lib/x86_64-linux-gnu/libc.so.6: version `GLIBC_2.38' not found
```

**Root cause:** Nix binaries expect GLIBC 2.38+ from Nix store, but were finding the older system glibc first in LD_LIBRARY_PATH.

## Solution

Created `.devenv/nvidia-libs/` with symlinks to **only** NVIDIA driver libraries, avoiding system glibc:

```bash
.devenv/nvidia-libs/
├── libcuda.so* → /usr/lib/x86_64-linux-gnu/libcuda.so*
└── libnvidia-*.so* → /usr/lib/x86_64-linux-gnu/libnvidia-*.so*
```

Updated `devenv.nix` to use this directory instead of the full system path:

```nix
env.LD_LIBRARY_PATH = lib.concatStringsSep ":" [
  (lib.makeLibraryPath [
    pkgs.zlib
    pkgs.stdenv.cc.cc.lib
  ])
  # NVIDIA drivers only (no glibc!)
  "${config.devenv.root}/.devenv/nvidia-libs"
  "/usr/local/cuda/lib64"
  "/usr/local/cuda/extras/CUPTI/lib64"
];
```

## Setup

Run `.devenv/setup-nvidia-libs.sh` to regenerate symlinks after NVIDIA driver updates.

## Testing

After restarting shell:

```bash
# Should show no glibc errors
devenv shell

# Should see 6 GPUs
uv run python -c "import torch; print(torch.cuda.device_count())"
```

## Why This Works

- Only NVIDIA-specific `.so` files are symlinked
- System `libc.so.6` is NOT included
- Nix binaries use their own glibc from `/nix/store/`
- PyTorch/vLLM find CUDA drivers in `.devenv/nvidia-libs/`
- No version conflicts!
