#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-linux}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "${REPO_ROOT}/dist"

build_linux() {
  if [[ "$(uname -s)" != Linux* ]]; then
    echo "Linux packaging must be run from Linux or WSL." >&2
    exit 1
  fi
  (cd "${REPO_ROOT}/client" && bash scripts/build-linux.sh)
}

case "${TARGET}" in
  linux)
    build_linux
    ;;
  *)
    echo "Usage: ./build.sh [linux]" >&2
    exit 2
    ;;
esac

echo
echo "Build artifacts:"
ls -lh "${REPO_ROOT}/dist"
