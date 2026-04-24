#!/usr/bin/env bash

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

cd "${ROOT_DIR}" || exit 1
pipreqs . --force --ignore ./codequery,./kernel/,./kdump_analyze/crash-9.0.0,./kdump_analyze/libkdumpfile,./kdump_analyze/pykdumpfile
