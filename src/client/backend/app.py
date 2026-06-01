from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from re import sub
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse

from .runner import AnalysisRunner, validate_config_payload
from .schemas import (
    AnalysisSessionPayload,
    CreateSessionRequest,
    EnvSettingsResponse,
    LoadEnvFileRequest,
    RunSessionRequest,
    UpdateEnvSettingsRequest,
    UploadVmcoreResponse,
    ValidateConfigResponse,
    utc_now,
)
from .session_store import SessionStore
from .env_settings import env_status, load_client_env, load_existing_env_file, write_env_values


store = SessionStore()
runner = AnalysisRunner(store)
load_client_env()

app = FastAPI(title="agent4kdump client API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_ROOT = Path("cache/client_uploads/vmcore").resolve()
MAX_VMCORE_UPLOAD_BYTES = 128 * 1024 * 1024 * 1024


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/settings/env", response_model=EnvSettingsResponse)
def get_env_settings() -> EnvSettingsResponse:
    return EnvSettingsResponse(**env_status())


@app.put("/api/settings/env", response_model=EnvSettingsResponse)
def update_env_settings(request: UpdateEnvSettingsRequest) -> EnvSettingsResponse:
    return EnvSettingsResponse(**write_env_values(request.values))


@app.post("/api/settings/env/load", response_model=EnvSettingsResponse)
def load_env_file(request: LoadEnvFileRequest) -> EnvSettingsResponse:
    try:
        return EnvSettingsResponse(**load_existing_env_file(request.path))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to load .env file: {exc}") from exc


@app.get("/api/sessions", response_model=list[AnalysisSessionPayload])
def list_sessions() -> list[AnalysisSessionPayload]:
    return store.list_sessions()


@app.post("/api/sessions", response_model=AnalysisSessionPayload)
def create_session(request: CreateSessionRequest) -> AnalysisSessionPayload:
    return store.create_session(request)


@app.get("/api/sessions/{session_id}", response_model=AnalysisSessionPayload)
def get_session(session_id: str) -> AnalysisSessionPayload:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session


@app.post("/api/sessions/{session_id}/validate", response_model=ValidateConfigResponse)
def validate_session(session_id: str) -> ValidateConfigResponse:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    store.update_session(session_id, status="validating", error="")
    store.add_event(session_id, "config.validation_started", stage="config")
    ok, config, error = validate_config_payload(session.config)
    if ok:
        store.update_session(session_id, status="ready")
        store.add_event(session_id, "config.validated", stage="config", payload=config or {})
    else:
        store.update_session(session_id, status="failed", error=error or "Validation failed.")
        store.add_event(
            session_id,
            "error",
            stage="config",
            payload={"message": error or "Validation failed."},
        )
    return ValidateConfigResponse(ok=ok, config=config, error=error)


@app.post("/api/config/validate", response_model=ValidateConfigResponse)
def validate_config(request: CreateSessionRequest) -> ValidateConfigResponse:
    ok, config, error = validate_config_payload(request.config)
    return ValidateConfigResponse(ok=ok, config=config, error=error)


@app.post("/api/uploads/vmcore", response_model=UploadVmcoreResponse)
async def upload_vmcore(file: UploadFile = File(...)) -> UploadVmcoreResponse:
    raw_name = Path(file.filename or "vmcore").name
    safe_name = sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._") or "vmcore"
    upload_id = uuid4().hex[:12]
    target_dir = UPLOAD_ROOT / upload_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = (target_dir / safe_name).resolve()

    if UPLOAD_ROOT not in target_path.parents:
        raise HTTPException(status_code=400, detail="Invalid upload target path.")

    size = 0
    try:
        with target_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_VMCORE_UPLOAD_BYTES:
                    target_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="vmcore upload is too large.")
                output.write(chunk)
    finally:
        await file.close()

    if size == 0:
        target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded vmcore is empty.")

    return UploadVmcoreResponse(filename=safe_name, stored_path=str(target_path), size=size)


@app.post("/api/sessions/{session_id}/run", response_model=AnalysisSessionPayload)
def run_session(session_id: str, request: RunSessionRequest | None = None) -> AnalysisSessionPayload:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    try:
        runner.run(session_id, dry_run=bool(request and request.dry_run))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    updated = store.get_session(session_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return updated


@app.post("/api/sessions/{session_id}/cancel", response_model=AnalysisSessionPayload)
def cancel_session(session_id: str) -> AnalysisSessionPayload:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    store.cancel(session_id)
    if session.status in {"created", "validating", "ready"}:
        session = store.update_session(session_id, status="cancelled")
        store.add_event(session_id, "session.cancelled")
    elif session.status == "running":
        runner.force_stop(session_id)
        session = store.update_session(session_id, status="cancelled", finished_at=utc_now())
        store.add_event(session_id, "session.cancelled")
    return session


@app.get("/api/sessions/{session_id}/report", response_class=PlainTextResponse)
def get_report(session_id: str) -> str:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session.results.report_markdown or ""


@app.get("/api/sessions/{session_id}/events")
async def session_events(session_id: str) -> StreamingResponse:
    if store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    async def event_stream() -> AsyncIterator[str]:
        offset = 0
        while True:
            events, offset = store.events_since(session_id, offset)
            for event in events:
                payload = event.model_dump()
                yield f"id: {event.id}\ndata: {json.dumps(payload)}\n\n"

            session = store.get_session(session_id)
            if session and session.status in {"completed", "failed", "cancelled"}:
                final_events, offset = store.events_since(session_id, offset)
                for event in final_events:
                    payload = event.model_dump()
                    yield f"id: {event.id}\ndata: {json.dumps(payload)}\n\n"
                break
            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
