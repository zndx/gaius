#!/bin/bash
# Run content pipeline BDD tests with devenv process management
#
# This script uses devenv process-compose for service lifecycle management.
# Services are started via devenv and persist between test runs for efficiency.
#
# Usage:
#   ./scripts/run_pipeline_tests.sh              # Run all tiers
#   ./scripts/run_pipeline_tests.sh --tier 1     # Run tier-1 only (DB only)
#   ./scripts/run_pipeline_tests.sh --tier 2     # Run tier-1 and tier-2 (+ MinIO)
#   ./scripts/run_pipeline_tests.sh --tier 3     # Run tier-1 through tier-3 (+ engine)
#   ./scripts/run_pipeline_tests.sh --tags @qwq  # Run QwQ-tagged tests only
#   ./scripts/run_pipeline_tests.sh --dry-run    # Dry run

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Default values
TIER=""
TAGS=""
DRY_RUN=""
START_POSTGRES=true
STOP_POSTGRES=false
START_MINIO=false
START_ENGINE=false
VERBOSE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --tier)
            TIER="$2"
            shift 2
            ;;
        --tags)
            TAGS="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN="--dry-run"
            shift
            ;;
        --no-start-postgres)
            START_POSTGRES=false
            shift
            ;;
        --stop-postgres)
            STOP_POSTGRES=true
            shift
            ;;
        --with-minio)
            START_MINIO=true
            shift
            ;;
        --with-engine)
            START_ENGINE=true
            shift
            ;;
        -v|--verbose)
            VERBOSE="-v"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Determine required services based on tier
if [ -n "$TIER" ]; then
    case $TIER in
        1)
            TAG_EXPR="@tier-1"
            ;;
        2)
            TAG_EXPR="@tier-1,@tier-2"
            START_MINIO=true  # Tier-2 needs MinIO for Iceberg
            ;;
        3)
            TAG_EXPR="@tier-1,@tier-2,@tier-3"
            START_MINIO=true
            START_ENGINE=true  # Tier-3 needs inference
            ;;
        4)
            TAG_EXPR="@tier-1,@tier-2,@tier-3,@tier-4"
            START_MINIO=true
            START_ENGINE=true
            ;;
        5)
            TAG_EXPR="@tier-1,@tier-2,@tier-3,@tier-4,@tier-5"
            START_MINIO=true
            START_ENGINE=true
            ;;
        *)
            echo "Invalid tier: $TIER (use 1-5)"
            exit 1
            ;;
    esac
elif [ -n "$TAGS" ]; then
    TAG_EXPR="$TAGS"
else
    TAG_EXPR=""
fi

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Content Pipeline BDD Tests                                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Service management via devenv
DEVENV_PG_DATA="$PROJECT_ROOT/.devenv/state/postgres"
DEVENV_PG_PORT=5444
RUSTFS_PORT=9010   # Signals RustFS (S3 API); START_MINIO now means "require RustFS"

check_postgres() {
    pg_isready -h localhost -p $DEVENV_PG_PORT -q 2>/dev/null
}

check_rustfs() {
    nc -z localhost $RUSTFS_PORT 2>/dev/null
}

start_postgres() {
    if check_postgres; then
        echo "✓ PostgreSQL already running on port $DEVENV_PG_PORT"
        return 0
    fi

    if [ ! -d "$DEVENV_PG_DATA" ]; then
        echo "ERROR: devenv postgres data directory not found"
        echo "       Expected: $DEVENV_PG_DATA"
        echo "       Run 'devenv up' first to initialize postgres"
        return 1
    fi

    echo "Starting PostgreSQL..."
    pg_ctl start -D "$DEVENV_PG_DATA" -l "$DEVENV_PG_DATA/postgres.log" -o "-p $DEVENV_PG_PORT" -w

    # Wait for postgres
    for i in {1..30}; do
        if check_postgres; then
            echo "✓ PostgreSQL started on port $DEVENV_PG_PORT"
            return 0
        fi
        sleep 1
    done

    echo "ERROR: PostgreSQL failed to start"
    return 1
}

require_rustfs() {
    # RustFS is Signals' object store (127.0.0.1:9010); gaius runs no object store of
    # its own (devenv MinIO retired 2026-09-05). This script cannot start it — fail
    # fast with the owner's remediation instead of skipping tiers silently.
    if check_rustfs; then
        echo "✓ RustFS (Signals) answering on port $RUSTFS_PORT"
        mc alias set rustfs "http://localhost:$RUSTFS_PORT" rustfsadmin rustfsadmin >/dev/null 2>&1 || true
        mc mb rustfs/zndx-gaius-test --ignore-existing >/dev/null 2>&1 || true
        return 0
    fi
    echo "RustFS not answering on localhost:$RUSTFS_PORT — tier-2+ tests need it."
    echo "  Guru: #ST.00002.RUSTFS_UNREACHABLE"
    echo "  Try (in ~/local/src/wxs/signals): devenv processes start rustfs"
    echo "  Or:  systemctl status signals.service"
    return 1

    echo "WARNING: MinIO failed to start (tests may fail)"
    return 1
}

