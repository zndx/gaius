#!/usr/bin/env bash
# scripts/processes/nifi.sh — Apache NiFi (Data Flow Visualization)
# Initializes NiFi config on first run, then starts in foreground mode.
# Launched by devenv process-compose; see devenv.nix processes.nifi
#
# Environment (set by devenv.nix exec block):
#   NIFI_PACKAGE  — Nix store path for NiFi package
#   DEVENV_ROOT   — Project root directory
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/process-helpers.sh"

check_disabled DISABLE_NIFI "NiFi"

banner "APACHE NIFI - Data Flow Visualization"

# NiFi requires a writable home directory with specific structure
NIFI_HOME="${DEVENV_ROOT}/.devenv/state/nifi"

mkdir -p "$NIFI_HOME"/{conf,logs,run,database_repository,flowfile_repository,content_repository,provenance_repository,state,work}

# Symlink lib directory from Nix store (read-only, contains JARs)
if [ ! -L "$NIFI_HOME/lib" ]; then
  ln -sf "$NIFI_PACKAGE/lib" "$NIFI_HOME/lib"
fi

# Copy default config files if not present (always refresh on startup for dev)
if [ ! -f "$NIFI_HOME/conf/bootstrap.conf" ] || [ ! -f "$NIFI_HOME/conf/nifi.properties.initialized" ]; then
  echo "Initializing NiFi configuration..."

  # Copy from Nix store and make writable (Nix store files are read-only)
  rm -rf "$NIFI_HOME/conf"/* 2>/dev/null || true
  cp -r "$NIFI_PACKAGE"/share/nifi/conf/* "$NIFI_HOME/conf/" 2>/dev/null || true
  chmod -R u+w "$NIFI_HOME/conf/"

  # Update bootstrap.conf to use absolute paths
  cat > "$NIFI_HOME/conf/bootstrap.conf" << BOOTSTRAP_EOF
# NiFi Bootstrap Configuration for Gaius
java=java
run.as=
preserve.environment=false

# Use absolute paths for lib and conf
lib.dir=$NIFI_HOME/lib
conf.dir=$NIFI_HOME/conf

graceful.shutdown.seconds=20
java.arg.1=-Dorg.apache.jasper.compiler.disablejsr199=true
java.arg.2=-Xms512m
java.arg.3=-Xmx1g
java.arg.4=-Djava.net.preferIPv4Stack=true
java.arg.5=-Dsun.net.http.allowRestrictedHeaders=true
java.arg.6=-Djava.protocol.handler.pkgs=sun.net.www.protocol
java.arg.14=-Djava.awt.headless=true
java.arg.15=-Djava.security.egd=file:/dev/urandom
java.arg.16=-Djavax.security.auth.useSubjectCredsOnly=true
java.arg.17=-Dzookeeper.admin.enableServer=false
nifi.bootstrap.sensitive.key=
notification.services.file=$NIFI_HOME/conf/bootstrap-notification-services.xml
notification.max.attempts=5
java.arg.curator.supress.excessive.logs=-Dcurator-log-only-first-connection-issue-as-error-level=true
nifi.bootstrap.listen.port=0
BOOTSTRAP_EOF

  # Modify the default nifi.properties for our environment
  # Use sed to update specific properties rather than replacing the whole file
  PROPS="$NIFI_HOME/conf/nifi.properties"

  # Web server - bind to all interfaces on port 8450 (HTTP only, clear HTTPS)
  sed -i 's|^nifi.web.http.host=.*|nifi.web.http.host=0.0.0.0|' "$PROPS"
  sed -i 's|^nifi.web.http.port=.*|nifi.web.http.port=8450|' "$PROPS"
  # Clear HTTPS port - NiFi requires HTTP OR HTTPS, not both
  sed -i 's|^nifi.web.https.host=.*|nifi.web.https.host=|' "$PROPS"
  sed -i 's|^nifi.web.https.port=.*|nifi.web.https.port=|' "$PROPS"

  # Clear TLS/security properties for HTTP-only mode
  # These point to non-existent keystore/truststore files by default
  sed -i 's|^nifi.security.keystore=.*|nifi.security.keystore=|' "$PROPS"
  sed -i 's|^nifi.security.keystoreType=.*|nifi.security.keystoreType=|' "$PROPS"
  sed -i 's|^nifi.security.keystorePasswd=.*|nifi.security.keystorePasswd=|' "$PROPS"
  sed -i 's|^nifi.security.keyPasswd=.*|nifi.security.keyPasswd=|' "$PROPS"
  sed -i 's|^nifi.security.truststore=.*|nifi.security.truststore=|' "$PROPS"
  sed -i 's|^nifi.security.truststoreType=.*|nifi.security.truststoreType=|' "$PROPS"
  sed -i 's|^nifi.security.truststorePasswd=.*|nifi.security.truststorePasswd=|' "$PROPS"

  # Disable remote input secure mode (Site-to-Site) - requires HTTPS if true
  sed -i 's|^nifi.remote.input.secure=.*|nifi.remote.input.secure=false|' "$PROPS"

  # Set sensitive properties key for encryption
  sed -i 's|^nifi.sensitive.props.key=.*|nifi.sensitive.props.key=gaius-dev-key-12345|' "$PROPS"

  # Convert relative paths to absolute paths
  sed -i "s|^\(nifi.flow.configuration.file=\).*|\1$NIFI_HOME/conf/flow.json.gz|" "$PROPS"
  sed -i "s|^\(nifi.flow.configuration.json.file=\).*|\1$NIFI_HOME/conf/flow.json.gz|" "$PROPS"
  sed -i "s|^\(nifi.flow.configuration.archive.dir=\).*|\1$NIFI_HOME/conf/archive/|" "$PROPS"
  sed -i "s|^\(nifi.database.directory=\).*|\1$NIFI_HOME/database_repository|" "$PROPS"
  sed -i "s|^\(nifi.flowfile.repository.directory=\).*|\1$NIFI_HOME/flowfile_repository|" "$PROPS"
  sed -i "s|^\(nifi.content.repository.directory.default=\).*|\1$NIFI_HOME/content_repository|" "$PROPS"
  sed -i "s|^\(nifi.provenance.repository.directory.default=\).*|\1$NIFI_HOME/provenance_repository|" "$PROPS"
  sed -i "s|^\(nifi.state.management.configuration.file=\).*|\1$NIFI_HOME/conf/state-management.xml|" "$PROPS"
  sed -i "s|^\(nifi.state.management.embedded.zookeeper.properties=\).*|\1$NIFI_HOME/conf/zookeeper.properties|" "$PROPS"
  sed -i "s|^\(nifi.authorizer.configuration.file=\).*|\1$NIFI_HOME/conf/authorizers.xml|" "$PROPS"
  sed -i "s|^\(nifi.login.identity.provider.configuration.file=\).*|\1$NIFI_HOME/conf/login-identity-providers.xml|" "$PROPS"
  sed -i "s|^\(nifi.templates.directory=\).*|\1$NIFI_HOME/conf/templates|" "$PROPS"
  sed -i "s|^\(nifi.nar.library.directory=\).*|\1$NIFI_HOME/lib|" "$PROPS"
  sed -i "s|^\(nifi.nar.library.autoload.directory=\).*|\1$NIFI_HOME/extensions|" "$PROPS"
  sed -i "s|^\(nifi.nar.working.directory=\).*|\1$NIFI_HOME/work/nar/|" "$PROPS"
  sed -i "s|^\(nifi.documentation.working.directory=\).*|\1$NIFI_HOME/work/docs/components|" "$PROPS"
  sed -i "s|^\(nifi.status.repository.questdb.persist.location=\).*|\1$NIFI_HOME/status_repository|" "$PROPS"

  # Update state-management.xml with absolute path
  if [ -f "$NIFI_HOME/conf/state-management.xml" ]; then
    sed -i "s|<property name=\"Directory\">./state/local</property>|<property name=\"Directory\">$NIFI_HOME/state/local</property>|g" "$NIFI_HOME/conf/state-management.xml"
  fi

  # Ensure all conf files are writable (NiFi needs to update them at runtime)
  chmod -R u+w "$NIFI_HOME/conf/"

  # Mark as initialized
  touch "$NIFI_HOME/conf/nifi.properties.initialized"
fi

# Create extensions directory for user NARs
mkdir -p "$NIFI_HOME/extensions"
mkdir -p "$NIFI_HOME/work/nar"
mkdir -p "$NIFI_HOME/conf/archive"
mkdir -p "$NIFI_HOME/state/local"

echo ""
echo "Starting NiFi on port 8450..."
echo "  URL:        http://0.0.0.0:8450/nifi"
echo "  External:   http://tinybox.dev.vista.zndx.org:8450/nifi"
echo "  Home:       $NIFI_HOME"
echo ""
echo "Note: First startup may take 1-2 minutes to initialize."
echo "      Check $NIFI_HOME/logs/nifi-app.log for single-user credentials."
echo ""

# Critical: Tell nifi-env.sh to use OUR environment variables
export NIFI_OVERRIDE_NIFIENV="true"
export NIFI_HOME="$NIFI_HOME"
export NIFI_LOG_DIR="$NIFI_HOME/logs"
export NIFI_PID_DIR="$NIFI_HOME/run"

cd "$NIFI_HOME"

# Run NiFi in foreground mode
exec "${NIFI_PACKAGE}/bin/nifi.sh" run
