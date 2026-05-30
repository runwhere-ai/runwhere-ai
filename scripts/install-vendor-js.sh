#!/usr/bin/env bash
# Download vendored JS assets (htmx, htmx-ws ext, alpine.js).
# Pinned versions for reproducibility. Uses parallel arrays for bash 3.2 compat.
set -euo pipefail

HTMX_VERSION="2.0.3"
ALPINE_VERSION="3.14.1"

DEST="$(dirname "$0")/../static/js"
mkdir -p "$DEST"

NAMES=(
  "htmx.min.js"
  "htmx-ext-ws.min.js"
  "alpine.min.js"
)
URLS=(
  "https://unpkg.com/htmx.org@${HTMX_VERSION}/dist/htmx.min.js"
  "https://unpkg.com/htmx-ext-ws@2.0.1/ws.js"
  "https://unpkg.com/alpinejs@${ALPINE_VERSION}/dist/cdn.min.js"
)

for i in "${!NAMES[@]}"; do
  name="${NAMES[$i]}"
  url="${URLS[$i]}"
  echo "Downloading ${name}…"
  curl -sL --fail --max-time 60 -o "${DEST}/${name}" "${url}"
  echo "  ✓ ${DEST}/${name} ($(wc -c <"${DEST}/${name}") bytes)"
done

echo "✓ All vendored JS assets installed."
