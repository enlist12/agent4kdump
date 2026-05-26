#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$(uname -s)" != Linux* ]]; then
  echo "Run this script from Linux or WSL." >&2
  exit 1
fi

if [[ "${1:-}" == "--install-system-deps" ]]; then
  sudo apt-get update
  sudo apt-get install -y \
    build-essential \
    curl \
    file \
    libayatana-appindicator3-dev \
    libgtk-3-dev \
    libjavascriptcoregtk-4.0-dev \
    librsvg2-dev \
    libsoup2.4-dev \
    libssl-dev \
    libwebkit2gtk-4.0-dev \
    patchelf \
    pkg-config \
    python3 \
    python3-venv \
    wget
fi

chmod +x "${REPO_ROOT}/kdump_analyze/kdump-gdbserver/kdump-gdbserver"
export AGENT4KDUMP_ROOT="${REPO_ROOT}"
bash "${REPO_ROOT}/build.sh" linux
