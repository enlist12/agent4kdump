from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import yaml

from .env_settings import load_client_env
from .schemas import (
    AnalysisConfigPayload,
    AnalysisSessionPayload,
    SessionResultPayload,
    utc_now,
)
from .session_store import SessionStore


RUNTIME_DIR = Path("cache/client_sessions")


def _config_to_yaml(config: AnalysisConfigPayload) -> dict[str, Any]:
    data = config.model_dump(exclude_none=True)
    data.pop("config_path", None)
    return data


def _config_file_for(session: AnalysisSessionPayload) -> Path | None:
    if session.config.config_path:
        return Path(session.config.config_path).expanduser()

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    session_dir = RUNTIME_DIR / session.id
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / "config.yaml"
    path.write_text(
        yaml.safe_dump(_config_to_yaml(session.config), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _app_config_summary(config: Any) -> dict[str, Any]:
    return {
        "config_path": str(config.config_path or "generated"),
        "linux_path": str(config.linux_path),
        "gdb_path": config.gdb_path,
        "vmcore": str(config.vmcore),
        "kdump_server": config.kdump_server,
        "enable_rag": config.enable_rag,
        "build_codequery": config.build_codequery,
        "rag_cache_dir": str(config.rag_cache_dir),
        "kdump_host": config.kdump_host,
        "kdump_port": config.kdump_port,
        "kdump_args": config.kdump_args or [],
    }


def validate_config_payload(config_payload: AnalysisConfigPayload) -> tuple[bool, dict[str, Any] | None, str | None]:
    from main import AppConfig

    try:
        load_client_env()
        if config_payload.config_path:
            app_config = AppConfig.load(config_payload.config_path)
        else:
            temp_session = AnalysisSessionPayload(
                id="validation",
                name="validation",
                status="created",
                config=config_payload,
                created_at=utc_now(),
            )
            config_path = _config_file_for(temp_session)
            app_config = AppConfig.load(config_path)
        app_config.validate()
        return True, _app_config_summary(app_config), None
    except Exception as exc:
        return False, None, str(exc)


def build_report_markdown(session: AnalysisSessionPayload) -> str:
    result = session.results
    search = result.parsed_search or {}
    analyze = result.parsed_analyze or {}
    lines = [
        f"# agent4kdump Report: {session.name}",
        "",
        f"- Session: `{session.id}`",
        f"- Status: `{session.status}`",
        f"- Created: `{session.created_at}`",
        "",
        "## Known Bug Search",
        "",
        f"- Known Bug: `{search.get('is_known_bug', 'unknown')}`",
        f"- Matched URLs: `{json.dumps(search.get('matched_url'), ensure_ascii=False)}`",
        "",
        str(search.get("evidence") or "No search evidence available."),
        "",
        "## Root Cause",
        "",
        str(analyze.get("root_cause") or "No root cause result available."),
        "",
        "## Trigger Path",
        "",
        str(analyze.get("trigger_path") or "No trigger path available."),
        "",
        "## Fix Suggestion",
        "",
        str(analyze.get("fix_suggestion") or "No fix suggestion available."),
        "",
    ]
    evidence = analyze.get("evidence") or []
    if evidence:
        lines.extend(["## Evidence", ""])
        lines.extend(f"- {item}" for item in evidence)
        lines.append("")
    return "\n".join(lines)


class AnalysisRunner:
    def __init__(self, store: SessionStore) -> None:
        self.store = store
        self._threads: dict[str, threading.Thread] = {}

    def run(self, session_id: str, *, dry_run: bool = False) -> None:
        if session_id in self._threads and self._threads[session_id].is_alive():
            raise RuntimeError("Session is already running.")
        thread = threading.Thread(
            target=self._run_session,
            args=(session_id, dry_run),
            name=f"analysis-{session_id}",
            daemon=True,
        )
        self._threads[session_id] = thread
        thread.start()

    def _run_session(self, session_id: str, dry_run: bool) -> None:
        from main import AppConfig, init_analysis, run_full_analysis

        load_client_env()
        session = self.store.get_session(session_id)
        if session is None:
            return

        self.store.update_session(
            session_id,
            status="validating",
            started_at=utc_now(),
            error="",
        )
        self.store.add_event(session_id, "config.validation_started", stage="config")

        try:
            config_path = _config_file_for(session)
            app_config = AppConfig.load(config_path)
            app_config.validate()
            config_summary = _app_config_summary(app_config)
            self.store.add_event(
                session_id,
                "config.validated",
                stage="config",
                payload=config_summary,
            )

            if dry_run:
                results = SessionResultPayload(report_markdown="Dry run completed.")
                self.store.update_session(
                    session_id,
                    status="completed",
                    finished_at=utc_now(),
                    results=results,
                )
                self.store.add_event(session_id, "session.completed", payload={"dry_run": True})
                return

            if self.store.is_cancelled(session_id):
                self.store.update_session(session_id, status="cancelled", finished_at=utc_now())
                self.store.add_event(session_id, "session.cancelled")
                return

            self.store.update_session(session_id, status="running")
            self.store.add_event(session_id, "debugger.starting", stage="debugger")
            analysis_session = init_analysis(str(config_path))
            self.store.add_event(session_id, "debugger.started", stage="debugger")

            if analysis_session.pageindex_status:
                self.store.add_event(
                    session_id,
                    "rag.status",
                    stage="rag",
                    payload=analysis_session.pageindex_status,
                )

            self.store.add_event(session_id, "analysis.started", stage="analysis")
            raw_results = run_full_analysis(analysis_session)
            results = SessionResultPayload(
                parsed_search=raw_results.get("parsed_search"),
                parsed_analyze=raw_results.get("parsed_analyze"),
                pageindex_status=analysis_session.pageindex_status,
            )
            completed = self.store.update_session(
                session_id,
                status="completed",
                finished_at=utc_now(),
                results=results,
            )
            completed.results.report_markdown = build_report_markdown(completed)
            self.store.update_session(session_id, results=completed.results)
            self.store.add_event(session_id, "analysis.completed", stage="analysis")
            self.store.add_event(session_id, "session.completed")
        except Exception as exc:
            self.store.update_session(
                session_id,
                status="failed",
                error=str(exc),
                finished_at=utc_now(),
            )
            self.store.add_event(
                session_id,
                "error",
                payload={"message": str(exc)},
            )
