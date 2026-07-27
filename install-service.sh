#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/cognios-ui.service"

if [ ! -f "$SERVICE_FILE" ]; then
  echo "Error: cognios-ui.service not found in $SCRIPT_DIR"
  exit 1
fi

echo "Installing CogniOS UI service..."
echo "Make sure you've edited cognios-ui.service with your username and paths first!"
echo ""

sudo cp "$SERVICE_FILE" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cognios-ui
sudo systemctl start cognios-ui
sudo systemctl status cognios-ui
