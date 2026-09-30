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

# The backend is stdlib-only today. If runtime dependencies are added later,
# bundle them here: Decky's frozen Python cannot use local site-packages.
"${PYTHON:-python3}" - "$PLUGIN_DIR/pyproject.toml" "$STAGE/py_modules" <<'PY'
import subprocess
import sys
import tomllib

with open(sys.argv[1], "rb") as project_file:
    dependencies = tomllib.load(project_file)["project"]["dependencies"]
if dependencies:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
         "--only-binary=:all:", "--target", sys.argv[2], *dependencies],
        check=True,
    )
PY

find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$STAGE" -name '*.pyc' -delete
rm -f "$STAGE/dist/index.js.map"
