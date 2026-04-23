from __future__ import annotations

import json
import logging
import threading
import uuid
from contextlib import contextmanager
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import io
import re
from typing import Any, Dict, Iterator, Optional

from pydantic import BaseModel

from agent_core.tools.codeQuery.codequery import create_cq_db, set_proj_path
from agent_core.tools.fileTools import set_linux_path
from agent_core.tools.gdbTools import getCrashReport, set_kdump_analysis_instance
from agents.analyze_agent import runAnalyzeAgent
from agents.rag import AnalysisRAGManager
from agents.search_agent import KnownBugAnalysisResult, parse_search_results, runSearchAgent
from kdump_analyze.kdump import KdumpAnalysis

from .models import RunDetail, RunEvent, RunRequest, RunStatus, RunSummary
from .repository import ProjectRepository

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


@dataclass
class RunRecord:
    id: str
    request: RunRequest
    label: str
    created_at: datetime
    updated_at: datetime
    status: RunStatus = "queued"
    current_stage: Optional[str] = None
    events: list[RunEvent] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    stop_requested: bool = False
    thread: Optional[threading.Thread] = None
    kdump_analysis: Any = None
    last_log_signature: Optional[tuple[str, str, str, Optional[str]]] = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def to_summary(self) -> RunSummary:
        return RunSummary(
            id=self.id,
            mode=self.request.mode,
            label=self.label,
            status=self.status,
            current_stage=self.current_stage,
            created_at=self.created_at,
            updated_at=self.updated_at,
            case_id=self.request.case_id,
            experience_id=self.request.experience_id,
            error=self.error,
        )

    def to_detail(self) -> RunDetail:
        return RunDetail(**self.to_summary().model_dump(), events=list(self.events), artifacts=_json_safe(self.artifacts))


class _RunLogHandler(logging.Handler):
    def __init__(self, manager: "RunManager", run: RunRecord) -> None:
        super().__init__(level=logging.INFO)
        self.manager = manager
        self.run = run

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        self.manager.emit(
            self.run,
            "log",
            payload={
                "logger": record.name,
                "level": record.levelname,
                "message": message,
            },
            stage=self.run.current_stage,
        )


class _EventStreamWriter(io.TextIOBase):
    def __init__(self, manager: "RunManager", run: RunRecord, stream_name: str) -> None:
        self.manager = manager
        self.run = run
        self.stream_name = stream_name
        self._buffer = ""

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit_line(line)
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            self._emit_line(self._buffer)
            self._buffer = ""

    def _emit_line(self, line: str) -> None:
        message = line.rstrip()
        if not message:
            return
        plain_message = ANSI_ESCAPE_RE.sub("", message)
        if self.stream_name == "stderr" and re.match(r"^(INFO|WARNING|ERROR) - [^ ]+ - ", plain_message):
            return
        self.manager.emit(
            self.run,
            "log",
            payload={
                "logger": self.stream_name,
                "level": "INFO" if self.stream_name == "stdout" else "ERROR",
                "message": plain_message,
            },
            stage=self.run.current_stage,
        )


