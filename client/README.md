# agent4kdump Complete Client

Complete desktop client for `agent4kdump`.

The client contains:

- `app/`: React + Vite workstation UI
- `backend/`: local FastAPI API service
- `src-tauri/`: Tauri desktop shell
- `scripts/`: Linux build scripts

## VMCore upload

The New Session panel supports two vmcore input modes:

- upload a local vmcore through `POST /api/uploads/vmcore`
- type a server-side vmcore path directly

Uploaded files are streamed to `cache/client_uploads/vmcore/<upload_id>/` and the returned path is used as `config.vmcore`.

## API key configuration

The Settings page writes allowlisted model/search/RAG keys into the local `.env`
used by the backend. Values are masked when displayed back to the UI.

The Settings page can also load an existing `.env` file. The selected path is
persisted in `cache/client_settings.json`, and the backend reloads that file
before config validation and analysis runs.

Supported keys include:

- `API_KEY`
- `MODEL_NAME`
- `MODEL_PROVIDER`
- `LLM_BASE_URL`
- `TAVILY_API_KEY`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_HOST`
- `PAGEINDEX_API_KEY`
- `OPENAI_API_KEY`
- `OPENAI_API_BASE`
- `DEEPSEEK_API_KEY`
- `MODEL_TEMPERATURE`
- `MAX_RECURSION_DEPTH`
- `SHELL_TOOL_WORKSPACE_ROOT`

## Linux build

Run on Linux with Rust, Node.js, uv and the Tauri Linux system dependencies installed:

```bash
./build-linux-wsl.sh
```

Use `./build-linux-wsl.sh --install-system-deps` on Debian/Ubuntu/WSL if the
native Tauri packages are not installed yet.

Outputs:

```text
dist/agent4kdump-client-linux-x64
dist/agent4kdump-client-linux-x64.AppImage
dist/agent4kdump-client-linux-x64.deb
```

Linux bundles cannot be produced reliably from the current Windows host because Tauri depends on native Linux WebKitGTK and packaging toolchains.

## Runtime

On startup, the Tauri shell tries this order:

1. Connect to an existing `127.0.0.1:8000` API service.
2. Start bundled `agent4kdump-backend`.
3. Fall back to `uv run uvicorn client.backend.app:app --host 127.0.0.1 --port 8000` when running from a development checkout.
