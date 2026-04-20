#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-$(pwd)}"
SERVICE_NAME="${2:-office-docs-to-md-sync}"
USER_NAME="${3:-$USER}"
UNIT_PATH="$HOME/.config/systemd/user/${SERVICE_NAME}.service"

mkdir -p "$(dirname "$UNIT_PATH")"
cat >"$UNIT_PATH" <<EOF
[Unit]
Description=Office Docs to Markdown Sync
After=network.target

[Service]
WorkingDirectory=${APP_DIR}
Environment=HOST=127.0.0.1
Environment=PORT=8080
Environment=APP_DATA_DIR=${APP_DIR}/.localdata
ExecStart=${APP_DIR}/dist/office-docs-to-md-sync/office-docs-to-md-sync
Restart=on-failure
User=${USER_NAME}

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "${SERVICE_NAME}.service"
echo "Installed ${SERVICE_NAME} to ${UNIT_PATH}"
