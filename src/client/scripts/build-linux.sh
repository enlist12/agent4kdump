#!/usr/bin/env bash
set -euo pipefail

CLIENT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "${CLIENT_ROOT}/../.." && pwd)"
CLIENT_BUILD_DIR="${REPO_ROOT}/build/client"
DIST_DIR="${CLIENT_BUILD_DIR}/release"
BACKEND_DIST="${CLIENT_BUILD_DIR}/backend-dist"
PYINSTALLER_BUILD="${CLIENT_BUILD_DIR}/pyinstaller"
TAURI_TARGET="${CLIENT_BUILD_DIR}/tauri-target"

mkdir -p "${DIST_DIR}" "${BACKEND_DIST}" "${PYINSTALLER_BUILD}" "${TAURI_TARGET}"

command -v uv >/dev/null 2>&1 || { echo "uv is required for backend packaging." >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "npm is required for frontend packaging." >&2; exit 1; }

echo "Building kdump dependencies..."
bash "${REPO_ROOT}/scripts/build-kdump-deps.sh"

(
  cd "${REPO_ROOT}"
  chmod +x "${REPO_ROOT}/kdump_analyze/kdump-gdbserver/kdump-gdbserver" || true
  
  # Determine the command to run PyInstaller
  PYINSTALLER_CMD="pyinstaller"
  if command -v uv >/dev/null 2>&1 && [[ -z "${CONDA_PREFIX:-}" ]]; then
      echo "Using 'uv run' for PyInstaller..."
      PYINSTALLER_CMD="uv run --with pyinstaller pyinstaller"
  else
      echo "Using local environment PyInstaller (Conda detected or uv missing)..."
  fi

  $PYINSTALLER_CMD \
    --noconfirm \
    --distpath "${BACKEND_DIST}" \
    --workpath "${PYINSTALLER_BUILD}" \
    "${REPO_ROOT}/agent4kdump-backend.spec"
)

(
  cd "${CLIENT_ROOT}"
  npm install
  export CARGO_TARGET_DIR="${TAURI_TARGET}"
  npm run desktop:build
)

if [[ -f "${TAURI_TARGET}/release/agent4kdump-client" ]]; then
  cp "${TAURI_TARGET}/release/agent4kdump-client" \
    "${DIST_DIR}/agent4kdump-client-linux-x64"
fi

if [[ -f "${TAURI_TARGET}/release/bundle/appimage/agent4kdump-client_0.1.0_amd64.AppImage" ]]; then
  cp "${TAURI_TARGET}/release/bundle/appimage/agent4kdump-client_0.1.0_amd64.AppImage" \
    "${DIST_DIR}/agent4kdump-client-linux-x64.AppImage"
fi

if [[ -f "${TAURI_TARGET}/release/bundle/deb/agent4kdump-client_0.1.0_amd64.deb" ]]; then
  cp "${TAURI_TARGET}/release/bundle/deb/agent4kdump-client_0.1.0_amd64.deb" \
    "${DIST_DIR}/agent4kdump-client-linux-x64.deb"
fi

ls -lh "${DIST_DIR}"
