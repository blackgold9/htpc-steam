#!/usr/bin/env bash
# Assemble the same self-contained plugin directory for sideload releases and SSH deploys.
set -euo pipefail

STAGE="${1:?usage: stage.sh DESTINATION}"
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -s "$PLUGIN_DIR/dist/index.js" ]; then
  echo "dist/index.js missing — build the frontend first." >&2
  exit 1
fi

if [ -e "$STAGE" ]; then
  echo "Staging destination already exists: $STAGE" >&2
  exit 1
fi

mkdir -p "$STAGE/py_modules"
cp -r \
  "$PLUGIN_DIR/plugin.json" \
  "$PLUGIN_DIR/package.json" \
  "$PLUGIN_DIR/main.py" \
  "$PLUGIN_DIR/dist" \
  "$PLUGIN_DIR/LICENSE" \
  "$PLUGIN_DIR/README.md" \
  "$STAGE/"
cp -r "$PLUGIN_DIR/py_modules/uc_steamos_agent" "$STAGE/py_modules/"

find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$STAGE" -name '*.pyc' -delete
rm -f "$STAGE/dist/index.js.map"
