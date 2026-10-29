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
$SSH "$ORTSBILD_SERVER" 'mkdir -p ~/ortsbild/backend ~/ortsbild/deploy && command -v rsync >/dev/null || { echo "rsync is missing on the server: sudo apt-get install -y rsync"; exit 1; }'

echo "== copy the backend (without secrets, logs and the virtual environment)"
rsync -az --delete -e "$SSH" \
    --exclude '.venv' --exclude '.env' --exclude 'logs' --exclude '__pycache__' \
    --exclude '.pytest_cache' --exclude 'THIRD_PARTY_NOTICES.md' \
    backend/ "$ORTSBILD_SERVER:ortsbild/backend/"

echo "== copy the stack files"
rsync -az -e "$SSH" deploy/docker-compose.prod.yml deploy/Caddyfile "$ORTSBILD_SERVER:ortsbild/deploy/"

echo "== build and start (the first build takes a while)"
$SSH "$ORTSBILD_SERVER" 'cd ortsbild/deploy && test -f .env.prod || { echo "missing ~/ortsbild/deploy/.env.prod, create it from .env.prod.example"; exit 1; }; docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build && docker compose --env-file .env.prod -f docker-compose.prod.yml ps'
