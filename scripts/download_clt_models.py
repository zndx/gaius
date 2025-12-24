#!/usr/bin/env python
"""Download CLT models from HuggingFace.

Downloads BluelightAI's Cross-Layer Transcoders for Qwen3, which provide
interpretable sparse features for circuit tracing and latent-space operations.

Run: uv run python scripts/download_clt_models.py

Models:
- Qwen/Qwen3-1.7B: Base language model (~3.5GB)
  Note: We use the non-Base variant because transformer_lens (used by circuit_tracer)
  only has Qwen/Qwen3-1.7B in its supported model list, not Qwen/Qwen3-1.7B-Base.
  The CLT transcoders work with either variant per BluelightAI docs.
- bluelightai/clt-qwen3-1.7b-base-20k: CLT transcoders (~1.5GB)
"""

import os
import sys

from huggingface_hub import snapshot_download


MODELS = [
    "Qwen/Qwen3-1.7B",  # transformer_lens compatible (not -Base)
    "bluelightai/clt-qwen3-1.7b-base-20k",
]


def main() -> int:
    """Download CLT models to HuggingFace cache."""
    cache_dir = os.environ.get("HF_HOME", "/raid/cache/huggingface")

    print(f"Downloading CLT models to: {cache_dir}")
    print()

    for model_id in MODELS:
        print(f"Downloading {model_id}...")
        try:
            path = snapshot_download(
                repo_id=model_id,
                cache_dir=cache_dir,
                local_dir_use_symlinks=True,
            )
            print(f"  -> {path}")
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            return 1

    print()
    print("All models downloaded successfully.")
    print()
    print("To verify, run:")
    print("  uv run python -c \"from circuit_tracer import ReplacementModel; print('OK')\"")

    return 0


if __name__ == "__main__":
    sys.exit(main())
