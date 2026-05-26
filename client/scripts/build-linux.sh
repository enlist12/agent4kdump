#!/usr/bin/env bash
set -euo pipefail

CLIENT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "${CLIENT_ROOT}/.." && pwd)"
DIST_DIR="${REPO_ROOT}/dist"
BACKEND_DIST="${CLIENT_ROOT}/backend-dist"

mkdir -p "${DIST_DIR}" "${BACKEND_DIST}"

command -v uv >/dev/null 2>&1 || { echo "uv is required for backend packaging." >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "npm is required for frontend packaging." >&2; exit 1; }

(
  cd "${REPO_ROOT}"
  chmod +x "${REPO_ROOT}/kdump_analyze/kdump-gdbserver/kdump-gdbserver" || true
  uv run --with pyinstaller pyinstaller \
    --noconfirm \
    --onefile \
    --name agent4kdump-backend \
    --paths "${REPO_ROOT}" \
    --collect-submodules src \
    --collect-submodules agents \
    --collect-submodules client \
    --add-data "${REPO_ROOT}/kdump_analyze:kdump_analyze" \
    --add-data "${REPO_ROOT}/.env:." \
    --distpath "${BACKEND_DIST}" \
    --workpath "${CLIENT_ROOT}/build/pyinstaller" \
    "${CLIENT_ROOT}/backend/entry.py"
)

(
  cd "${CLIENT_ROOT}"
  npm install
  npm run desktop:build
)

if [[ -f "${CLIENT_ROOT}/src-tauri/target/release/agent4kdump-client" ]]; then
  cp "${CLIENT_ROOT}/src-tauri/target/release/agent4kdump-client" \
    "${DIST_DIR}/agent4kdump-client-linux-x64"
fi

if [[ -f "${CLIENT_ROOT}/src-tauri/target/release/bundle/appimage/agent4kdump-client_0.1.0_amd64.AppImage" ]]; then
  cp "${CLIENT_ROOT}/src-tauri/target/release/bundle/appimage/agent4kdump-client_0.1.0_amd64.AppImage" \
    "${DIST_DIR}/agent4kdump-client-linux-x64.AppImage"
fi

if [[ -f "${CLIENT_ROOT}/src-tauri/target/release/bundle/deb/agent4kdump-client_0.1.0_amd64.deb" ]]; then
  cp "${CLIENT_ROOT}/src-tauri/target/release/bundle/deb/agent4kdump-client_0.1.0_amd64.deb" \
    "${DIST_DIR}/agent4kdump-client-linux-x64.deb"
fi

ls -lh "${DIST_DIR}"
