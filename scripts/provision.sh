#!/usr/bin/env bash
# One-time setup for the kraken-spot-autopilot LXC (local .env secrets — no Infisical yet).
set -euo pipefail

REPO_URL="https://github.com/MasterLKey/kraken-spot-autopilot.git"
APP_DIR="/opt/kraken-spot-autopilot"
SERVICE_FILE="/etc/systemd/system/kraken-spot-autopilot.service"

echo ""
echo "================================================================"
echo "  Kraken Spot Autopilot — Container Provisioning"
echo "================================================================"
echo ""

echo ">>> Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq curl git ca-certificates gnupg lsb-release

echo ">>> Installing Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo "Docker installed."
else
    echo "Docker already installed."
fi

echo ">>> Cloning repo..."
if [ -d "$APP_DIR" ]; then
    echo "App directory already exists, pulling latest..."
    git -C "$APP_DIR" pull
else
    git clone "$REPO_URL" "$APP_DIR"
fi

chmod +x "$APP_DIR/start.sh" "$APP_DIR/scripts/provision.sh" 2>/dev/null || true

echo ">>> Writing systemd unit..."
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Kraken Spot Autopilot
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=$APP_DIR/start.sh
ExecStop=/usr/bin/docker compose -f $APP_DIR/docker-compose.yml down
WorkingDirectory=$APP_DIR

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable kraken-spot-autopilot

echo ""
echo "================================================================"
echo "  Provisioning complete"
echo "================================================================"
echo ""
echo "Secrets are LOCAL (not Infisical)."
echo "Copy your .env onto the box, then start:"
echo ""
echo "  scp -i ~/.ssh/octo_scrape_deploy .env root@<IP>:$APP_DIR/.env"
echo "  ssh ... \"chmod 600 $APP_DIR/.env && bash $APP_DIR/start.sh\""
echo ""
echo "Or: systemctl start kraken-spot-autopilot"
echo ""
