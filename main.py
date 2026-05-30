from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import find_dotenv, load_dotenv
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from log import get_logger
from runtime_config import DEFAULT_RECURSION_LIMIT, set_runtime_config

main_log = get_logger("Main")
console = Console()


def _is_path_like(value: str) -> bool:
    return bool(
        os.sep in value
        or (os.altsep and os.altsep in value)
        or Path(value).drive
        or value.startswith("~")
    )


def _resource_roots(base_dir: Path) -> list[Path]:
    roots: list[Path] = []
    pyinstaller_root = getattr(sys, "_MEIPASS", None)
    if pyinstaller_root:
        roots.append(Path(pyinstaller_root).resolve())

    configured_root = os.getenv("AGENT4KDUMP_ROOT")
    if configured_root:
        roots.append(Path(configured_root).expanduser().resolve())

    roots.extend([base_dir.resolve(), Path(__file__).resolve().parent, Path.cwd().resolve()])

    seen: set[Path] = set()
    unique_roots: list[Path] = []
    for root in roots:
        if root not in seen:
            seen.add(root)
            unique_roots.append(root)
    return unique_roots


def _bundled_kdump_server(base_dir: Path) -> str | None:
    for root in _resource_roots(base_dir):
        candidate = root / "kdump_analyze" / "kdump-gdbserver" / "kdump-gdbserver"
        if candidate.is_file():
            return str(candidate)
    return None


def _resolve_command(value: str, *, base_dir: Path, candidates: list[str]) -> str:
    raw = value.strip()
    if raw and raw.lower() not in {"auto", "default"} and _is_path_like(raw):
        value_path = Path(raw).expanduser()
        if not value_path.is_absolute():
            value_path = base_dir / value_path
        return str(value_path.resolve())

    probe: list[str] = []
    if raw and raw.lower() not in {"auto", "default"}:
        probe.append(raw)
    probe.extend(candidates)

    seen: set[str] = set()
    for item in probe:
        if not item or item in seen:
            continue
        seen.add(item)
        if _is_path_like(item):
            path_item = Path(item).expanduser()
            if not path_item.is_absolute():
                path_item = base_dir / path_item
            if path_item.exists():
                return str(path_item.resolve())
        else:
            found = shutil.which(item)
            if found:
                return str(Path(found).resolve())

    return raw or (probe[0] if probe else "")


