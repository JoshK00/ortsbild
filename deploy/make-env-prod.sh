#!/usr/bin/env bash
# Create ~/ortsbild/deploy/.env.prod on the server from backend/.env. Run it on your Mac:
#   export ORTSBILD_SERVER=deploy@217.154.175.68
#   deploy/make-env-prod.sh
# Nothing secret is printed. An existing file on the server is NEVER overwritten, because a new
# PSEUDONYM_SECRET would break the link between the reporters and their pseudonyms.
set -euo pipefail

: "${ORTSBILD_SERVER:?set ORTSBILD_SERVER, e.g. export ORTSBILD_SERVER=deploy@217.154.175.68}"
KEY="${ORTSBILD_SSH_KEY:-$HOME/.ssh/ionos_ortsbild}"
cd "$(dirname "$0")/.."

python3 deploy/make_env_prod.py --check

python3 deploy/make_env_prod.py | ssh -i "$KEY" "$ORTSBILD_SERVER" '
    set -e
    umask 077
    mkdir -p ~/ortsbild/deploy
    if [ -e ~/ortsbild/deploy/.env.prod ]; then
        echo "~/ortsbild/deploy/.env.prod already exists, not overwriting it" >&2
        exit 1
    fi
    cat > ~/ortsbild/deploy/.env.prod
    chmod 600 ~/ortsbild/deploy/.env.prod
    echo "created ~/ortsbild/deploy/.env.prod ($(wc -l < ~/ortsbild/deploy/.env.prod) lines, only you can read it)"
'
