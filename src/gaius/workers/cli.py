"""CLI entry point for fetch workers.

Usage:
    gaius-worker                    # Run worker pool as daemon
    gaius-worker --once             # Process all pending jobs once
    gaius-worker --pool-size 2      # Run with 2 workers
    gaius-worker --status           # Show job status
"""

import argparse
import asyncio
import logging
import sys

from gaius.workers.config import WorkerConfig
from gaius.workers.manager import run_once, run_worker_pool


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the worker."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quiet down noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)


async def show_status(config: WorkerConfig) -> None:
    """Show current job and source status."""
    from gaius.workers.db import Database

    db = await Database.connect(config.db_url)
    try:
        pending = await db.get_pending_job_count()
        print(f"Pending jobs: {pending}")
        print()

        stats = await db.get_source_stats()
        if stats:
            print("Source Status:")
            print("-" * 80)
            for stat in stats:
                status_icon = {
                    "ok": "[OK]",
                    "overdue": "[!]",
                    "never": "[-]",
                }.get(stat.get("status", ""), "[?]")

                print(
                    f"  {status_icon} {stat['name']:<20} "
                    f"type={stat['source_type']:<10} "
                    f"items={stat.get('total_items', 0):>5} "
                    f"kb={stat.get('kb_items', 0):>5} "
                    f"pending={stat.get('pending_jobs', 0):>3}"
                )
        else:
            print("No sources configured.")
    finally:
        await db.close()


def main() -> int:
    """Main entry point."""
    # Initialize telemetry early with worker entry point
    try:
        from gaius.core.config import get_config
        from gaius.core.telemetry import init_from_config
        config = get_config()
        init_from_config(config, entry_point="worker")
    except Exception:
        pass  # Telemetry init failure is non-fatal

    parser = argparse.ArgumentParser(
        description="Gaius fetch worker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process all pending jobs once and exit",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show job and source status",
    )
    parser.add_argument(
        "--pool-size",
        type=int,
        default=None,
        help="Number of concurrent workers (default: from env or 4)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=None,
        help="Seconds between job polls (default: from env or 30)",
    )
    parser.add_argument(
        "--process",
        type=int,
        nargs="?",
        const=50,
        metavar="LIMIT",
        help="Process content items to KB (default limit: 50)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Load config from environment
    config = WorkerConfig.from_env()

    # Override from CLI
    if args.pool_size is not None:
        config = config.with_pool_size(args.pool_size)

    if args.status:
        asyncio.run(show_status(config))
        return 0

    if args.process is not None:
        from gaius.workers.processor import process_content
        processed = asyncio.run(process_content(config, limit=args.process))
        print(f"Processed {processed} items to KB")
        return 0

    if args.once:
        processed = asyncio.run(run_once(config))
        print(f"Processed {processed} jobs")
        return 0

    # Run as daemon
    try:
        asyncio.run(run_worker_pool(config))
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
