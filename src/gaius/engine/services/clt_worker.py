"""CLT Worker - Subprocess for GPU-isolated CLT model inference.

This worker runs as a separate process with CUDA_VISIBLE_DEVICES set by CLTService
to isolate the CLT model from vLLM endpoints. GPU is dynamically allocated via
ResourceManager. Communication happens via JSON-RPC over stdin/stdout.

Usage (called by CLTService, not directly):
    CUDA_VISIBLE_DEVICES=<gpu_id> HF_HOME=/raid/cache/huggingface python -m gaius.engine.services.clt_worker

Protocol:
    Request:  {"method": "extract", "params": {"text": "...", "top_k": 115}}
    Response: {"result": {"features": [...], "count": ...}}

    Request:  {"method": "status"}
    Response: {"result": {"loaded": true, "model": "...", ...}}

    Request:  {"method": "shutdown"}
    Response: {"result": "ok"}
"""

import json
import logging
import os
import sys

# Suppress transformer_lens/circuit_tracer warnings
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# GPU is set by CLTService via CUDA_VISIBLE_DEVICES environment variable
# Do NOT set a default here - the caller is responsible for GPU allocation
gpu_id = os.environ.get("CUDA_VISIBLE_DEVICES", "")
if not gpu_id:
    # If no GPU specified, CLTService should have set one
    # Log warning but continue - CUDA will use GPU 0 by default
    import sys
    print("WARNING: CUDA_VISIBLE_DEVICES not set, using default GPU", file=sys.stderr)


def main() -> int:
    """Run CLT worker loop."""
    import contextlib
    import io

    # Log to stderr so stdout is reserved for JSON-RPC
    print(f"CLT Worker starting on GPU {os.environ.get('CUDA_VISIBLE_DEVICES', 'default')}", file=sys.stderr)

    model = None
    loaded = False

    def ensure_loaded():
        nonlocal model, loaded
        if not loaded:
            print("Loading CLT model...", file=sys.stderr)

            # CRITICAL: Redirect stdout during model loading because transformer_lens
            # prints "Loaded pretrained model..." directly to stdout, which pollutes
            # our JSON-RPC communication channel
            from gaius.models.clt import load_clt_model

            captured_stdout = io.StringIO()
            original_stdout = sys.stdout
            try:
                sys.stdout = captured_stdout
                # Device is "cuda" since CUDA_VISIBLE_DEVICES remaps to GPU 0
                model = load_clt_model(name="qwen3-1.7b", device="cuda")
            finally:
                sys.stdout = original_stdout

            # Log any captured output to stderr
            captured = captured_stdout.getvalue()
            if captured:
                print(f"Model loader output: {captured.strip()}", file=sys.stderr)

            loaded = True
            print("CLT model loaded", file=sys.stderr)
        return model

    def send_response(response: dict):
        """Send JSON response to stdout."""
        print(json.dumps(response), flush=True)

    def send_error(error: str, code: int = -1):
        """Send error response."""
        send_response({"error": {"code": code, "message": error}})

    # Process JSON-RPC requests from stdin
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as e:
            send_error(f"Invalid JSON: {e}")
            continue

        method = request.get("method", "")
        params = request.get("params", {})

        try:
            if method == "extract":
                text = params.get("text", "")
                top_k = params.get("top_k", 115)

                m = ensure_loaded()
                result = m.extract_features(text, top_k=top_k)

                # Convert features to JSON-serializable format
                features = [
                    {
                        "layer_idx": f.layer_idx,
                        "position": f.position,
                        "feature_idx": f.feature_idx,
                        "activation": f.activation,
                    }
                    for f in result.features
                ]

                send_response({
                    "result": {
                        "features": features,
                        "count": len(features),
                        "text_length": len(text),
                    }
                })

            elif method == "status":
                send_response({
                    "result": {
                        "loaded": loaded,
                        "model": "Qwen/Qwen3-1.7B" if loaded else None,
                        "gpu": os.environ.get("CUDA_VISIBLE_DEVICES", "default"),
                    }
                })

            elif method == "load":
                ensure_loaded()
                send_response({"result": "ok"})

            elif method == "shutdown":
                send_response({"result": "ok"})
                break

            else:
                send_error(f"Unknown method: {method}")

        except Exception as e:
            send_error(f"{type(e).__name__}: {e}")

    print("CLT Worker shutting down", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
