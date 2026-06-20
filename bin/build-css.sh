#!/usr/bin/env bash
set -euo pipefail
BIN=/usr/local/bin/tailwindcss
if [ ! -x "$BIN" ]; then
  echo "Fetching Tailwind standalone CLI…"
  python3 -c "import urllib.request; urllib.request.urlretrieve('https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-linux-x64', '$BIN')"
  chmod +x "$BIN"
fi
MODE="${1:-build}"
if [ "$MODE" = "watch" ]; then
  exec "$BIN" -c tailwind.config.js -i static/css/input.css -o static/css/app.css --watch
else
  "$BIN" -c tailwind.config.js -i static/css/input.css -o static/css/app.css --minify
fi
