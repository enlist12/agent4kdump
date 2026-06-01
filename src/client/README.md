# agent4kdump Client

Tauri desktop client for `agent4kdump`.

The client is distributed as a desktop application. It provides configuration validation, session management, `vmcore` upload, analysis execution and report viewing in one packaged workflow.

## Build

Build on Linux or WSL:

```bash
cd src/client
npm install
npm run build:linux
```

Equivalent command from the repository root:

```bash
bash src/client/scripts/build-linux.sh
```

The build script packages the local analysis runtime under `build/client/`, builds the Tauri application and copies release artifacts to `build/client/release/`:

```text
build/client/release/agent4kdump-client-linux-x64
build/client/release/agent4kdump-client-linux-x64.AppImage
build/client/release/agent4kdump-client-linux-x64.deb
```

## Requirements

- Linux or WSL
- Node.js and npm
- Rust and Cargo
- `uv`
- Tauri Linux native dependencies, including WebKitGTK, AppIndicator, OpenSSL and librsvg

Linux desktop bundles are not expected to build reliably from a native Windows host because Tauri depends on Linux WebKitGTK and packaging toolchains.

## Runtime Notes

- `vmcore` can be selected by server-side path or uploaded through the desktop client.
- Uploaded files are stored under `cache/client_uploads/vmcore/<upload_id>/`.
- The Settings page can load or update the local `.env` used by analysis runs.
- Supported keys include `API_KEY`, `MODEL_NAME`, `MODEL_PROVIDER`, `LLM_BASE_URL`, `TAVILY_API_KEY`, `LANGFUSE_*`, `PAGEINDEX_API_KEY`, `OPENAI_API_KEY` and `OPENAI_API_BASE`.
