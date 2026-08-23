#!/usr/bin/env bash
# Syncs this plugin directly into ~/homebrew/plugins/ over SSH and restarts
# Decky's plugin_loader — the fast dev-loop path, not the store-distribution
# zip (that's `decky plugin build`, for Phase 5 packaging).
#
# Usage: DECK_HOST=my-bazzite.local [DECK_USER=deck] [DECK_PORT=22] ./scripts/deploy.sh
set -euo pipefail

DECK_HOST="${DECK_HOST:?set DECK_HOST to the target hostname or IP}"
DECK_USER="${DECK_USER:-deck}"
DECK_PORT="${DECK_PORT:-22}"
PLUGIN_NAME="uc-steamos-agent"
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_PLUGIN_DIR="homebrew/plugins/${PLUGIN_NAME}"

if [ ! -f "$PLUGIN_DIR/dist/index.js" ]; then
  echo "dist/index.js missing — run 'pnpm build' in $PLUGIN_DIR first." >&2
  exit 1
fi

echo "Syncing $PLUGIN_DIR -> $DECK_USER@$DECK_HOST:$REMOTE_PLUGIN_DIR"
ssh -p "$DECK_PORT" "$DECK_USER@$DECK_HOST" "mkdir -p ~/$REMOTE_PLUGIN_DIR"
rsync -azp --delete \
  --exclude 'node_modules' --exclude '.git' --exclude 'src' --exclude 'tests' --exclude 'cli' \
  --rsh="ssh -p $DECK_PORT" \
  "$PLUGIN_DIR"/ "$DECK_USER@$DECK_HOST:$REMOTE_PLUGIN_DIR/"

echo "Restarting Decky's plugin_loader service..."
ssh -p "$DECK_PORT" "$DECK_USER@$DECK_HOST" "sudo systemctl restart plugin_loader"

echo "Done. Check the Quick Access Menu for '$PLUGIN_NAME'."