@dataclass(slots=True)
class AppConfig:
    config_path: Path | None
    linux_path: Path
    gdb_path: str
    vmcore: Path
    kdump_server: str
    enable_rag: bool = False
    build_codequery: bool = True
    rag_cache_dir: Path = Path("cache/rag")
    kdump_host: str = "127.0.0.1"
    kdump_port: int = 1234
    kdump_args: list[str] | None = None
    recursion_limit: int = DEFAULT_RECURSION_LIMIT

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "AppConfig":
        path = Path(config_path or "config.yaml")
        explicit_path = config_path is not None
        data: dict[str, Any] = {}

        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"Config file must contain a YAML mapping: {path}")
            data = raw
            base_dir = path.resolve().parent
            loaded_path: Path | None = path.resolve()
        elif explicit_path:
            raise FileNotFoundError(f"Config file does not exist: {path}")
        else:
            base_dir = Path.cwd()
            loaded_path = None

        def cfg_path(name: str, default: str) -> Path:
            value_path = Path(str(data.get(name, default))).expanduser()
            if not value_path.is_absolute():
                value_path = base_dir / value_path
            return value_path.resolve()

        def cfg_command(name: str, default: str, candidates: list[str]) -> str:
            return _resolve_command(
                str(data.get(name, default)), base_dir=base_dir, candidates=candidates
            )

        kdump_args = data.get("kdump_args")
        if isinstance(kdump_args, str):
            kdump_args = [kdump_args]
        elif kdump_args is not None and not (
            isinstance(kdump_args, list) and all(isinstance(item, str) for item in kdump_args)
        ):
            raise ValueError("kdump_args must be a string list when provided.")

        gdb_candidates = [
            os.getenv("AGENT4KDUMP_GDB", ""),
            os.getenv("GDB_PATH", ""),
            "gdb",
            "gdb-multiarch",
        ]
        kdump_candidates = [
            _bundled_kdump_server(base_dir) or "",
            "kdump-gdbserver",
        ]

        return cls(
            config_path=loaded_path,
            linux_path=cfg_path("linux_path", "./kernel/linux"),
            gdb_path=cfg_command("gdb_path", "auto", gdb_candidates),
            vmcore=cfg_path("vmcore", "./vmcore"),
            kdump_server=cfg_command("kdump_server", "auto", kdump_candidates),
            enable_rag=bool(data.get("enable_rag", False)),
            build_codequery=bool(data.get("build_codequery", True)),
            rag_cache_dir=cfg_path("rag_cache_dir", "./cache/rag"),
            kdump_host=str(data.get("kdump_host", "127.0.0.1")),
            kdump_port=int(data.get("kdump_port", 1234)),
            kdump_args=kdump_args,
            recursion_limit=int(data.get("recursion_limit", DEFAULT_RECURSION_LIMIT)),
        )

    def validate(self) -> None:
        if self.recursion_limit <= 0:
            raise ValueError("recursion_limit must be greater than 0")

        missing: list[str] = []
        if not self.linux_path.is_dir():
            missing.append(f"linux_path directory: {self.linux_path}")
        if not (self.linux_path / "vmlinux").is_file():
            missing.append(f"vmlinux: {self.linux_path / 'vmlinux'}")
        if not self.vmcore.is_file():
            missing.append(f"vmcore: {self.vmcore}")
        for label, command in [
            ("gdb executable", self.gdb_path),
            ("kdump-gdbserver executable", self.kdump_server),
        ]:
            if _is_path_like(command):
                exists = Path(command).exists()
            else:
                exists = shutil.which(command) is not None
            if not exists:
                missing.append(f"{label}: {command}")

        if missing:
            details = "\n  - ".join(missing)
            raise FileNotFoundError(f"Required runtime inputs are missing:\n  - {details}")

        kernel_config = self.linux_path / ".config"
        if not kernel_config.exists():
            main_log.warning(
                "Kernel .config not found: %s; read_config tool will return false.", kernel_config
            )


@dataclass(slots=True)
class AnalysisSession:
    config: AppConfig
    kdump_analysis: Any
    rag_retriever: Any = None
    pageindex_status: dict[str, Any] | None = None


def print_section(title: str) -> None:
    console.print(f"\n[bold green]{title}[/bold green]")


def print_kv(label: str, value: Any) -> None:
    if value not in (None, "", []):
        console.print(f"[cyan]{label}:[/cyan] {value}")


def print_list_section(title: str, items: list[Any] | None) -> None:
    if not items:
        return
    console.print(f"[cyan]{title}:[/cyan]")
    for idx, item in enumerate(items, start=1):
        console.print(f"  {idx}. {item}")


def get_pageindex_config_status(base_dir: Path) -> dict[str, Any]:
    try:
        from pageindex.page_index_md import md_to_tree as pageindex_md_to_tree
    except Exception:
        pageindex_md_to_tree = None

    corpus_path = base_dir / "history_corpus.md"
    tree_path = base_dir / "pageindex_tree.json"
    state_path = base_dir / "pageindex_state.json"
    state: dict[str, Any] = {}

    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}

    current_hash = ""
    if corpus_path.exists():
        try:
            current_hash = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
        except OSError:
            current_hash = ""

    stored_hash = str(state.get("corpus_hash", ""))
    has_history = corpus_path.exists() and bool(current_hash)
    tree_stale = bool(has_history and (not tree_path.exists() or stored_hash != current_hash))
    tree_ready = bool(has_history and tree_path.exists() and not tree_stale)
    fallback = ""
    if has_history and state.get("last_error") and not tree_ready:
        fallback = str(state.get("last_error"))
    elif has_history and not tree_ready:
        fallback = "History tree is not ready; falling back to local experience retrieval."

    return {
        "enabled": True,
        "markdown_backend_ready": pageindex_md_to_tree is not None,
        "tree_cache_ready": tree_ready,
        "tree_cache_stale": tree_stale,
        "last_sync_status": state.get("last_sync_status", ""),
        "fallback_reason": fallback,
    }


