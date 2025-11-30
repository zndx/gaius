#!/usr/bin/env python3
"""Test script to validate MCP server functionality.

This tests the MCP tools directly without going through the MCP protocol.
"""

import asyncio
import json
import os
import sys

# Ensure we're in the project directory
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set required env vars for inference (use direct assignment to ensure they're set)
os.environ["OPTILLM_API_KEY"] = "sk-optillm"
os.environ["GAIUS_OPTILLM_URL"] = "http://localhost:8080/v1"
os.environ["GAIUS_VLLM_URL"] = "http://localhost:8088/v1"
os.environ["GAIUS_OFFLINE"] = "true"  # Disable OpenAI fallback

# Reset the inference client singleton to pick up fresh env vars
import gaius.inference
gaius.inference._client = None


async def call_tool(server, name: str, arguments: dict) -> dict:
    """Call a tool on the FastMCP server."""
    result = await server.call_tool(name, arguments)
    # FastMCP returns (list[TextContent], dict) tuple
    if result and len(result) >= 2:
        # Get result from the dict in position 1
        result_dict = result[1]
        if 'result' in result_dict:
            return json.loads(result_dict['result'])
        # Or from the TextContent list in position 0
        content_list = result[0]
        if content_list and hasattr(content_list[0], 'text'):
            return json.loads(content_list[0].text)
    return {"error": "No result"}


async def test_kb_operations():
    """Test KB CRUD operations."""
    print("\n=== KB Operations ===\n")

    from gaius.mcp_server import create_server

    server = create_server()

    # Test list_kb
    print("1. list_kb():")
    data = await call_tool(server, "list_kb", {"directory": ""})
    print(f"   Found {data.get('total', 0)} entries")

    # Test create_kb
    print("\n2. create_kb():")
    test_path = "scratch/mcp_test.md"
    test_content = "# MCP Test\n\nThis is a test entry created by the MCP test script."
    data = await call_tool(server, "create_kb", {"path": test_path, "content": test_content})
    if "error" in data:
        print(f"   Error: {data['error']}")
    else:
        print(f"   Created: {data.get('created')}")

    # Test read_kb
    print("\n3. read_kb():")
    data = await call_tool(server, "read_kb", {"path": test_path})
    if "error" in data:
        print(f"   Error: {data['error']}")
    else:
        print(f"   Read {data.get('size', 0)} bytes from {data.get('path')}")

    # Test search_kb
    print("\n4. search_kb():")
    data = await call_tool(server, "search_kb", {"query": "mcp_test"})
    print(f"   Found {data.get('total', 0)} results")

    # Test update_kb
    print("\n5. update_kb():")
    new_content = test_content + "\n\nUpdated!"
    data = await call_tool(server, "update_kb", {"path": test_path, "content": new_content})
    if "error" in data:
        print(f"   Error: {data['error']}")
    else:
        print(f"   Updated: old={data.get('old_size')}, new={data.get('new_size')}")

    # Test delete_kb
    print("\n6. delete_kb():")
    data = await call_tool(server, "delete_kb", {"path": test_path})
    if "error" in data:
        print(f"   Error: {data['error']}")
    else:
        print(f"   Deleted: {data.get('deleted')}")

    print("\n[OK] KB operations test complete")
    return True


async def test_inference():
    """Test local inference via optillm."""
    print("\n=== Inference Operations ===\n")

    from gaius.mcp_server import create_server

    server = create_server()

    print("1. ask_local() - simple question:")
    data = await call_tool(server, "ask_local", {
        "question": "What is 2+2? Answer with just the number.",
        "technique": "",
        "max_tokens": 50
    })
    if "error" in data:
        print(f"   Error: {data['error']}")
        return False
    else:
        response = data.get("response", "")[:100]
        print(f"   Model: {data.get('model')}")
        print(f"   Response: {response}...")
        print(f"   Tokens: {data.get('input_tokens')} in, {data.get('output_tokens')} out")

    print("\n2. ask_local() - with cot_reflection technique:")
    data = await call_tool(server, "ask_local", {
        "question": "What are the factors of 24? Think step by step.",
        "technique": "cot_reflection",
        "max_tokens": 200
    })
    if "error" in data:
        print(f"   Error: {data['error']}")
    else:
        response = data.get("response", "")[:200]
        print(f"   Technique: {data.get('technique')}")
        print(f"   Response: {response}...")

    print("\n[OK] Inference test complete")
    return True


async def test_kb_resources():
    """Test KB entries exposed as MCP resources."""
    print("\n=== KB Resources ===\n")

    from gaius.mcp_server import create_server

    server = create_server()

    # List all resources
    print("1. list_resources():")
    resources = await server.list_resources()
    print(f"   Found {len(resources)} KB resources")

    if not resources:
        print("   [WARN] No resources found - KB may be empty")
        return True

    # Show first 5 resources
    for r in resources[:5]:
        print(f"   - {r.uri}: {r.name}")
    if len(resources) > 5:
        print(f"   ... and {len(resources) - 5} more")

    # Read a resource with content
    print("\n2. read_resource():")
    # Find a resource with actual content (overview.md is known to have content)
    target_uri = None
    for r in resources:
        uri_str = str(r.uri)
        if "overview" in uri_str or "domains" in uri_str:
            target_uri = r.uri
            break

    if not target_uri:
        target_uri = resources[0].uri

    result = await server.read_resource(target_uri)
    if result and len(result) > 0:
        item = result[0]
        content = item.content if hasattr(item, 'content') else str(item)
        print(f"   Resource: {target_uri}")
        print(f"   Content length: {len(content)} chars")
        print(f"   MIME type: {item.mime_type if hasattr(item, 'mime_type') else 'unknown'}")
        if content:
            preview = content[:150].replace('\n', ' ')
            print(f"   Preview: {preview}...")
    else:
        print(f"   Error: Could not read {target_uri}")

    print("\n[OK] KB resources test complete")
    return True


async def main():
    print("=" * 60)
    print("Gaius MCP Server Test")
    print("=" * 60)

    results = {}

    # Test KB operations
    try:
        results["KB Operations"] = await test_kb_operations()
    except Exception as e:
        print(f"\n[FAIL] KB operations: {e}")
        import traceback
        traceback.print_exc()
        results["KB Operations"] = False

    # Test KB resources
    try:
        results["KB Resources"] = await test_kb_resources()
    except Exception as e:
        print(f"\n[FAIL] KB resources: {e}")
        import traceback
        traceback.print_exc()
        results["KB Resources"] = False

    # Test inference
    try:
        results["Inference"] = await test_inference()
    except Exception as e:
        print(f"\n[FAIL] Inference: {e}")
        import traceback
        traceback.print_exc()
        results["Inference"] = False

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
    sys.exit(asyncio.run(main()))
