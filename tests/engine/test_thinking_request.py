"""Thinking-mode kwargs ride the vLLM payload."""

from __future__ import annotations

from pathlib import Path

from gaius.engine.backends.vllm_controller import VLLMRequest, _tinybox_cuda_compile_env


def test_vllm_request_thinking_defaults() -> None:
    req = VLLMRequest(messages=[{"role": "user", "content": "hi"}], model="Qwen/Qwen3.8-27B")
    assert req.enable_thinking is True
    assert req.preserve_thinking is True
    assert req.reasoning_effort == "xhigh"


def test_tinybox_cuda_compile_env_drops_nix_gcc() -> None:
    env = _tinybox_cuda_compile_env(
        {
            "PATH": (
                "/nix/store/aaa-gcc-wrapper-15.2.0/bin:"
                "/nix/store/wc7-ninja-1.13.2/bin:"
                "/repo/.devenv/state/venv/bin:"
                "/usr/bin"
            ),
            "LD_LIBRARY_PATH": (
                "/tmp/x/.devenv/profile/lib:"
                "/nix/store/bbb-gcc-15.2.0-lib/lib:"
                "/repo/.devenv/nvidia-libs:"
                "/usr/local/cuda/lib64"
            ),
            "NIX_CC": "/nix/store/aaa-gcc-wrapper-15.2.0",
            "CUDA_HOME": "",
        }
    )
    assert "gcc-wrapper" not in env["PATH"]
    assert "ninja-1.13.2" not in env["PATH"]
    assert "gcc-15" not in env["LD_LIBRARY_PATH"]
    assert "profile/lib" not in env["LD_LIBRARY_PATH"]
    assert "nvidia-libs" in env["LD_LIBRARY_PATH"]
    assert "/usr/lib/x86_64-linux-gnu" not in env["LD_LIBRARY_PATH"].split(":")
    assert "/lib/x86_64-linux-gnu" not in env["LD_LIBRARY_PATH"].split(":")
    assert "NIX_CC" not in env
    assert env["CUDA_HOME"].endswith(".devenv/tinybox-cuda")
    assert (Path(env["CUDA_HOME"]) / "bin" / "nvcc").is_file()
    assert env["NINJA"].endswith(".devenv/tinybox-cuda/bin/ninja")
    assert (Path(env["NINJA"])).is_file()
    assert "/repo/.devenv/state/venv/bin" in env["PATH"].split(":")
    assert "/usr/bin" in env["PATH"]
