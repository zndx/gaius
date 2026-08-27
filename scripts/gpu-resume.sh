#!/usr/bin/env bash
# gpu-resume.sh — resume GPU workloads after a deferred (unclean-reboot) boot.
#
# gaius-engine.sh holds the baseline GPU workloads when crash-guard has dropped
# the defer marker. Once you've inspected the box and decided it's safe to run,
# this starts the baseline "thinking" endpoint (Qwen3-27B, TP=4, GPUs 0-3) and
# clears the marker ONLY if the start succeeds — so a failed resume re-defers on
# the next engine (re)start rather than looping.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MARKER="${GAIUS_DEFER_MARKER:-/var/lib/gaius/defer-gpu}"

if [[ -f "$MARKER" ]]; then
  echo "gpu-resume: defer marker present ($MARKER) — resuming baseline GPU workloads"
else
  echo "gpu-resume: no defer marker (not a deferred boot); starting baseline anyway"
fi

if uv run gaius-cli --cmd "/gpu start thinking"; then
  rm -f "$MARKER"
  echo "gpu-resume: thinking endpoint start requested; defer marker cleared"
  echo "gpu-resume: watch it reach HEALTHY with: uv run gaius-cli --cmd '/gpu status' --format json"
else
  echo "gpu-resume: '/gpu start thinking' FAILED — defer marker LEFT in place" >&2
  echo "gpu-resume: the engine will re-defer on its next (re)start until this succeeds" >&2
  exit 1
fi
