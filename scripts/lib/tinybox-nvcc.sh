#!/usr/bin/env bash
# Tinybox host nvcc: CUDA 12.4 frontend (cicc/ptxas) must not see Nix libstdc++.
# Nix gcc-15 libstdc++ needs glibc 2.38; host Ubuntu 22.04 is 2.35.
# torch.utils.cpp_extension invokes $CUDA_HOME/bin/nvcc, not PATH.
set -euo pipefail

REAL_NVCC="${TINYBOX_REAL_NVCC:-/usr/local/cuda/bin/nvcc}"
if [[ ! -x "$REAL_NVCC" ]]; then
  echo "tinybox-nvcc: missing $REAL_NVCC (#EP.00000005.TINYBOXCUDA)" >&2
  exit 127
fi

export CC="${CC:-/usr/bin/gcc-11}"
export CXX="${CXX:-/usr/bin/g++-11}"
export CUDAHOSTCXX="${CUDAHOSTCXX:-/usr/bin/g++-11}"
export NVCC_PREPEND_FLAGS="${NVCC_PREPEND_FLAGS:--ccbin=/usr/bin/g++-11}"

HOST_LD="/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu:/usr/local/cuda/lib64"
if [[ -d /usr/local/cuda/extras/CUPTI/lib64 ]]; then
  HOST_LD="${HOST_LD}:/usr/local/cuda/extras/CUPTI/lib64"
fi
export LD_LIBRARY_PATH="$HOST_LD"
# Host-only PATH: parent devenv PATH has Nix binutils (`as`/`ld`) whose
# RUNPATH loses to this LD_LIBRARY_PATH and then dies on host glibc 2.35.
export PATH="/usr/bin:/bin:/usr/local/cuda/bin"
unset LD_PRELOAD || true
unset LIBRARY_PATH CPLUS_INCLUDE_PATH C_INCLUDE_PATH CPATH || true
unset NIX_CC NIX_CFLAGS_COMPILE NIX_LDFLAGS \
  NIX_CC_WRAPPER_TARGET_HOST_x86_64_unknown_linux_gnu || true

exec "$REAL_NVCC" "$@"
