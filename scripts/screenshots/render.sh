#!/bin/sh
# Renders the README screenshots from made-up data in headless Chromium; needs Docker and a built panel.
set -eu
cd "$(dirname "$0")/../.."
test -s custom_components/notification_journal/frontend/panel.js || { echo "build the panel first" >&2; exit 1; }
mkdir -p docs/screenshots
docker run --rm --log-driver none --ipc=host \
  -v "$PWD/scripts/screenshots:/src:ro" \
  -v "$PWD/custom_components/notification_journal/frontend/panel.js:/src-panel/panel.js:ro" \
  -v "$PWD/docs/screenshots:/work/out" \
  mcr.microsoft.com/playwright:v1.65.0-noble \
  sh -c 'cd /work && cp /src/readme.html /src/readme-data.js /src/render.mjs /src-panel/panel.js . && npm i -s --no-audit --no-fund playwright@1.65.0 >/dev/null && node render.mjs'
