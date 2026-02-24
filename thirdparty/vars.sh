#!/bin/bash
# =============================================================================
# Third-Party Dependency Version Pins
# =============================================================================
# This file contains version pins and URLs for all third-party dependencies.
# Following the Apache Kudu pattern for thirdparty management.
# =============================================================================

# Cloudera Manager Extension Tools (cm_ext)
# Used for parcel and CSD validation
# https://github.com/cloudera/cm_ext
CM_EXT_VERSION="master"
CM_EXT_GIT_URL="https://github.com/cloudera/cm_ext.git"
CM_EXT_ARCHIVE_URL="https://github.com/cloudera/cm_ext/archive/refs/heads/master.zip"

# Directory structure
THIRDPARTY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${THIRDPARTY_DIR}/src"
BUILD_DIR="${THIRDPARTY_DIR}/build"
INSTALLED_DIR="${THIRDPARTY_DIR}/installed"

# Cloudera-specific paths
CM_EXT_SOURCE="${SOURCE_DIR}/cm_ext"
CM_EXT_VALIDATOR_JAR="${INSTALLED_DIR}/cloudera/validator.jar"

# LuxCoreRender - Physically-based unbiased renderer
# Used for card visualization rendering (glass, caustics, volumetrics)
# https://github.com/LuxCoreRender/LuxCore
LUXCORE_VERSION="2.10.0-dev0"
LUXCORE_GIT_URL="git@github.com:LuxCoreRender/LuxCore.git"
LUXCORE_DEPS_VERSION="1.0.0"  # From build-helpers/build-settings.json

# LuxCore paths
LUXCORE_SOURCE="${SOURCE_DIR}/LuxCore"
LUXCORE_BUILD="${BUILD_DIR}/LuxCore"
LUXCORE_INSTALLED="${INSTALLED_DIR}/LuxCore"

# Build requirements
MAVEN_MIN_VERSION="3.6.0"
JAVA_MIN_VERSION="8"
