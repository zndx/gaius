#!/usr/bin/env bash
# systemd and devenv share one compose graph. pid 1 is never membership.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../scripts/lib/systemd-unit.sh
source "$ROOT/scripts/lib/systemd-unit.sh"

fail=0

if owned_by_compose 1; then
  echo "FAIL: pid 1 owned_by_compose"
  fail=1
else
  echo "OK: pid 1 not compose-owned"
fi

# Legacy dedicated runtime must not be required for membership.
export GAIUS_DEVENV_RUNTIME=/run/user/1001/gaius-systemd
if owned_by_compose 1; then
  echo "FAIL: pid 1 owned_by_compose with GAIUS_DEVENV_RUNTIME set"
  fail=1
else
  echo "OK: dedicated runtime does not make pid 1 ready"
fi
unset GAIUS_DEVENV_RUNTIME

exit "$fail"
