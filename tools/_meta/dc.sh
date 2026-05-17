#!/usr/bin/env bash
# `dc` — wrapper for `docker compose` that works in Claude Code sessions
# where the macOS keychain is locked.
#
# It points DOCKER_CONFIG at a temporary anonymous config (no
# credential helpers) so public-image pulls work without auth.
# In normal interactive shells with keychain unlocked, just use
# `docker compose` directly.
#
# Usage:
#   tools/_meta/dc.sh build eval
#   tools/_meta/dc.sh up -d eval
#   tools/_meta/dc.sh run --rm train python -m tools.dataset.gen_bc configs/...
#   tools/_meta/dc.sh down

set -euo pipefail

DOCKER_CONFIG_DIR="/tmp/gicg-docker-config"
mkdir -p "$DOCKER_CONFIG_DIR"
cat > "$DOCKER_CONFIG_DIR/config.json" <<'EOF'
{
  "auths": {
    "https://index.docker.io/v1/": { "auth": "" }
  },
  "credHelpers": {
    "https://index.docker.io/v1/": ""
  },
  "cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]
}
EOF

DOCKER_CONFIG="$DOCKER_CONFIG_DIR" exec docker compose "$@"