def init_analysis(
    config_path: str | Path | None = None,
    *,
    start_debugger: bool = True,
    build_codequery: bool | None = None,
) -> AnalysisSession:
    load_dotenv(find_dotenv())

    config = AppConfig.load(config_path)
    if build_codequery is not None:
        config.build_codequery = build_codequery
    config.validate()
    set_runtime_config(recursion_limit=config.recursion_limit)

    from agents.tools.codeQuery.codequery import set_proj_path
    from agents.tools.fileTools import set_linux_path
    from agents.tools.gdbTools import set_kdump_analysis_instance

    set_linux_path(str(config.linux_path))
    set_proj_path(str(config.linux_path))
    from agents.tools.codeQuery.codequery import create_cq_db, has_codequery_dependencies

    if not config.build_codequery:
        main_log.info("Skipping CodeQuery database build by request.")
    elif not has_codequery_dependencies():
        main_log.warning(
            "CodeQuery dependencies are not available; source lookup tools will degrade."
        )
    else:
        create_cq_db(str(config.linux_path))

    rag_retriever = None
    pageindex_status = (
        get_pageindex_config_status(config.rag_cache_dir) if config.enable_rag else None
    )
    if config.enable_rag:
        from agents.rag import AnalysisRAGManager

        main_log.info("Initializing analysis RAG system...")
        rag_retriever = AnalysisRAGManager(base_dir=str(config.rag_cache_dir), use_pageindex=True)
        pageindex_status = rag_retriever.get_pageindex_runtime_status()

    from agents.utils.kdump import KdumpAnalysis

    kdump_analysis = KdumpAnalysis(
        linux=str(config.linux_path),
        kdump_server=config.kdump_server,
        vmcore=str(config.vmcore),
        gdb_path=config.gdb_path,
        host=config.kdump_host,
        port=config.kdump_port,
        kdump_args=config.kdump_args,
    )
    set_kdump_analysis_instance(kdump_analysis)
    atexit.register(kdump_analysis.stop)

    if start_debugger:
        main_log.info("Starting kdump-gdbserver and gdb...")
        kdump_analysis.loadKdump()
        kdump_analysis.loadGDB()
    main_log.info("Analysis environment initialized successfully")
    return AnalysisSession(
        config=config,
        kdump_analysis=kdump_analysis,
        rag_retriever=rag_retriever,
        pageindex_status=pageindex_status,
    )


def render_config_table(session: AnalysisSession) -> None:
    config = session.config
    table = Table(title="Configuration Summary", show_header=True, header_style="bold magenta")
    table.add_column("Setting", style="cyan", width=20)
    table.add_column("Value", style="green")
    table.add_row("Config", str(config.config_path or "defaults"))
    table.add_row("Linux Path", str(config.linux_path))
    table.add_row("GDB Path", config.gdb_path)
    table.add_row("VMCore", str(config.vmcore))
    table.add_row("Kdump Server", config.kdump_server)
    table.add_row("Kdump Target", f"{config.kdump_host}:{config.kdump_port}")
    table.add_row("CodeQuery Build", "Yes" if config.build_codequery else "No")
    table.add_row("RAG Enabled", "Yes" if config.enable_rag else "No")
    table.add_row("Recursion Limit", str(config.recursion_limit))
    console.print(table)


