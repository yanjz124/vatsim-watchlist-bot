#!/usr/bin/env bash
set -euo pipefail

# Simple deploy helper for Raspberry Pi/systemd deployments.
# Usage: Run from the repository root or call this script from your deploy process.
# Configure VENV with the environment variable VENV or place a virtualenv at ./.venv

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${VENV:-$REPO_DIR/.venv}"

echo "Deploy: repo=$REPO_DIR venv=$VENV"

if [ -d "$VENV" ]; then
    echo "Activating virtualenv: $VENV"
    # shellcheck disable=SC1090
    source "$VENV/bin/activate"
else
    echo "No virtualenv found at $VENV — continuing with system python"
fi

echo "Installing requirements..."
python -m pip install --upgrade pip
python -m pip install -r "$REPO_DIR/requirements.txt"

echo "Restarting systemd service: larperdetector.service"
echo "Restarting systemd service: larperdetector.service"
# If running as root, restart directly. Otherwise attempt a sudo restart non-interactively.
if [ "$(id -u)" -eq 0 ]; then
    systemctl restart larperdetector.service || {
        echo "Failed to restart service as root. Check service name and logs."
        exit 1
    }
else
    # Try to restart via sudo without prompting for password. If sudo would prompt, fail with actionable message.
    if sudo -n /bin/systemctl restart larperdetector.service 2>/dev/null; then
        echo "Service restarted via sudo."
    else
        echo "Failed to restart service via sudo without a password."
        echo "If you want deploy to restart the service automatically, allow this command without a password for the deploy user on the host:" 
        echo
        echo "  # Run on the server as root (adjust user if needed)"
        echo "  USERNAME=$(whoami)" 
        echo "  echo \"\$USERNAME ALL=(root) NOPASSWD: /bin/systemctl restart larperdetector.service\" | sudo tee /etc/sudoers.d/larperdetector"
        echo "  sudo chmod 440 /etc/sudoers.d/larperdetector"
        echo
        echo "Alternatively, run this script as root or restart the service manually: sudo systemctl restart larperdetector.service"
        exit 2
    fi
fi

echo "Deploy complete." 