class RunManager:
    def __init__(self, root_dir: Path, repository: ProjectRepository) -> None:
        self.root_dir = Path(root_dir)
        self.repository = repository
        self.runs: Dict[str, RunRecord] = {}
        self._runs_lock = threading.Lock()
        self._live_lock = threading.Lock()

    def list_runs(self) -> list[RunSummary]:
        with self._runs_lock:
            records = list(self.runs.values())
        records.sort(key=lambda item: item.created_at, reverse=True)
        return [record.to_summary() for record in records]

    def get_run(self, run_id: str) -> Optional[RunDetail]:
        record = self._get_record(run_id)
        return record.to_detail() if record else None

    def create_run(self, request: RunRequest) -> RunSummary:
        if request.mode == "live" and not self._live_lock.acquire(blocking=False):
            raise RuntimeError("A live analysis run is already in progress.")

        now = datetime.utcnow()
        run_id = uuid.uuid4().hex[:12]
        label = request.label or self._default_label(request)
        record = RunRecord(id=run_id, request=request, label=label, created_at=now, updated_at=now)
        with self._runs_lock:
            self.runs[run_id] = record

        self.emit(record, "run_created", payload={"label": label, "mode": request.mode})
        thread = threading.Thread(target=self._execute_run, args=(record,), daemon=True)
        record.thread = thread
        thread.start()
        return record.to_summary()

    def stop_run(self, run_id: str) -> RunSummary:
        record = self._get_record(run_id)
        if record is None:
            raise RuntimeError("Run not found.")
        with record.lock:
            if record.status not in {"queued", "running"}:
                return record.to_summary()
            record.stop_requested = True
        self.emit(
            record,
            "run_stop_requested",
            payload={"summary": "Stop requested. The current stage will terminate as soon as possible."},
            stage=record.current_stage,
        )
        if record.kdump_analysis is not None:
            try:
                record.kdump_analysis.stop()
            except Exception:
                pass
        return record.to_summary()

    def emit(
        self,
        run: RunRecord,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        stage: Optional[str] = None,
    ) -> RunEvent:
        with run.lock:
            run.updated_at = datetime.utcnow()
            safe_payload = _json_safe(payload or {})
            if event_type == "log":
                signature = (
                    str(safe_payload.get("logger", "")),
                    str(safe_payload.get("level", "")),
                    str(safe_payload.get("message", "")),
                    stage or run.current_stage,
                )
                if run.last_log_signature == signature:
                    return RunEvent(
                        id=len(run.events),
                        run_id=run.id,
                        timestamp=run.updated_at,
                        stage=stage or run.current_stage,
                        type="log_deduped",
                        payload={},
                    )
                run.last_log_signature = signature
            event = RunEvent(
                id=len(run.events) + 1,
                run_id=run.id,
                timestamp=run.updated_at,
                stage=stage or run.current_stage,
                type=event_type,
                payload=safe_payload,
            )
            run.events.append(event)
            return event

    def event_slice(self, run_id: str, after_id: int = 0) -> tuple[list[RunEvent], Optional[RunStatus]]:
        record = self._get_record(run_id)
        if record is None:
            return [], None
        with record.lock:
            events = [event for event in record.events if event.id > after_id]
            return events, record.status

    def _execute_run(self, run: RunRecord) -> None:
        handler = _RunLogHandler(self, run)
        handler.setFormatter(logging.Formatter("%(message)s"))
        loggers = self._attach_loggers(handler)
        stdout_writer = _EventStreamWriter(self, run, "stdout")
        stderr_writer = _EventStreamWriter(self, run, "stderr")
        run.status = "running"
        try:
            with redirect_stdout(stdout_writer), redirect_stderr(stderr_writer):
                if run.request.mode == "live":
                    self._run_live(run)
                else:
                    self._run_replay(run)
            if run.stop_requested:
                run.status = "canceled"
                run.error = "Stopped by user."
                self.emit(
                    run,
                    "run_canceled",
                    payload={"summary": "Run stopped by user."},
                    stage=run.current_stage,
                )
            else:
                run.status = "completed"
                run.current_stage = "completed"
                self.emit(run, "run_completed", payload={"artifacts_ready": True}, stage="completed")
        except Exception as exc:
            if run.stop_requested:
                run.status = "canceled"
                run.error = "Stopped by user."
                self.emit(
                    run,
                    "run_canceled",
                    payload={"summary": "Run stopped by user."},
                    stage=run.current_stage,
                )
            else:
                run.status = "failed"
                run.error = str(exc)
                self.emit(
                    run,
                    "run_failed",
                    payload={
                        "error": str(exc),
                        "stage": run.current_stage,
                        "summary": f"Run stopped during {run.current_stage or 'unknown'}: {exc}",
                    },
                    stage=run.current_stage,
                )
        finally:
            stdout_writer.flush()
            stderr_writer.flush()
            self._detach_loggers(handler, loggers)
            if run.request.mode == "live":
                self._live_lock.release()
            run.kdump_analysis = None

    def _run_live(self, run: RunRecord) -> None:
        self._ensure_not_stopped(run)
        config = self._resolve_runtime_config(run.request)
        self._set_artifact(run, "config_summary", config)

        with self._stage(run, "config", "配置确认"):
            rag_status = self._get_pageindex_status(config)
            self._set_artifact(run, "pageindex_status", rag_status)
            self._set_artifact(
                run,
                "input_selection",
                {
                    "mode": run.request.mode,
                    "selected_case": run.request.case_id,
                    "selected_experience": run.request.experience_id,
                    "label": run.label,
                },
            )
            self.emit(run, "config_ready", payload={"config": config, "pageindex_status": rag_status})

        rag_manager: Optional[AnalysisRAGManager] = None
        kdump_analysis: Optional[KdumpAnalysis] = None
        search_payload: Optional[Dict[str, Any]] = None
        crash_report_text = ""

        try:
            with self._stage(run, "kdump_init", "Kdump / GDB 初始化"):
                self._ensure_not_stopped(run)
                if config["enable_rag"]:
                    rag_manager = AnalysisRAGManager(
                        base_dir=str(self.root_dir / "cache" / "rag"),
                        use_pageindex=True,
                    )
                    rag_status = rag_manager.get_pageindex_runtime_status()
                    self._set_artifact(run, "pageindex_status", rag_status)
                    self.emit(run, "rag_runtime_ready", payload=rag_status, stage="kdump_init")

                kdump_analysis = KdumpAnalysis(
                    linux=config["linux_path"],
                    kdump_server=config["kdump_server"],
                    vmcore=config["vmcore"],
                    gdb_path=config["gdb_path"],
                )
                run.kdump_analysis = kdump_analysis
                set_kdump_analysis_instance(kdump_analysis)
                kdump_analysis.loadKdump()
                kdump_analysis.loadGDB()
                set_linux_path(config["linux_path"])
                set_proj_path(config["linux_path"])
                create_cq_db(config["linux_path"])
                self.emit(
                    run,
                    "stage_snapshot",
                    payload={
                        "vmcore": config["vmcore"],
                        "linux_path": config["linux_path"],
                        "codequery_ready": True,
                    },
                    stage="kdump_init",
                )

            with self._stage(run, "search", "Known Bug Search"):
                self._ensure_not_stopped(run)
                result = runSearchAgent()
                if not isinstance(result, KnownBugAnalysisResult):
                    raise RuntimeError("Unexpected result type from search agent.")
                search_payload = parse_search_results(result)
                self._set_artifact(run, "search_result", search_payload)
                self.emit(run, "search_result", payload=search_payload, stage="search")

            if search_payload is None:
                raise RuntimeError("Search result is missing.")

            if not search_payload.get("is_known_bug"):
                rag_payload: Optional[Dict[str, Any]] = None
                if config["enable_rag"] and rag_manager is not None:
                    with self._stage(run, "rag", "RAG 上下文构建"):
                        self._ensure_not_stopped(run)
                        crash_report_raw = getCrashReport.invoke({})
                        crash_report_text = crash_report_raw if isinstance(crash_report_raw, str) else str(crash_report_raw)
                        rag_payload = rag_manager.build_pre_analysis_context(crash_report_text, top_k=3)
                        self._set_artifact(run, "rag_payload", rag_payload)
                        self.emit(run, "rag_context_ready", payload=rag_payload, stage="rag")

                with self._stage(run, "analyze", "Root Cause Analysis"):
                    self._ensure_not_stopped(run)
                    analyze_output = runAnalyzeAgent(
                        rag_context=(rag_payload or {}).get("context"),
                        return_trace=bool(config["enable_rag"] and rag_manager),
                    )
                    analyze_trace: Dict[str, Any] = {}
                    if isinstance(analyze_output, tuple):
                        analyze_result, analyze_trace = analyze_output
                    else:
                        analyze_result = analyze_output
                    if analyze_result is None:
                        raise RuntimeError("Analyze agent returned no result.")
                    parsed_analyze = analyze_result.model_dump()
                    self._set_artifact(run, "analysis_result", parsed_analyze)
                    self._set_artifact(run, "analysis_trace", analyze_trace)
                    self.emit(run, "analysis_result", payload=parsed_analyze, stage="analyze")
                    self.emit(run, "taint_trace_ready", payload=analyze_trace, stage="analyze")

                if config["enable_rag"] and rag_manager is not None:
                    with self._stage(run, "persist", "经验持久化"):
                        self._ensure_not_stopped(run)
                        if not crash_report_text:
                            crash_report_raw = getCrashReport.invoke({})
                            crash_report_text = crash_report_raw if isinstance(crash_report_raw, str) else str(crash_report_raw)
                        case_id = rag_manager.persist_success_case(
                            crash_report=crash_report_text,
                            analysis_result=run.artifacts.get("analysis_result", {}),
                            trace=run.artifacts.get("analysis_trace", {}),
                            retrieved_context=run.artifacts.get("rag_payload", {}),
                        )
                        experience = self.repository.get_experience(case_id)
                        payload = experience.model_dump() if experience else {"case_id": case_id}
                        self._set_artifact(run, "persisted_case", payload)
                        self.emit(run, "experience_persisted", payload=payload, stage="persist")
        finally:
            if kdump_analysis is not None:
                kdump_analysis.stop()

    def _run_replay(self, run: RunRecord) -> None:
        self._ensure_not_stopped(run)
        experience_id = run.request.experience_id
        if not experience_id:
            raise RuntimeError("Replay mode requires experience_id.")
        experience = self.repository.get_experience(experience_id)
        if experience is None:
            raise RuntimeError(f"Experience {experience_id} not found.")

        config = {
            "mode": "replay",
            "experience_id": experience.case_id,
            "enable_rag": bool(experience.retrieved_context),
            "kernel_version": experience.kernel_version,
            "bug_type": experience.bug_type,
        }
        self._set_artifact(run, "config_summary", config)

        with self._stage(run, "config", "回放配置"):
            self._ensure_not_stopped(run)
            self.emit(run, "config_ready", payload={"config": config}, stage="config")

        with self._stage(run, "search", "已知漏洞检索回放"):
            self._ensure_not_stopped(run)
            synthetic_search = {
                "is_known_bug": False,
                "evidence": "Replay mode does not have stored search-agent transcripts for this case.",
                "candidate_matches": [],
                "queries_tried": [],
                "final_reasoning": "Using persisted root-cause experience for presentation replay.",
            }
            self._set_artifact(run, "search_result", synthetic_search)
            self.emit(run, "search_result", payload=synthetic_search, stage="search")

        with self._stage(run, "rag", "RAG 上下文回放"):
            self._ensure_not_stopped(run)
            rag_payload = experience.retrieved_context or {}
            self._set_artifact(run, "rag_payload", rag_payload)
            self.emit(run, "rag_context_ready", payload=rag_payload, stage="rag")

        with self._stage(run, "analyze", "根因分析回放"):
            self._ensure_not_stopped(run)
            analysis_result = experience.analysis_result or {}
            trace_payload = experience.trace_summary or {}
            self._set_artifact(run, "analysis_result", analysis_result)
            self._set_artifact(run, "analysis_trace", trace_payload)
            self.emit(run, "analysis_result", payload=analysis_result, stage="analyze")
            self.emit(run, "taint_trace_ready", payload=trace_payload, stage="analyze")

        with self._stage(run, "persist", "经验案例展示"):
            self._ensure_not_stopped(run)
            payload = experience.model_dump()
            self._set_artifact(run, "persisted_case", payload)
            self.emit(run, "experience_persisted", payload=payload, stage="persist")

    @contextmanager
    def _stage(self, run: RunRecord, stage: str, title: str) -> Iterator[None]:
        run.current_stage = stage
        self.emit(run, "stage_started", payload={"title": title}, stage=stage)
        try:
            yield
            self.emit(run, "stage_finished", payload={"title": title}, stage=stage)
        except Exception as exc:
            self.emit(run, "stage_failed", payload={"title": title, "error": str(exc)}, stage=stage)
            raise

    def _set_artifact(self, run: RunRecord, key: str, value: Any) -> None:
        run.artifacts[key] = _json_safe(value)

    @staticmethod
    def _ensure_not_stopped(run: RunRecord) -> None:
        if run.stop_requested:
            raise RuntimeError("Stopped by user.")

    def _resolve_runtime_config(self, request: RunRequest) -> Dict[str, Any]:
        base = self.repository.load_config()
        override = request.config_override.model_dump(exclude_none=True)
        case_record = self.repository.get_case(request.case_id) if request.case_id else None

        config = {
            "linux_path": str(self._resolve_path(base.get("linux_path", "./kernel/linux"))),
            "gdb_path": self._resolve_gdb_path(str(base.get("gdb_path", "gdb"))),
            "vmcore": str(self._resolve_path(base.get("vmcore", "./vmcore"))),
            "kdump_server": str(self._resolve_path(base.get("kdump_server", "./kdump_server"))),
            "syzbot_data": str(self._resolve_path(base.get("syzbot_data", "./data"))),
            "enable_rag": bool(base.get("enable_rag", False)),
        }

        if case_record and case_record.vmcore_path and "vmcore" not in override:
            config["vmcore"] = case_record.vmcore_path

        for key, value in override.items():
            if key == "gdb_path":
                config[key] = self._resolve_gdb_path(str(value))
            elif key.endswith("_path") or key in {"vmcore", "kdump_server", "syzbot_data"}:
                config[key] = str(self._resolve_path(value))
            else:
                config[key] = value

        return config

    def _get_pageindex_status(self, config: Dict[str, Any]) -> Dict[str, Any]:
        if not config.get("enable_rag"):
            return {"enabled": False}

        state_path = self.root_dir / "cache" / "rag" / "pageindex_state.json"
        if not state_path.exists():
            return {"enabled": True, "last_sync_status": "missing"}
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"enabled": True, "last_sync_status": "invalid_state_file"}

    def _get_record(self, run_id: str) -> Optional[RunRecord]:
        with self._runs_lock:
            return self.runs.get(run_id)

    def _attach_loggers(self, handler: logging.Handler) -> list[logging.Logger]:
        names = ["Main", "kdump", "analysis_rag", "root", "langchain", "httpx"]
        loggers: list[logging.Logger] = []
        for name in names:
            logger = logging.getLogger(name if name != "root" else "")
            logger.addHandler(handler)
            loggers.append(logger)
        return loggers

    @staticmethod
    def _detach_loggers(handler: logging.Handler, loggers: list[logging.Logger]) -> None:
        for logger in loggers:
            logger.removeHandler(handler)

    def _resolve_path(self, raw_path: str) -> Path:
        path = Path(str(raw_path))
        if path.is_absolute():
            return path
        return (self.root_dir / path).resolve()

    def _resolve_gdb_path(self, raw_path: str) -> str:
        if "/" in raw_path:
            return str(self._resolve_path(raw_path))
        return raw_path

    @staticmethod
    def _default_label(request: RunRequest) -> str:
        if request.mode == "replay" and request.experience_id:
            return f"Replay {request.experience_id}"
        if request.case_id:
            return f"Live {request.case_id}"
        return f"{request.mode.title()} Run"
