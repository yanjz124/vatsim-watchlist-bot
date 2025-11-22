#!/usr/bin/env bash
set -euo pipefail

# Example git post-merge hook to run after a successful pull/merge on the server.
# Place this in the repo on the Pi at .git/hooks/post-merge and make it executable.
# It will call the repo's deploy script to install new deps and restart the service.

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "post-merge hook: running deploy script"
"$REPO_DIR/scripts/deploy.sh"
