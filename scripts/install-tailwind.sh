#!/usr/bin/env bash
# Download Tailwind Standalone CLI binary (no Node/npm dependency).
# Pinned to v3.4.13 for reproducibility.
set -euo pipefail

VERSION="v3.4.13"
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)

case "$ARCH" in
  x86_64)  ARCH="x64" ;;
  aarch64|arm64) ARCH="arm64" ;;
  *) echo "Unsupported arch: $ARCH" >&2; exit 1 ;;
esac

case "$OS" in
  linux)   OS_TAG="linux" ;;
  darwin)  OS_TAG="macos" ;;
  *) echo "Unsupported OS: $OS" >&2; exit 1 ;;
esac

URL="https://github.com/tailwindlabs/tailwindcss/releases/download/${VERSION}/tailwindcss-${OS_TAG}-${ARCH}"
TARGET="$(dirname "$0")/../tools/tailwindcss"

mkdir -p "$(dirname "$TARGET")"
echo "Downloading Tailwind ${VERSION} for ${OS}-${ARCH}…"
curl -sL --fail -o "$TARGET" "$URL"
chmod +x "$TARGET"
echo "✓ Installed: $(realpath "$TARGET")"
"$TARGET" --help | head -3