start_engine() {
    # Check if gRPC port is listening
    if nc -z localhost 50051 2>/dev/null; then
        echo "✓ Engine already running on port 50051"
        return 0
    fi

    echo "Starting gaius-engine via devenv..."
    devenv processes up gaius-engine -d >/dev/null 2>&1

    # Wait for engine
    for i in {1..30}; do
        if nc -z localhost 50051 2>/dev/null; then
            echo "✓ Engine started on port 50051"
            return 0
        fi
        sleep 1
    done

    echo "WARNING: Engine failed to start (tests may fail)"
    return 1
}

stop_postgres() {
    if ! check_postgres; then
        echo "PostgreSQL not running"
        return 0
    fi

    echo "Stopping PostgreSQL..."
    pg_ctl stop -D "$DEVENV_PG_DATA" -m fast
    echo "✓ PostgreSQL stopped"
}

cleanup_gpus() {
    # Aggressive GPU cleanup to ensure zero-state before GPU-intensive tests
    # This kills all vLLM processes and waits for GPU memory to be freed
    echo "=== GPU Cleanup ==="

    # Kill all vLLM processes (parent and tensor-parallel workers)
    pkill -9 -f "vllm" 2>/dev/null || true
    pkill -9 -f "VLLM" 2>/dev/null || true

    # Wait for processes to die
    sleep 3

    # Verify GPU memory is freed
    local attempts=0
    local max_attempts=10
    while [ $attempts -lt $max_attempts ]; do
        local all_free=true
        while IFS= read -r mem; do
            # Remove any whitespace and compare
            mem_int=${mem%.*}
            if [ -n "$mem_int" ] && [ "$mem_int" -gt 500 ]; then
                all_free=false
                echo "  GPU still has ${mem} MiB in use, waiting..."
                break
            fi
        done < <(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null)

        if $all_free; then
            echo "✓ All GPUs are free"
            return 0
        fi

        attempts=$((attempts + 1))
        sleep 2
    done

    echo "⚠ Warning: Some GPUs may still have memory in use"
    return 0
}

# Start required services
echo "Starting required services..."
echo ""

if $START_POSTGRES; then
    start_postgres || exit 1
fi

if $START_MINIO; then
    require_rustfs || exit 1
fi

if $START_ENGINE; then
    # Clean up GPU memory before starting engine (critical for tier-4+)
    cleanup_gpus
    start_engine || true  # Don't fail if engine doesn't start
fi

# Set environment
# Note: devenv postgres uses the system user, not 'postgres'
export GAIUS_DATABASE_URL="postgresql://$USER@localhost:$DEVENV_PG_PORT/zndx_gaius"
export GAIUS_KB_ROOT="$PROJECT_ROOT/build/test"
export GAIUS_RUSTFS_ENDPOINT="localhost:$RUSTFS_PORT"
export GAIUS_RUSTFS_BUCKET="zndx-gaius-test"
export GAIUS_RUSTFS_ACCESS_KEY="rustfsadmin"
export GAIUS_RUSTFS_SECRET_KEY="rustfsadmin"

echo ""
echo "Environment:"
echo "  GAIUS_DATABASE_URL=$GAIUS_DATABASE_URL"
echo "  GAIUS_KB_ROOT=$GAIUS_KB_ROOT"
if $START_MINIO; then
    echo "  GAIUS_RUSTFS_ENDPOINT=$GAIUS_RUSTFS_ENDPOINT"
    echo "  GAIUS_RUSTFS_BUCKET=$GAIUS_RUSTFS_BUCKET"
fi
echo ""

# Build behave command
BEHAVE_CMD="uv run behave"
if [ -n "$TAG_EXPR" ]; then
    BEHAVE_CMD="$BEHAVE_CMD --tags=\"$TAG_EXPR\""
fi
if [ -n "$DRY_RUN" ]; then
    BEHAVE_CMD="$BEHAVE_CMD $DRY_RUN"
fi
if [ -n "$VERBOSE" ]; then
    BEHAVE_CMD="$BEHAVE_CMD --no-capture"
fi
BEHAVE_CMD="$BEHAVE_CMD features/content_pipeline.feature"

echo "Running: $BEHAVE_CMD"
echo ""

# Run tests
eval $BEHAVE_CMD
TEST_RESULT=$?

# Stop postgres if requested
if $STOP_POSTGRES; then
    stop_postgres
fi

echo ""
if [ $TEST_RESULT -eq 0 ]; then
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  ✓ Tests Passed                                              ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
else
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  ✗ Tests Failed                                              ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
fi

exit $TEST_RESULT
