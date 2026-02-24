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
            echo "  luxcore   LuxCoreRender (pyluxcore with GPU support)"
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

    # Apply patches if needed
    PATCHES_DIR="${SCRIPT_DIR}/patches"
    if [ -f "${PATCHES_DIR}/cm_ext-findbugs-version.patch" ]; then
        log_info "Applying patches..."
        git checkout -- . 2>/dev/null || true  # Reset any previous patches
        patch -p1 < "${PATCHES_DIR}/cm_ext-findbugs-version.patch" || {
            log_warn "Patch may have already been applied"
        }
    fi

    # Step 1: Build cm-schema first (required dependency)
    # Skip tests and javadoc (JDK 11 has stricter javadoc rules that fail on old code)
    log_info "Building cm-schema..."
    cd cm-schema
    mvn clean install -DskipTests -Dmaven.javadoc.skip=true -q
    cd ..

    # Step 2: Build the validator
    log_info "Building validator..."
    cd validator
    mvn clean package -DskipTests -Dmaven.javadoc.skip=true -q
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
# Build LuxCore (Physically-Based Renderer)
# =============================================================================
build_luxcore() {
    log_info "Building LuxCoreRender (pyluxcore with GPU support)..."

    if [ ! -d "${LUXCORE_SOURCE}" ]; then
        log_error "LuxCore source not found at ${LUXCORE_SOURCE}."
        log_error "Run: git submodule update --init thirdparty/src/LuxCore"
        exit 1
    fi

    # Check build prerequisites
    for cmd in cmake conan ninja; do
        if ! command -v $cmd &> /dev/null; then
            log_error "$cmd is not installed. Ensure devenv shell is active."
            exit 1
        fi
    done

    log_info "  cmake:  $(cmake --version | head -1)"
    log_info "  conan:  $(conan --version 2>&1 | head -1)"
    log_info "  ninja:  $(ninja --version 2>&1 | head -1)"
    log_info "  gcc:    $(gcc --version | head -1)"

    # Check CUDA — add to PATH if system CUDA exists but isn't in devenv PATH
    if ! command -v nvcc &> /dev/null; then
        for cuda_dir in /usr/local/cuda /usr/local/cuda-12 /usr/local/cuda-12.4; do
            if [ -x "${cuda_dir}/bin/nvcc" ]; then
                export PATH="${cuda_dir}/bin:${PATH}"
                log_info "Added ${cuda_dir}/bin to PATH for CUDA support"
                break
            fi
        done
    fi
    if command -v nvcc &> /dev/null; then
        log_info "  nvcc:   $(nvcc --version 2>&1 | tail -1)"
    else
        log_warn "nvcc not found — LuxCore will build without CUDA/OptiX GPU support"
    fi

    # =========================================================================
    # Environment sanitization for Nix/devenv
    # =========================================================================
    # The devenv Python wrapper injects Nix's gcc libstdc++ into LD_LIBRARY_PATH.
    # This libstdc++ requires glibc 2.42+ (Nix rolling), but host binaries only
    # have glibc 2.35 (Ubuntu 22.04), causing "GLIBC_2.38 not found" crashes.
    # Strip it from LD_LIBRARY_PATH. Nix binaries use RUNPATH and don't need it.
    log_info "Sanitizing LD_LIBRARY_PATH for Nix compatibility..."
    ORIG_LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"
    export LD_LIBRARY_PATH=$(echo "$ORIG_LD_LIBRARY_PATH" | tr ':' '\n' | grep -v '/nix/store.*gcc.*-lib/lib' | paste -sd ':' -)
    log_info "  LD_LIBRARY_PATH: ${LD_LIBRARY_PATH:-(empty)}"

    # Build PKG_CONFIG_PATH from Nix-provided system libraries.
    # conan's system recipes (opengl/system, xorg/system) are configured with
    # tools.system.package_manager:mode=disabled, so cmake must find libraries
    # via pkg-config from these Nix paths.
    # The LUXCORE_NIX_PKGCONFIG env var is set by devenv.nix with the .dev
    # output paths that aren't automatically in the pkg-config wrapper's search.
    log_info "Building PKG_CONFIG_PATH from Nix packages..."
    if [ -n "${LUXCORE_NIX_PKGCONFIG:-}" ]; then
        export PKG_CONFIG_PATH="${LUXCORE_NIX_PKGCONFIG}${PKG_CONFIG_PATH:+:${PKG_CONFIG_PATH}}"
    fi
    # Also include the devenv profile's pkgconfig
    if [ -d "${DEVENV_ROOT:-.}/.devenv/profile/lib/pkgconfig" ]; then
        export PKG_CONFIG_PATH="${PKG_CONFIG_PATH:+${PKG_CONFIG_PATH}:}${DEVENV_ROOT:-.}/.devenv/profile/lib/pkgconfig"
    fi
    log_info "  PKG_CONFIG_PATH: ${PKG_CONFIG_PATH:-(empty)}"

    cd "${LUXCORE_SOURCE}"

    # Step 1: Install dependencies via Conan (downloads pre-built packages)
    log_info "Step 1/3: Installing LuxCore dependencies via Conan..."
    make deps 2>&1 | while IFS= read -r line; do
        echo "  $line"
    done

    # Step 2: Build pyluxcore target (the Python bindings we need)
    log_info "Step 2/3: Building pyluxcore..."
    make pyluxcore 2>&1 | while IFS= read -r line; do
        echo "  $line"
    done

    # Step 3: Install to our thirdparty installed dir
    log_info "Step 3/3: Installing pyluxcore..."
    mkdir -p "${LUXCORE_INSTALLED}"

    # The build produces pyluxcore.so in the install directory
    INSTALL_DIR="${LUXCORE_SOURCE}/out/install/Release"
    if [ -d "${INSTALL_DIR}" ]; then
        cp -r "${INSTALL_DIR}"/* "${LUXCORE_INSTALLED}/"
        log_info "LuxCore installed to: ${LUXCORE_INSTALLED}"
    else
        log_warn "Install directory not found at ${INSTALL_DIR}"
        log_info "Checking build output..."
        find "${LUXCORE_SOURCE}/out" -name "pyluxcore*" -type f 2>/dev/null | head -5
    fi

    # Step 3b: Create lib/ directory with runtime shared libraries.
    # pyluxcore.so has RPATH=$ORIGIN/../lib, so it looks for shared libs
    # in a lib/ directory that is a sibling of the pyluxcore/ directory.
    # The conan deps provide these in the full_deploy directory.
    DEPS_DIR="${LUXCORE_SOURCE}/out/dependencies/full_deploy/host"
    LIB_DIR="${LUXCORE_INSTALLED}/lib"
    if [ -d "${DEPS_DIR}" ]; then
        log_info "Creating runtime lib/ directory..."
        mkdir -p "${LIB_DIR}"

        # OIDN (OpenImageDenoise) - from conan oidn package
        OIDN_LIB="${DEPS_DIR}/oidn/2.3.1/Release/x86_64/lib"
        if [ -d "${OIDN_LIB}" ]; then
            for so in "${OIDN_LIB}"/*.so*; do
                [ -f "$so" ] && ln -sf "$so" "${LIB_DIR}/$(basename "$so")"
            done
            # Create soname symlinks (e.g. .so.2 -> .so.2.3.1)
            for versioned in "${LIB_DIR}"/libOpenImageDenoise*.so.*.*.*; do
                [ -f "$versioned" ] || continue
                soname=$(basename "$versioned" | sed 's/\.\([0-9]*\)\.\([0-9]*\)\.\([0-9]*\)$/.\1/')
                [ ! -e "${LIB_DIR}/${soname}" ] && ln -sf "$(basename "$versioned")" "${LIB_DIR}/${soname}"
            done
        fi

        # OIDN device_cpu plugin (from cmake install)
        DEVICE_CPU="${LUXCORE_INSTALLED}/pyluxcore.libs/libOpenImageDenoise_device_cpu.so.2.3.1"
        if [ -f "${DEVICE_CPU}" ]; then
            ln -sf "${DEVICE_CPU}" "${LIB_DIR}/$(basename "${DEVICE_CPU}")"
        fi

        # OneTBB - from conan onetbb package
        TBB_LIB="${DEPS_DIR}/onetbb/2021.12.0/Release/x86_64/lib"
        if [ -d "${TBB_LIB}" ]; then
            for so in "${TBB_LIB}"/*.so*; do
                [ -f "$so" ] && ln -sf "$so" "${LIB_DIR}/$(basename "$so")"
            done
        fi

        log_info "Runtime libraries linked:"
        ls -la "${LIB_DIR}"/ 2>/dev/null | while IFS= read -r line; do echo "  $line"; done
    fi

    # Verify pyluxcore is importable
    PYLUXCORE_SO=$(find "${LUXCORE_INSTALLED}/pyluxcore" -name "pyluxcore*.so" 2>/dev/null | head -1)
    if [ -n "${PYLUXCORE_SO}" ]; then
        log_info "Found: ${PYLUXCORE_SO}"
        log_info "Testing import..."
        python3 -c "
import sys
sys.path.insert(0, '$(dirname "${PYLUXCORE_SO}")')
import pyluxcore
print(f'pyluxcore {pyluxcore.Version()} loaded successfully')
descs = pyluxcore.GetOpenCLDeviceDescs()
print(f'  OpenCL devices: {descs.GetSize()}')
" 2>&1 | while IFS= read -r line; do
            echo "  $line"
        done
        log_info "LuxCore build complete!"
    else
        log_warn "pyluxcore .so not found — check build output for errors"
    fi
}

# =============================================================================
# Main
# =============================================================================
main() {
    log_info "========================================"
    log_info "Building third-party dependencies"
    log_info "========================================"

    if [ -z "${COMPONENT}" ] || [ "${COMPONENT}" == "cm_ext" ]; then
        preflight_check
        build_cm_ext
    fi

    if [ -z "${COMPONENT}" ] || [ "${COMPONENT}" == "luxcore" ]; then
        build_luxcore
    fi

    log_info "========================================"
    log_info "Build complete!"
    log_info "========================================"
    log_info ""
    log_info "Installed artifacts:"
    ls -la "${INSTALLED_DIR}"/cloudera/*.jar 2>/dev/null || log_warn "No JARs installed"
    ls -la "${INSTALLED_DIR}"/LuxCore/lib/pyluxcore*.so 2>/dev/null || log_warn "No pyluxcore installed"
}

main
