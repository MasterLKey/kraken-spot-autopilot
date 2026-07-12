#!/usr/bin/env bash
# Start/restart the bot using the local .env on this host (no Infisical).
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "ERROR: missing $(pwd)/.env"
  echo "Copy secrets with: scp .env root@<IP>:/opt/kraken-spot-autopilot/.env"
  exit 1
fi

chmod 600 .env
echo "Starting Kraken Spot Autopilot (docker compose)..."
docker compose up -d --build
echo ""
echo "Status:"
docker compose ps
echo ""
echo "Logs: docker compose logs -f --tail=50 bot"
