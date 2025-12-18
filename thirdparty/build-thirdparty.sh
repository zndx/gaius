#!/bin/bash
# =============================================================================
# Build Third-Party Dependencies
# =============================================================================
# Builds third-party dependencies from source.
# Following the Apache Kudu pattern for thirdparty management.
#
# Usage:
#   ./build-thirdparty.sh [--component <name>]
#
# Examples:
#   ./build-thirdparty.sh              # Build all dependencies
#   ./build-thirdparty.sh --component cm_ext
#
# Prerequisites:
#   - Java 8+ (JDK)
#   - Maven 3.6+
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/vars.sh"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Parse arguments
COMPONENT=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --component)
            COMPONENT="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--component <name>]"
            echo ""
            echo "Components:"
            echo "  cm_ext    Cloudera Manager Extension Tools (validator.jar)"
            exit 0
            ;;
        *)
            log_error "Unknown argument: $1"
            exit 1
            ;;
    esac
done

# =============================================================================
# Preflight Checks
# =============================================================================
preflight_check() {
    log_info "Running preflight checks..."

    # Check Java
    if ! command -v java &> /dev/null; then
        log_error "Java is not installed. Please install JDK 8+."
        exit 1
    fi

    JAVA_VERSION=$(java -version 2>&1 | head -1 | cut -d'"' -f2 | cut -d'.' -f1)
    if [ "$JAVA_VERSION" -lt "$JAVA_MIN_VERSION" ]; then
        log_error "Java version $JAVA_MIN_VERSION+ required. Found: $JAVA_VERSION"
        exit 1
    fi
    log_info "Java version: $(java -version 2>&1 | head -1)"

    # Check Maven
    if ! command -v mvn &> /dev/null; then
        log_error "Maven is not installed. Please install Maven 3.6+."
        exit 1
    fi
    log_info "Maven version: $(mvn -version 2>&1 | head -1)"

    log_info "Preflight checks passed!"
}

# =============================================================================
# Build cm_ext (Cloudera Manager Extension Tools)
# =============================================================================
build_cm_ext() {
    log_info "Building Cloudera cm_ext validator..."

    if [ ! -d "${CM_EXT_SOURCE}" ]; then
        log_error "cm_ext source not found. Run ./download-thirdparty.sh first."
        exit 1
    fi

    cd "${CM_EXT_SOURCE}"

    # Step 1: Build cm-schema first (required dependency)
    log_info "Building cm-schema..."
    cd cm-schema
    mvn clean install -DskipTests -q
    cd ..

    # Step 2: Build the validator
    log_info "Building validator..."
    cd validator
    mvn clean package -DskipTests -q
    cd ..

    # Step 3: Copy the built JAR to installed location
    mkdir -p "${INSTALLED_DIR}/cloudera"

    VALIDATOR_JAR=$(find validator/target -name "validator*.jar" -not -name "*sources*" | head -1)
    if [ -z "${VALIDATOR_JAR}" ]; then
        log_error "validator.jar not found after build!"
        exit 1
    fi

    cp "${VALIDATOR_JAR}" "${CM_EXT_VALIDATOR_JAR}"
    log_info "Validator installed to: ${CM_EXT_VALIDATOR_JAR}"

    # Verify it works
    log_info "Verifying validator..."
    java -jar "${CM_EXT_VALIDATOR_JAR}" --help > /dev/null 2>&1 || {
        log_warn "Validator help check failed, but JAR was built"
    }

    log_info "cm_ext validator build complete!"
}

# =============================================================================
# Main
# =============================================================================
main() {
    log_info "========================================"
    log_info "Building third-party dependencies"
    log_info "========================================"

    preflight_check

    if [ -z "${COMPONENT}" ] || [ "${COMPONENT}" == "cm_ext" ]; then
        build_cm_ext
    fi

    log_info "========================================"
    log_info "Build complete!"
    log_info "========================================"
    log_info ""
    log_info "Installed artifacts:"
    ls -la "${INSTALLED_DIR}"/cloudera/*.jar 2>/dev/null || log_warn "No JARs installed yet"
}

main
