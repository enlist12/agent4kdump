from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from webapp.backend.models import ExperienceDetailView, ExperienceRecordView, RunDetail, RunRequest, RunSummary
from webapp.backend.repository import ProjectRepository
from webapp.backend.runtime import RunManager


repository = ProjectRepository(ROOT_DIR)
run_manager = RunManager(ROOT_DIR, repository)

app = FastAPI(
    title="Agent4Kdump Visualization API",
    version="0.1.0",
    description="Visualization backend for kernel kdump vulnerability root-cause analysis.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/runs", response_model=RunSummary)
def create_run(request: RunRequest) -> RunSummary:
    try:
        return run_manager.create_run(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/runs", response_model=list[RunSummary])
def list_runs() -> list[RunSummary]:
    return run_manager.list_runs()


@app.get("/api/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: str) -> RunDetail:
    detail = run_manager.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return detail


@app.post("/api/runs/{run_id}/stop", response_model=RunSummary)
def stop_run(run_id: str) -> RunSummary:
    try:
        return run_manager.stop_run(run_id)
    except RuntimeError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/artifacts")
def get_run_artifacts(run_id: str) -> dict:
    detail = run_manager.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return detail.artifacts


@app.get("/api/runs/{run_id}/events")
async def stream_run_events(run_id: str, after: int = 0) -> StreamingResponse:
    if run_manager.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_stream() -> AsyncIterator[str]:
        last_event_id = after
        while True:
            events, status = run_manager.event_slice(run_id, after_id=last_event_id)
            if events:
                for event in events:
                    payload = event.model_dump(mode="json")
                    yield f"id: {event.id}\n"
                    yield f"event: {event.type}\n"
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    last_event_id = event.id
            elif status in {"completed", "failed", "canceled"}:
                break
            await asyncio.sleep(0.6)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/cases")
def list_cases() -> list[dict]:
    return [item.model_dump(mode="json") for item in repository.list_cases()]


@app.get("/api/cases/{case_id}")
def get_case(case_id: str) -> dict:
    record = repository.get_case(case_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return record.model_dump(mode="json")


@app.get("/api/experience", response_model=list[ExperienceRecordView])
def list_experience() -> list[ExperienceRecordView]:
    return repository.list_experiences()


@app.get("/api/experience/{case_id}", response_model=ExperienceDetailView)
def get_experience(case_id: str) -> ExperienceDetailView:
    record = repository.get_experience(case_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Experience not found")
    return record


@app.get("/api/project/overview")
def get_project_overview() -> dict:
    return repository.build_project_overview().model_dump(mode="json")


@app.get("/api/project/tree")
def get_project_tree() -> list[dict]:
    return repository.build_project_tree()


frontend_dist = ROOT_DIR / "webapp" / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:
    @app.get("/", response_class=HTMLResponse)
    def frontend_placeholder() -> str:
        return """
        <html>
          <body style="font-family: sans-serif; padding: 32px;">
            <h1>Agent4Kdump Visualization Backend</h1>
            <p>Frontend build assets were not found. Start the Vite frontend in <code>webapp/frontend</code>.</p>
          </body>
        </html>
        """
