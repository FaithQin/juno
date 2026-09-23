#!/usr/bin/env bash
# Sync the project to the server and (re)start juno there.
#   scripts/deploy.sh root@SERVER_IP
# Copies code, config and .env. Copies data/ (sqlite + google token) only if the server has
# none yet, so the server's own state is never overwritten by a stale laptop copy.
set -euo pipefail
HOST="${1:?usage: scripts/deploy.sh user@host}"
DIR=/opt/juno
cd "$(dirname "$0")/.."

ssh "$HOST" "mkdir -p $DIR/data"
rsync -az --delete \
  --exclude .venv --exclude .git --exclude __pycache__ --exclude .pytest_cache --exclude .DS_Store --exclude data \
  ./ "$HOST:$DIR/"
if ! ssh "$HOST" "[ -f $DIR/data/assistant.sqlite3 ]"; then
  echo "first deploy: copying data/ (database + google token)"
  rsync -az ./data/ "$HOST:$DIR/data/"
fi
ssh "$HOST" "cd $DIR && docker compose up -d --build && sleep 3 && docker compose logs --tail=15 juno"
