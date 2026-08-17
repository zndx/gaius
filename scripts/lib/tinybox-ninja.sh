#!/usr/bin/env bash
# Tinybox host ninja: must not see Nix libstdc++ (needs glibc 2.38).
# vLLM restores devenv LD_LIBRARY_PATH after exec; host ninja is a host ELF.
set -euo pipefail

REAL_NINJA="${TINYBOX_REAL_NINJA:-${HOME}/.local/bin/ninja}"
if [[ ! -x "$REAL_NINJA" ]]; then
  for c in /usr/bin/ninja /usr/local/bin/ninja; do
    if [[ -x "$c" ]]; then REAL_NINJA=$c; break; fi
  done
fi
if [[ ! -x "$REAL_NINJA" ]]; then
  echo "tinybox-ninja: host ninja missing (#EP.00000005.TINYBOXCUDA)" >&2
  exit 127
fi

HOST_LD="/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu:/usr/local/cuda/lib64"
if [[ -d /usr/local/cuda/extras/CUPTI/lib64 ]]; then
  HOST_LD="${HOST_LD}:/usr/local/cuda/extras/CUPTI/lib64"
fi
export LD_LIBRARY_PATH="$HOST_LD"
export PATH="/usr/bin:/bin:/usr/local/cuda/bin"
unset LD_PRELOAD || true
unset LIBRARY_PATH CPLUS_INCLUDE_PATH C_INCLUDE_PATH CPATH || true
unset NIX_CC NIX_CFLAGS_COMPILE NIX_LDFLAGS \
  NIX_CC_WRAPPER_TARGET_HOST_x86_64_unknown_linux_gnu || true

exec "$REAL_NINJA" "$@"
