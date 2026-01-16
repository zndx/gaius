#!/usr/bin/env python3
"""
Test script to validate optillm + vLLM integration.

Prerequisites:
1. Start vLLM server (Terminal 1):
   vllm serve Qwen/Qwen2.5-Coder-32B-Instruct \
     --tensor-parallel-size 4 \
     --max-model-len 8192 \
     --port 8000

2. Start optillm proxy (Terminal 2):
   pip install optillm
   export OPENAI_API_KEY="sk-dummy"
   export OPTILLM_BASE_URL="http://localhost:8000/v1"
   optillm --port 8080

3. Run this script:
   uv run python scripts/test_optillm_vllm.py
"""

import os
import sys
import httpx
from openai import OpenAI

# Configuration from environment
VLLM_URL = os.getenv("GAIUS_VLLM_URL", "http://localhost:8088/v1").rstrip("/v1")
OPTILLM_URL = os.getenv("GAIUS_OPTILLM_URL", "http://localhost:8080/v1").rstrip("/v1")
OPTILLM_API_KEY = os.getenv("OPTILLM_API_KEY", "sk-optillm")


def check_vllm() -> bool:
    """Check if vLLM is running."""
    try:
        r = httpx.get(f"{VLLM_URL}/v1/models", timeout=5)
        if r.status_code == 200:
            models = r.json().get("data", [])
            print(f"[OK] vLLM running at {VLLM_URL}")
            for m in models:
                print(f"     Model: {m.get('id')}")
            return True
    except Exception as e:
        print(f"[FAIL] vLLM not responding at {VLLM_URL}: {e}")
    return False


def check_optillm() -> bool:
    """Check if optillm is running."""
    try:
        headers = {"Authorization": f"Bearer {OPTILLM_API_KEY}"}
        r = httpx.get(f"{OPTILLM_URL}/v1/models", headers=headers, timeout=5)
        if r.status_code == 200:
            print(f"[OK] optillm proxy running at {OPTILLM_URL}")
            return True
        else:
            print(f"[FAIL] optillm returned {r.status_code} at {OPTILLM_URL}")
    except Exception as e:
        print(f"[FAIL] optillm not responding at {OPTILLM_URL}: {e}")
    return False


def test_direct_vllm(model: str) -> bool:
    """Test direct vLLM completion (no optillm)."""
    print("\n--- Test: Direct vLLM completion ---")
    try:
        client = OpenAI(api_key="sk-dummy", base_url=f"{VLLM_URL}/v1")
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "What is 2+2? Answer briefly."}],
            max_tokens=50,
            temperature=0.1,
        )
        content = response.choices[0].message.content
        print(f"[OK] Direct vLLM response: {content[:100]}...")
        return True
    except Exception as e:
        print(f"[FAIL] Direct vLLM failed: {e}")
        return False


def test_optillm_passthrough(model: str) -> bool:
    """Test optillm passthrough (no technique)."""
    print("\n--- Test: optillm passthrough (no technique) ---")
    try:
        client = OpenAI(api_key=OPTILLM_API_KEY, base_url=f"{OPTILLM_URL}/v1")
        response = client.chat.completions.create(
            model=model,  # No technique prefix = passthrough
            messages=[{"role": "user", "content": "What is 3+3? Answer briefly."}],
            max_tokens=50,
            temperature=0.1,
        )
        content = response.choices[0].message.content
        print(f"[OK] optillm passthrough response: {content[:100]}...")
        return True
    except Exception as e:
        print(f"[FAIL] optillm passthrough failed: {e}")
        return False


def test_cot_reflection(model: str) -> bool:
    """Test Chain-of-Thought with Reflection technique."""
    print("\n--- Test: CoT Reflection technique ---")
    try:
        client = OpenAI(api_key=OPTILLM_API_KEY, base_url=f"{OPTILLM_URL}/v1")
        # Use cot_reflection prefix
        technique_model = f"cot_reflection-{model}"

        response = client.chat.completions.create(
            model=technique_model,
            messages=[
                {
                    "role": "user",
                    "content": "What are the prime factors of 84? Think step by step.",
                }
            ],
            max_tokens=500,
            temperature=0.7,
        )
        content = response.choices[0].message.content

        # Check for thinking/reflection tags
        has_thinking = "<thinking>" in content.lower() or "think" in content.lower()

        print(f"[{'OK' if has_thinking else 'WARN'}] CoT response (has reasoning: {has_thinking}):")
        print(f"     {content[:300]}...")

        return True
    except Exception as e:
        print(f"[FAIL] CoT Reflection failed: {e}")
        return False


def test_best_of_n(model: str) -> bool:
    """Test Best-of-N sampling technique."""
    print("\n--- Test: Best-of-N technique ---")
    try:
        client = OpenAI(api_key=OPTILLM_API_KEY, base_url=f"{OPTILLM_URL}/v1")
        technique_model = f"bon-{model}"

        response = client.chat.completions.create(
            model=technique_model,
            messages=[
                {"role": "user", "content": "Write a one-line Python function to check if a number is prime."}
            ],
            max_tokens=200,
            temperature=0.7,
        )
        content = response.choices[0].message.content
        print(f"[OK] Best-of-N response:")
        print(f"     {content[:200]}...")
        return True
    except Exception as e:
        print(f"[FAIL] Best-of-N failed: {e}")
        return False


def main():
    print("=" * 60)
    print("optillm + vLLM Integration Test")
    print("=" * 60)
    print(f"vLLM URL: {VLLM_URL}")
    print(f"optillm URL: {OPTILLM_URL}")
    print("=" * 60)

    # Check services
    vllm_ok = check_vllm()
    optillm_ok = check_optillm()

    if not vllm_ok:
        print("\n[!] vLLM not running. Start it with:")
        print("    ~/local/srv/vllm/serve.sh")
        sys.exit(1)

    if not optillm_ok:
        print("\n[!] optillm not running. Start it with:")
        print("    export OPENAI_API_KEY='sk-dummy'")
        print("    export OPTILLM_API_KEY='sk-optillm'")
        print(f"    export OPTILLM_BASE_URL='{VLLM_URL}/v1'")
        print("    uv run optillm --port 8080")
        sys.exit(1)

    # Get model name from vLLM
    r = httpx.get(f"{VLLM_URL}/v1/models")
    models = r.json().get("data", [])
    if not models:
        print("[!] No models loaded in vLLM")
        sys.exit(1)

    model = models[0]["id"]
    print(f"\nUsing model: {model}")

    # Run tests
    results = {
        "Direct vLLM": test_direct_vllm(model),
        "optillm passthrough": test_optillm_passthrough(model),
        "CoT Reflection": test_cot_reflection(model),
        "Best-of-N": test_best_of_n(model),
    }

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    for name, passed in results.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status} {name}")

    all_passed = all(results.values())
    print(f"\nOverall: {'All tests passed!' if all_passed else 'Some tests failed'}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
