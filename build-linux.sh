#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "${REPO_ROOT}/src/client/scripts/build-linux.sh"
