#!/usr/bin/env bash
# Copy the backend to the server and (re)start the stack. Run it on your Mac:
#   export ORTSBILD_SERVER=deploy@217.154.175.68
#   deploy/deploy.sh
# Uses the SSH key ~/.ssh/ionos_ortsbild (change it with ORTSBILD_SSH_KEY).
#
# The image is built ON the server: the Mac has a different processor (ARM) than the Cube (x86).
# The secrets stay on the server: backend/.env is never copied, .env.prod lives only there.
set -euo pipefail

: "${ORTSBILD_SERVER:?set ORTSBILD_SERVER, e.g. export ORTSBILD_SERVER=deploy@217.154.175.68}"
KEY="${ORTSBILD_SSH_KEY:-$HOME/.ssh/ionos_ortsbild}"
SSH="ssh -i $KEY"
cd "$(dirname "$0")/.."

echo "== prepare the folders on the server"
$SSH "$ORTSBILD_SERVER" 'mkdir -p ~/ortsbild/backend ~/ortsbild/services/gateway ~/ortsbild/deploy && command -v rsync >/dev/null || { echo "rsync is missing on the server: sudo apt-get install -y rsync"; exit 1; }'

echo "== copy the backend (without secrets, logs and the virtual environment)"
rsync -az --delete -e "$SSH" \
    --exclude '.venv' --exclude '.env' --exclude 'logs' --exclude '__pycache__' \
    --exclude '.pytest_cache' --exclude 'THIRD_PARTY_NOTICES.md' \
    --exclude 'eval/faces' --exclude 'eval/seed' \
    backend/ "$ORTSBILD_SERVER:ortsbild/backend/"

echo "== copy the connector gateway (services/gateway/README.md)"
rsync -az --delete -e "$SSH" \
    --exclude '.venv' --exclude '.env' --exclude '__pycache__' --exclude '.pytest_cache' --exclude '.ruff_cache' \
    --exclude '*.egg-info' --exclude 'tests' \
    services/gateway/ "$ORTSBILD_SERVER:ortsbild/services/gateway/"

echo "== copy the map file of the dashboard (only if there is one, rsync sends nothing when it did not change)"
if [ -d tiles ]; then
    $SSH "$ORTSBILD_SERVER" 'mkdir -p ~/ortsbild/tiles'
    rsync -az --exclude '*.mbtiles' --exclude '*-journal' -e "$SSH" tiles/ "$ORTSBILD_SERVER:ortsbild/tiles/"
fi

echo "== copy the stack files"
rsync -az -e "$SSH" deploy/docker-compose.prod.yml deploy/Caddyfile "$ORTSBILD_SERVER:ortsbild/deploy/"

echo "== build and start (the first build takes a while)"
$SSH "$ORTSBILD_SERVER" 'cd ortsbild/deploy && test -f .env.prod || { echo "missing ~/ortsbild/deploy/.env.prod, create it from .env.prod.example"; exit 1; }; grep -q "^GATEWAY_KEY=..*" .env.prod || { echo "missing GATEWAY_KEY in ~/ortsbild/deploy/.env.prod, see .env.prod.example"; exit 1; }; docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build && docker compose --env-file .env.prod -f docker-compose.prod.yml ps'
