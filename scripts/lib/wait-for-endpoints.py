#!/usr/bin/env python3
"""Poll gRPC OrchestratorStatus until all endpoints are HEALTHY.

Designed for use in restart-clean.sh Phase 2. Pays the Python import
cost once (~5s), then polls in a tight loop with live terminal output.

Exit codes:
  0 - All endpoints healthy (or no endpoints found, or import failure)
  1 - Timeout or endpoint failure
"""
import argparse
import sys
import time

# Status enum values from gaius_service.proto
HEALTHY = 3
STARTING = 2
PENDING = 7
FAILED = 6

STATUS_LABELS = {
    0: "UNSPECIFIED",
    1: "STOPPED",
    2: "STARTING",
    3: "HEALTHY",
    4: "UNHEALTHY",
    5: "STOPPING",
    6: "FAILED",
    7: "PENDING",
}


def _import_grpc():
    """Import gRPC deps. Returns (stub_class, empty_pb2) or None on failure."""
    try:
        import grpc
        from gaius.engine.generated import GaiusServiceStub
        from google.protobuf import empty_pb2

        return grpc, GaiusServiceStub, empty_pb2
    except ImportError as e:
        print(f"  (skipping endpoint polling: {e})")
        return None


def _status_label(status_value):
    return STATUS_LABELS.get(status_value, f"UNKNOWN({status_value})")


def _format_time(seconds):
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60:02d}s"


def poll(timeout, interval, host, port):
    deps = _import_grpc()
    if deps is None:
        return 0

    grpc_mod, StubClass, empty_pb2 = deps
    target = f"{host}:{port}"
    channel = grpc_mod.insecure_channel(target)
    stub = StubClass(channel)

    is_tty = sys.stdout.isatty()
    first_seen = {}  # endpoint name -> monotonic time
    prev_line_count = 0
    start = time.monotonic()

    while True:
        elapsed = time.monotonic() - start
        if elapsed > timeout:
            print(f"\n  Timeout after {_format_time(int(elapsed))}")
            channel.close()
            return 1

        try:
            resp = stub.OrchestratorStatus(empty_pb2.Empty(), timeout=10)
        except Exception:
            # Engine not ready yet — keep waiting
            if is_tty:
                print(f"\r  Connecting to engine... [{_format_time(int(elapsed))}]", end="", flush=True)
            else:
                print(f"  Connecting to engine... [{_format_time(int(elapsed))}]")
            time.sleep(interval)
            continue

        endpoints = list(resp.endpoints)
        if not endpoints:
            if is_tty:
                print(f"\r  No endpoints configured yet... [{_format_time(int(elapsed))}]", end="", flush=True)
            else:
                print(f"  No endpoints configured yet... [{_format_time(int(elapsed))}]")
            time.sleep(interval)
            continue

        now = time.monotonic()
        for ep in endpoints:
            if ep.name not in first_seen:
                first_seen[ep.name] = now

        # Build display lines
        lines = []
        all_healthy = True
        any_failed = False

        for ep in endpoints:
            status_val = ep.status
            status_str = _status_label(status_val)
            ep_elapsed = int(now - first_seen[ep.name])
            model_short = ep.model.split("/")[-1] if ep.model else ""

            if status_val == HEALTHY:
                line = f"  \033[32m✓\033[0m {ep.name:<18s} HEALTHY    {model_short:<45s} [{_format_time(ep_elapsed)}]"
            elif status_val == FAILED:
                line = f"  \033[31m✗\033[0m {ep.name:<18s} FAILED     {model_short}"
                any_failed = True
                all_healthy = False
            else:
                line = f"  \033[33m·\033[0m {ep.name:<18s} {status_str:<10s} {model_short}"
                all_healthy = False

            lines.append(line)

        # Render table
        if is_tty and prev_line_count > 0:
            # Move cursor up to overwrite previous output
            sys.stdout.write(f"\033[{prev_line_count}F")

        header = f"  Endpoints ({_format_time(int(elapsed))} elapsed)"
        print(header)
        for line in lines:
            # Clear to end of line in case previous was longer
            print(f"{line}\033[K" if is_tty else line)

        prev_line_count = 1 + len(lines)
        sys.stdout.flush()

        if all_healthy:
            print(f"\n  All {len(endpoints)} endpoint(s) ready.")
            channel.close()
            return 0

        if any_failed:
            print(f"\n  Endpoint failure detected.")
            channel.close()
            return 1

        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Wait for GPU endpoints to reach HEALTHY")
    parser.add_argument("--timeout", type=int, default=300, help="Max seconds to wait (default: 300)")
    parser.add_argument("--interval", type=int, default=5, help="Poll interval in seconds (default: 5)")
    parser.add_argument("--host", default="localhost", help="gRPC host (default: localhost)")
    parser.add_argument("--port", type=int, default=50051, help="gRPC port (default: 50051)")
    args = parser.parse_args()

    sys.exit(poll(args.timeout, args.interval, args.host, args.port))


if __name__ == "__main__":
    main()
