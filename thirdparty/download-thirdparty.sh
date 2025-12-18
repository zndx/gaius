#!/bin/bash
# =============================================================================
# Download Third-Party Dependencies
# =============================================================================
# Downloads source code for third-party dependencies.
# Following the Apache Kudu pattern for thirdparty management.
#
# Usage:
#   ./download-thirdparty.sh [--component <name>]
#
# Examples:
#   ./download-thirdparty.sh              # Download all dependencies
#   ./download-thirdparty.sh --component cm_ext
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
            echo "  cm_ext    Cloudera Manager Extension Tools"
            exit 0
            ;;
        *)
            log_error "Unknown argument: $1"
            exit 1
            ;;
    esac
done

# Create directories
mkdir -p "${SOURCE_DIR}"

# =============================================================================
# Download cm_ext (Cloudera Manager Extension Tools)
# =============================================================================
download_cm_ext() {
    log_info "Downloading Cloudera cm_ext..."

    if [ -d "${CM_EXT_SOURCE}" ]; then
        log_info "cm_ext already exists, updating..."
        cd "${CM_EXT_SOURCE}"
        git fetch origin
        git checkout "${CM_EXT_VERSION}"
        git pull origin "${CM_EXT_VERSION}" || true
    else
        log_info "Cloning cm_ext from ${CM_EXT_GIT_URL}..."
        git clone "${CM_EXT_GIT_URL}" "${CM_EXT_SOURCE}"
        cd "${CM_EXT_SOURCE}"
        git checkout "${CM_EXT_VERSION}"
    fi

    log_info "cm_ext downloaded to ${CM_EXT_SOURCE}"
}

# =============================================================================
# Main
# =============================================================================
main() {
    log_info "========================================"
    log_info "Downloading third-party dependencies"
    log_info "========================================"

    if [ -z "${COMPONENT}" ] || [ "${COMPONENT}" == "cm_ext" ]; then
        download_cm_ext
    fi

    log_info "========================================"
    log_info "Download complete!"
    log_info "========================================"
    log_info ""
    log_info "Next step: Run ./build-thirdparty.sh to build"
}

main