def render_pageindex_status(status: dict[str, Any]) -> None:
    print_section("PageIndex Status")
    print_kv("Enabled", "Yes" if status.get("enabled") else "No")
    print_kv("Markdown Backend Ready", "Yes" if status.get("markdown_backend_ready") else "No")
    print_kv("History Tree Ready", "Yes" if status.get("tree_cache_ready") else "No")
    print_kv("History Tree Stale", "Yes" if status.get("tree_cache_stale") else "No")
    print_kv("Last Sync Status", status.get("last_sync_status"))
    print_kv("Fallback Reason", status.get("fallback_reason"))


def run_full_analysis(session: AnalysisSession, on_stage=None) -> dict[str, Any]:
    from agents.analyze_agent import RootCauseAnalysisResult, runAnalyzeAgent
    from agents.search_agent import KnownBugAnalysisResult, parse_search_results, runSearchAgent
    from agents.tools.gdbTools import getCrashReport

    main_log.info("Running search agent...")
    if on_stage:
        on_stage("known_bug_search", "starting")
    try:
        result = runSearchAgent()
    except Exception as exc:
        main_log.warning(
            "Search agent failed; continuing with root cause analysis without known-bug context: %s",
            exc,
        )
        result = KnownBugAnalysisResult(
            is_known_bug=False,
            evidence=f"Known-bug search failed and was skipped: {exc}",
            matched_url=[],
            extra_info="Continuing with root cause analysis without known-bug context.",
        )
    if not isinstance(result, KnownBugAnalysisResult):
        main_log.warning(
            "Search agent did not return a KnownBugAnalysisResult; continuing with root cause analysis."
        )
        result = KnownBugAnalysisResult(
            is_known_bug=False,
            evidence="Known-bug search returned no structured result and was skipped.",
            matched_url=[],
            extra_info="Continuing with root cause analysis without known-bug context.",
        )

    parsed_search = parse_search_results(result)
    if on_stage:
        on_stage("known_bug_search", "completed")
    if parsed_search["is_known_bug"]:
        main_log.info("Known bug found: %s", parsed_search.get("matched_url"))
        return {"parsed_search": parsed_search, "parsed_analyze": None}

    main_log.info("No known bug found, proceeding with root cause analysis...")
    rag_context_text = None
    rag_payload = None
    crash_report_text = ""

    if session.config.enable_rag and session.rag_retriever:
        try:
            crash_report_text = str(getCrashReport.invoke({}))
            rag_payload = session.rag_retriever.build_pre_analysis_context(crash_report_text, top_k=3)
            rag_context_text = rag_payload.get("context")
            main_log.info("Built pre-analysis RAG context")
        except Exception as exc:
            main_log.warning(
                "RAG context build failed; continuing without RAG context: %s", exc
            )
            rag_payload = None
            rag_context_text = None

    analyze_output = runAnalyzeAgent(
        rag_context=rag_context_text,
        return_trace=bool(session.config.enable_rag and session.rag_retriever),
        on_stage=on_stage,
    )
    if isinstance(analyze_output, tuple):
        analyze_result, analyze_trace = analyze_output
    else:
        analyze_result, analyze_trace = analyze_output, {}

    if not isinstance(analyze_result, RootCauseAnalysisResult):
        raise RuntimeError("Analyze agent did not return a RootCauseAnalysisResult.")

    parsed_analyze = analyze_result.model_dump()
    if session.config.enable_rag and session.rag_retriever:
        if not crash_report_text:
            try:
                crash_report_text = str(getCrashReport.invoke({}))
            except Exception as exc:
                main_log.warning(
                    "Could not retrieve crash report for RAG persistence; continuing: %s",
                    exc,
                )
        if crash_report_text:
            try:
                case_id = session.rag_retriever.persist_success_case(
                    crash_report=crash_report_text,
                    analysis_result=parsed_analyze,
                    trace=analyze_trace,
                    retrieved_context=rag_payload,
                )
                main_log.info("Stored analysis experience as %s", case_id)
            except Exception as exc:
                main_log.warning("Failed to persist RAG experience; continuing: %s", exc)

    return {"parsed_search": parsed_search, "parsed_analyze": parsed_analyze}


