#!/usr/bin/env python
"""Run evolution daemon continuously.

Usage:
    uv run python scripts/run_evolution.py [--endpoint reasoning]

This script runs indefinitely, monitoring GPU utilization and
running evolution cycles when resources are idle.

Press Ctrl+C to stop gracefully.
"""

import asyncio
import argparse
import signal
import sys
from datetime import datetime


async def main(endpoint: str = "fast"):
    """Run evolution daemon continuously."""
    from gaius.inference.orchestrator import get_orchestrator
    from gaius.agents.evolution import get_evolution_daemon

    print(f"[{datetime.now().isoformat()}] Starting evolution runner...")
    print(f"  Endpoint: {endpoint}")

    # Phase 1: Clean start GPU
    print(f"[{datetime.now().isoformat()}] Phase 1: Cleaning up and starting GPU...")
    orchestrator = get_orchestrator()
    result = await orchestrator.clean_start([endpoint])

    if not result["success"]:
        print(f"[{datetime.now().isoformat()}] ERROR: Failed to start GPU endpoint")
        print(f"  Cleanup: {result['cleanup']}")
        print(f"  Startup: {result['startup']}")
        return 1

    print(f"[{datetime.now().isoformat()}] GPU ready: {result['startup']}")

    # Phase 2: Start evolution daemon
    print(f"[{datetime.now().isoformat()}] Phase 2: Starting evolution daemon...")
    daemon = get_evolution_daemon()
    await daemon.start()

    print(f"[{datetime.now().isoformat()}] Evolution daemon running!")
    print(f"  Next agent: {daemon.next_agent}")
    print(f"  Strategy: {daemon.config.strategy}")
    print(f"  Agents: {daemon.config.agents}")
    print()
    print("Press Ctrl+C to stop gracefully.")
    print()

    # Set up signal handlers
    stop_event = asyncio.Event()

    def signal_handler():
        print(f"\n[{datetime.now().isoformat()}] Shutdown signal received...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Monitor loop
    last_cycles = 0
    while not stop_event.is_set():
        try:
            status = daemon.get_status()
            cycles = status["cycles_completed"]

            if cycles > last_cycles:
                improvement = status.get("total_improvement_percent", 0)
                print(f"[{datetime.now().isoformat()}] Cycle {cycles} complete | "
                      f"Total improvement: {improvement:.1f}%")
                last_cycles = cycles

            # Wait 10 seconds between status checks
            await asyncio.wait_for(stop_event.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            continue

    # Graceful shutdown
    print(f"[{datetime.now().isoformat()}] Stopping daemon...")
    await daemon.stop()

    status = daemon.get_status()
    print(f"[{datetime.now().isoformat()}] Final status:")
    print(f"  Cycles completed: {status['cycles_completed']}")
    print(f"  Total improvement: {status.get('total_improvement_percent', 0):.1f}%")

    # Stop orchestrator
    print(f"[{datetime.now().isoformat()}] Stopping GPU endpoint...")
    await orchestrator.stop()

    print(f"[{datetime.now().isoformat()}] Evolution runner stopped.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run evolution daemon continuously")
    parser.add_argument(
        "--endpoint", "-e",
        default="fast",
        help="GPU endpoint to use (default: fast)"
    )
    args = parser.parse_args()

    sys.exit(asyncio.run(main(args.endpoint)))
