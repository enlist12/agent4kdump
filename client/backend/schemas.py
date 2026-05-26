from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


SessionStatus = Literal[
    "created",
    "validating",
    "ready",
    "running",
    "completed",
    "failed",
    "cancelled",
]


class AnalysisConfigPayload(BaseModel):
    config_path: str | None = None
    linux_path: str | None = None
    gdb_path: str | None = None
    vmcore: str | None = None
    kdump_server: str | None = None
    enable_rag: bool = False
    build_codequery: bool = True
    rag_cache_dir: str | None = None
    kdump_host: str = "127.0.0.1"
    kdump_port: int = 1234
    kdump_args: list[str] | None = None


class CreateSessionRequest(BaseModel):
    name: str | None = None
    config: AnalysisConfigPayload = Field(default_factory=AnalysisConfigPayload)


class SessionResultPayload(BaseModel):
    parsed_search: dict[str, Any] | None = None
    parsed_analyze: dict[str, Any] | None = None
    pageindex_status: dict[str, Any] | None = None
    report_markdown: str | None = None


class AnalysisSessionPayload(BaseModel):
    id: str
    name: str
    status: SessionStatus
    config: AnalysisConfigPayload
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    results: SessionResultPayload = Field(default_factory=SessionResultPayload)


class AnalysisEventPayload(BaseModel):
    id: str
    session_id: str
    type: str
    stage: str | None = None
    timestamp: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ValidateConfigResponse(BaseModel):
    ok: bool
    config: dict[str, Any] | None = None
    error: str | None = None


class RunSessionRequest(BaseModel):
    dry_run: bool = False


class UploadVmcoreResponse(BaseModel):
    filename: str
    stored_path: str
    size: int


class EnvVarStatus(BaseModel):
    configured: bool
    masked: str


class EnvSettingsResponse(BaseModel):
    path: str
    values: dict[str, EnvVarStatus]


class UpdateEnvSettingsRequest(BaseModel):
    values: dict[str, str | None]


class LoadEnvFileRequest(BaseModel):
    path: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
