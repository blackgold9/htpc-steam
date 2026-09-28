#!/usr/bin/env bash
# Stages the same self-contained files as the sideload zip, syncs them into
# ~/homebrew/plugins/ over SSH, and restarts Decky's plugin_loader.
#
# Usage: DECK_HOST=my-bazzite.local [DECK_USER=deck] [DECK_PORT=22] ./scripts/deploy.sh
# DECK_USER is whoever owns ~/homebrew on the target (Bazzite's default user if
# Homebrew was installed by them, not `deck`). Prompts twice for sudo: the
# plugin dir is root-owned, and plugin_loader re-chowns it on every load.
set -euo pipefail

DECK_HOST="${DECK_HOST:?set DECK_HOST to the target hostname or IP}"
DECK_USER="${DECK_USER:-deck}"
DECK_PORT="${DECK_PORT:-22}"
PLUGIN_NAME="uc-steamos-agent"
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_PLUGIN_DIR="homebrew/plugins/${PLUGIN_NAME}"

if [ ! -s "$PLUGIN_DIR/dist/index.js" ]; then
  echo "dist/index.js missing — run 'pnpm build' in $PLUGIN_DIR first." >&2
  exit 1
fi

STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGE_DIR"' EXIT
bash "$PLUGIN_DIR/scripts/stage.sh" "$STAGE_DIR/$PLUGIN_NAME"

# plugin_loader re-asserts root ownership of a plugin's directory each time
# it (re)loads it (e.g. after a restart or reboot), so this has to run
# before every deploy, not just once — matches the official decky-plugin-template
# VSCode tasks' chmodplugins step.
echo "Ensuring $REMOTE_PLUGIN_DIR is writable..."
ssh -t -p "$DECK_PORT" "$DECK_USER@$DECK_HOST" \
  "sudo mkdir -p ~/$REMOTE_PLUGIN_DIR && sudo chown -R $DECK_USER:$DECK_USER ~/$REMOTE_PLUGIN_DIR"

echo "Syncing packaged plugin -> $DECK_USER@$DECK_HOST:$REMOTE_PLUGIN_DIR"
rsync -azp --delete \
  --exclude 'py_modules/.lock' \
  --rsh="ssh -p $DECK_PORT" \
  "$STAGE_DIR/$PLUGIN_NAME"/ "$DECK_USER@$DECK_HOST:$REMOTE_PLUGIN_DIR/"

echo "Restarting Decky's plugin_loader service..."
ssh -t -p "$DECK_PORT" "$DECK_USER@$DECK_HOST" "sudo systemctl restart plugin_loader"

echo "Done. Check the Quick Access Menu for '$PLUGIN_NAME'."
