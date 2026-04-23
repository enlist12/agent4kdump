from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


RunMode = Literal["live", "replay"]
RunStage = Literal["config", "kdump_init", "search", "rag", "analyze", "persist", "completed"]
RunStatus = Literal["queued", "running", "completed", "failed", "canceled"]


class ConfigOverride(BaseModel):
    linux_path: Optional[str] = None
    gdb_path: Optional[str] = None
    vmcore: Optional[str] = None
    kdump_server: Optional[str] = None
    syzbot_data: Optional[str] = None
    enable_rag: Optional[bool] = None


class RunRequest(BaseModel):
    mode: RunMode = "live"
    case_id: Optional[str] = None
    experience_id: Optional[str] = None
    label: Optional[str] = None
    config_override: ConfigOverride = Field(default_factory=ConfigOverride)


class RunEvent(BaseModel):
    id: int
    run_id: str
    timestamp: datetime
    stage: Optional[RunStage] = None
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class RunSummary(BaseModel):
    id: str
    mode: RunMode
    label: str
    status: RunStatus
    current_stage: Optional[RunStage] = None
    created_at: datetime
    updated_at: datetime
    case_id: Optional[str] = None
    experience_id: Optional[str] = None
    error: Optional[str] = None


class RunDetail(RunSummary):
    events: List[RunEvent] = Field(default_factory=list)
    artifacts: Dict[str, Any] = Field(default_factory=dict)


class CaseRecordView(BaseModel):
    case_id: str
    path: str
    vmcore_path: Optional[str] = None
    poc_path: Optional[str] = None
    poc_source_path: Optional[str] = None
    config_path: Optional[str] = None
    has_vmcore: bool
    has_poc: bool
    has_config: bool
    file_count: int
    updated_at: Optional[datetime] = None
    poc_preview: Optional[str] = None
    config_preview: Optional[str] = None


class ExperienceRecordView(BaseModel):
    case_id: str
    created_at: Optional[datetime] = None
    summary: str = ""
    root_cause: str = ""
    trigger_path: str = ""
    confidence: str = "unknown"
    keywords: List[str] = Field(default_factory=list)
    kernel_version: Optional[str] = None
    bug_type: Optional[str] = None
    driver_candidates: List[str] = Field(default_factory=list)
    markdown_path: Optional[str] = None


class ExperienceDetailView(ExperienceRecordView):
    lessons: Dict[str, Any] = Field(default_factory=dict)
    trace_summary: Dict[str, Any] = Field(default_factory=dict)
    analysis_result: Dict[str, Any] = Field(default_factory=dict)
    retrieved_context: Dict[str, Any] = Field(default_factory=dict)
    retrieval_text: str = ""
    markdown_content: str = ""


class ProjectModuleView(BaseModel):
    name: str
    description: str
    path: str
    children: List["ProjectModuleView"] = Field(default_factory=list)


class ProjectOverviewView(BaseModel):
    root_path: str
    config_path: str
    total_cases: int
    total_experiences: int
    syzbot_bug_files: int
    rag_status: Dict[str, Any] = Field(default_factory=dict)
    workflow: List[Dict[str, str]] = Field(default_factory=list)
    modules: List[ProjectModuleView] = Field(default_factory=list)


ProjectModuleView.model_rebuild()