def render_search_results(parsed_result: dict[str, Any]) -> None:
    print_section("Known Bug Search Result")
    print_kv("Known Bug", parsed_result.get("is_known_bug"))

    fingerprint = parsed_result.get("crash_fingerprint") or {}
    if fingerprint:
        console.print("[cyan]Crash Fingerprint:[/cyan]")
        for key in ["fault_type", "crash_function", "source_path"]:
            print_kv(f"  - {key}", fingerprint.get(key))
        if fingerprint.get("top_frames"):
            console.print(f"  - top_frames: {', '.join(fingerprint['top_frames'])}")
        if fingerprint.get("title_candidates"):
            console.print(f"  - title_candidates: {' | '.join(fingerprint['title_candidates'])}")

    queries = parsed_result.get("queries_tried") or []
    if queries:
        console.print("[cyan]Queries Tried:[/cyan]")
        for idx, item in enumerate(queries, start=1):
            domains = ", ".join(item.get("target_domains", [])) or "all"
            console.print(
                f"  {idx}. [{domains}] {item.get('query', '')} (observed={item.get('observed_result', '')})"
            )

    print_kv("Evidence", parsed_result.get("evidence"))
    print_kv("Matched URLs", parsed_result.get("matched_url"))
    print_kv("Extra Info", parsed_result.get("extra_info"))


def render_analyze_results(parsed_analyze: dict[str, Any]) -> None:
    print_section("Root Cause Analysis Result")
    print_kv("Root Cause", parsed_analyze.get("root_cause"))
    print_kv("Trigger Path", parsed_analyze.get("trigger_path"))
    print_kv("Fix Suggestion", parsed_analyze.get("fix_suggestion"))
    print_kv("Confidence", parsed_analyze.get("confidence"))

    crash_site = parsed_analyze.get("crash_site") or {}
    if crash_site:
        console.print("[cyan]Crash Site:[/cyan]")
        for key in ["file", "function", "line", "invalid_object", "statement"]:
            print_kv(f"  - {key}", crash_site.get(key))

    key_locations = parsed_analyze.get("key_locations") or []
    if key_locations:
        console.print("[cyan]Key Locations:[/cyan]")
        for idx, item in enumerate(key_locations, start=1):
            console.print(
                f"  {idx}. [{item.get('role')}] {item.get('file')}:{item.get('line')} "
                f"{item.get('function')}::{item.get('object')} | {item.get('detail')}"
            )

    print_kv("Patch Sketch", parsed_analyze.get("patch_sketch"))
    print_list_section("Evidence", parsed_analyze.get("evidence"))
    print_list_section("Verification TODO", parsed_analyze.get("verification_todo"))
    print_kv("Uncertainty", parsed_analyze.get("uncertainty"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run agent4kdump analysis.")
    parser.add_argument(
        "--config", default=None, help="Config YAML path. Defaults to ./config.yaml."
    )
    parser.add_argument(
        "--confirm", action="store_true", help="Ask for confirmation after printing config."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print config without starting kdump/gdb.",
    )
    parser.add_argument(
        "--no-codequery", action="store_true", help="Skip CodeQuery database build during init."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    main_log.info("Starting kdump analysis tool...")

    try:
        session = init_analysis(
            args.config,
            start_debugger=not args.dry_run,
            build_codequery=False if args.no_codequery else None,
        )
        render_config_table(session)
        if session.pageindex_status:
            render_pageindex_status(session.pageindex_status)

        if args.dry_run:
            return 0
        if args.confirm and not Confirm.ask("\nProceed with this configuration?", default=True):
            console.print("[yellow]Operation cancelled by user.[/yellow]")
            return 0

        results = run_full_analysis(session)
        render_search_results(results["parsed_search"])
        if results["parsed_analyze"] is not None:
            render_analyze_results(results["parsed_analyze"])
        return 0
    except Exception as exc:
        main_log.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
