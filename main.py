import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Any

import yaml
from dotenv import load_dotenv, find_dotenv

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from log import *
from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm
from kdump_analyze.kdump import KdumpAnalysis
from agents.tools.codeQuery.codequery import create_cq_db, set_proj_path
from agents.tools.gdbTools import getCrashReport, set_kdump_analysis_instance
from agents.tools.fileTools import set_linux_path
from contextlib import contextmanager
from agents.search_agent import runSearchAgent, parse_search_results, KnownBugAnalysisResult
from agents.analyze_agent import runAnalyzeAgent, RootCauseAnalysisResult
from agents.rag import AnalysisRAGManager

try:
    from pageindex.page_index_md import md_to_tree as _pageindex_md_to_tree
except Exception:
    _pageindex_md_to_tree = None

main_log = get_logger("Main")
console = Console()


# ── Data structures ──────────────────────────────────────────────

@dataclass
class AnalysisSession:
    """Holds all initialized components for a kdump analysis session."""
    config: dict
    linux_path: str
    gdb_path: str
    vmcore: str
    kdump_server: str
    syzbot_data: str
    enable_rag: bool
    kdump_analysis: Any  # KdumpAnalysis
    rag_retriever: Optional[AnalysisRAGManager] = None
    pageindex_status: Optional[dict] = None


# ── Rendering helpers ────────────────────────────────────────────

def print_section(title: str) -> None:
    console.print(f"\n[bold green]{title}[/bold green]")


def print_kv(label: str, value) -> None:
    if value is None or value == "" or value == []:
        return
    console.print(f"[cyan]{label}:[/cyan] {value}")


def print_list_section(title: str, items) -> None:
    if not items:
        return
    console.print(f"[cyan]{title}:[/cyan]")
    for idx, item in enumerate(items, start=1):
        console.print(f"  {idx}. {item}")


def render_pageindex_status(status: dict) -> None:
    print_section("PageIndex Status")
    print_kv("Enabled", "Yes" if status.get("enabled") else "No")
    print_kv("Markdown Backend Ready", "Yes" if status.get("markdown_backend_ready") else "No")
    print_kv("History Tree Ready", "Yes" if status.get("tree_cache_ready") else "No")
    print_kv("History Tree Stale", "Yes" if status.get("tree_cache_stale") else "No")
    print_kv("Last Sync Status", status.get("last_sync_status"))
    print_kv("Fallback Reason", status.get("fallback_reason"))


def get_pageindex_config_status(base_dir: str = "./cache/rag") -> dict:
    cache_dir = Path(base_dir)
    corpus_path = cache_dir / "history_corpus.md"
    tree_path = cache_dir / "pageindex_tree.json"
    state_path = cache_dir / "pageindex_state.json"
    markdown_backend_ready = _pageindex_md_to_tree is not None

    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}

    current_corpus_hash = ""
    if corpus_path.exists():
        try:
            current_corpus_hash = hashlib.sha256(corpus_path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        except OSError:
            current_corpus_hash = ""

    stored_hash = str(state.get("corpus_hash", ""))
    has_history = corpus_path.exists() and bool(current_corpus_hash)
    tree_cache_stale = bool(has_history and (not tree_path.exists() or stored_hash != current_corpus_hash))
    tree_cache_ready = bool(has_history and tree_path.exists() and not tree_cache_stale)

    fallback_reason = ""
    if has_history and state.get("last_error") and not tree_cache_ready:
        fallback_reason = state.get("last_error")
    elif has_history and not tree_cache_ready:
        fallback_reason = "History tree is not ready; falling back to local experience retrieval."

    return {
        "enabled": True,
        "markdown_backend_ready": markdown_backend_ready,
        "tree_cache_ready": tree_cache_ready,
        "tree_cache_stale": tree_cache_stale,
        "last_sync_status": state.get("last_sync_status", ""),
        "fallback_reason": fallback_reason,
    }


def render_search_results(parsed_result: dict) -> None:
    print_section("Known Bug Search Result")
    print_kv("Known Bug", parsed_result.get("is_known_bug"))

    fingerprint = parsed_result.get("crash_fingerprint") or {}
    if fingerprint:
        console.print("[cyan]Crash Fingerprint:[/cyan]")
        for key in [
            "fault_type",
            "crash_function",
            "source_path",
        ]:
            if fingerprint.get(key):
                console.print(f"  - {key}: {fingerprint.get(key)}")
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
                f"  {idx}. [{domains}] {item.get('query', '')} "
                f"(observed={item.get('observed_result', '')})"
            )

    print_kv("Evidence", parsed_result.get("evidence"))
    print_kv("Matched URLs", parsed_result.get("matched_url"))
    print_kv("Extra Info", parsed_result.get("extra_info"))


def render_analyze_results(parsed_analyze: dict) -> None:
    print_section("Root Cause Analysis Result")
    print_kv("Root Cause", parsed_analyze.get("root_cause"))
    print_kv("Trigger Path", parsed_analyze.get("trigger_path"))
    print_kv("Fix Suggestion", parsed_analyze.get("fix_suggestion"))
    print_kv("Confidence", parsed_analyze.get("confidence"))

    crash_site = parsed_analyze.get("crash_site") or {}
    if crash_site:
        console.print("[cyan]Crash Site:[/cyan]")
        for key in ["file", "function", "line", "invalid_object", "statement"]:
            if crash_site.get(key) is not None and crash_site.get(key) != "":
                console.print(f"  - {key}: {crash_site.get(key)}")

    key_locations = parsed_analyze.get("key_locations") or []
    if key_locations:
        console.print("[cyan]Key Locations:[/cyan]")
        for idx, item in enumerate(key_locations, start=1):
            console.print(
                f"  {idx}. [{item.get('role')}] {item.get('file')}:{item.get('line')} "
                f"{item.get('function')}::{item.get('object')} | {item.get('detail')}"
            )

    patch_sketch = parsed_analyze.get("patch_sketch")
    if patch_sketch:
        console.print("[cyan]Patch Sketch:[/cyan]")
        console.print(f"[white]{patch_sketch}[/white]")

    print_list_section("Evidence", parsed_analyze.get("evidence"))
    print_list_section("Verification TODO", parsed_analyze.get("verification_todo"))
    print_kv("Uncertainty", parsed_analyze.get("uncertainty"))


# ── Context manager ──────────────────────────────────────────────

@contextmanager
def catch_error(desc):
    main_log.info(f"Starting: {desc}")
    try:
        yield
    except Exception as e:
        main_log.error(f"{desc} failed: {e}")
        sys.exit(1)
    main_log.info(f"Completed: {desc}")


# ── Core init function ───────────────────────────────────────────

def init_analysis(config_path: str | Path) -> AnalysisSession:
    """
    Initialize the kdump analysis environment from a YAML config file.

    Performs:
      1. Load .env
      2. Parse YAML config
      3. Normalize & resolve paths
      4. Initialize RAG system (if enabled)
      5. Initialize KdumpAnalysis + load kdump + load GDB
      6. Set linux path for file/code tools
      7. Build codequery database

    Returns an AnalysisSession holding all initialized components.
    Callers can then run search/analyze agents and render results as needed.
    """
    load_dotenv(find_dotenv())

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file {config_path} does not exist.")

    with open(config_path, "r") as file:
        config = yaml.safe_load(file)

    linux = config.get("linux_path", "./linux")
    gdb = config.get("gdb_path", "gdb")
    vmcore = config.get("vmcore", "./vmcore")
    kdump_server = config.get("kdump_server", "./kdump_server")
    syzbot_data = config.get("syzbot_data", "./syzbot_data")
    enable_rag = config.get("enable_rag", False)

    linux_path = os.path.abspath(linux)
    vmcore = os.path.abspath(vmcore)
    kdump_server = os.path.abspath(kdump_server)
    syzbot_data = os.path.abspath(syzbot_data)

    if "/" in gdb:
        gdb = os.path.abspath(gdb)

    pageindex_status = get_pageindex_config_status() if enable_rag else None

    # ── RAG ──
    rag_retriever = None
    if enable_rag:
        main_log.info("Initializing analysis RAG system...")
        rag_retriever = AnalysisRAGManager(
            base_dir=os.path.abspath("./cache/rag"),
            use_pageindex=True,
        )
        main_log.info("RAG system initialized successfully")

    # ── Kdump + GDB ──
    main_log.info("Initializing kdump-gdbserver...")

    kdump_analysis = KdumpAnalysis(
        linux=linux_path,
        kdump_server=kdump_server,
        vmcore=vmcore,
        gdb_path=gdb,
    )
    set_kdump_analysis_instance(kdump_analysis)

    kdump_analysis.loadKdump()
    kdump_analysis.loadGDB()

    set_linux_path(linux_path)

    # ── Code query ──
    if not os.path.exists(config_path):
        raise FileNotFoundError(f".config file not found in linux path: {linux_path}")

    set_proj_path(linux_path)
    create_cq_db(linux_path)

    session = AnalysisSession(
        config=config,
        linux_path=linux_path,
        gdb_path=gdb,
        vmcore=vmcore,
        kdump_server=kdump_server,
        syzbot_data=syzbot_data,
        enable_rag=enable_rag,
        kdump_analysis=kdump_analysis,
        rag_retriever=rag_retriever,
        pageindex_status=pageindex_status,
    )

    main_log.info("Analysis environment initialized successfully")
    return session


def render_config_table(session: AnalysisSession) -> None:
    """Display the configuration summary as a Rich table."""
    table = Table(title="Configuration Summary", show_header=True, header_style="bold magenta")
    table.add_column("Setting", style="cyan", width=20)
    table.add_column("Value", style="green")

    table.add_row("Linux Path", session.linux_path)
    table.add_row("GDB Path", session.gdb_path)
    table.add_row("VMCore", session.vmcore)
    table.add_row("Kdump Server", session.kdump_server)
    table.add_row("Syzbot Data", session.syzbot_data)
    table.add_row("RAG Enabled", "Yes" if session.enable_rag else "No")
    if session.enable_rag and session.pageindex_status is not None:
        table.add_row("PageIndex Enabled", "Yes" if session.pageindex_status["enabled"] else "No")
        table.add_row("Markdown Backend Ready", "Yes" if session.pageindex_status["markdown_backend_ready"] else "No")

    console.print(table)


def run_full_analysis(session: AnalysisSession) -> dict:
    """
    Run the complete analysis pipeline (search → optionally deep analyze).
    Returns a dict with keys: parsed_search, parsed_analyze (or None).
    """
    # ── Search agent ──
    main_log.info("Running search agent...")
    result = runSearchAgent()

    if result is None:
        main_log.error("Failed to get output from search agent")
        sys.exit(1)

    if not isinstance(result, KnownBugAnalysisResult):
        main_log.error("Unexpected result type from search agent")
        sys.exit(1)

    parsed_result = parse_search_results(result)

    if parsed_result["is_known_bug"]:
        main_log.info(f"Known bug found: {parsed_result['matched_url']}")
        return {"parsed_search": parsed_result, "parsed_analyze": None}

    # ── Deep analysis ──
    main_log.info("No known bug found, proceeding with root cause analysis...")
    rag_context_text = None
    rag_payload = None
    crash_report_text = ""

    if session.enable_rag and session.rag_retriever:
        crash_report_raw = getCrashReport.invoke({})
        crash_report_text = crash_report_raw if isinstance(crash_report_raw, str) else str(crash_report_raw)
        rag_payload = session.rag_retriever.build_pre_analysis_context(crash_report_text, top_k=3)
        rag_context_text = rag_payload.get("context")
        main_log.info("Built pre-analysis RAG context")

    analyze_output = runAnalyzeAgent(
        rag_context=rag_context_text,
        return_trace=bool(session.enable_rag and session.rag_retriever),
    )

    analyze_trace = {}
    if isinstance(analyze_output, tuple):
        analyze_result, analyze_trace = analyze_output
    else:
        analyze_result = analyze_output

    if analyze_result is None:
        main_log.error("Failed to get output from analyze agent")
        sys.exit(1)

    if not isinstance(analyze_result, RootCauseAnalysisResult):
        main_log.error("Unexpected result type from analyze agent")
        sys.exit(1)

    parsed_analyze = analyze_result.model_dump()
    main_log.info("Root cause analysis completed")

    # ── Persist experience ──
    if session.enable_rag and session.rag_retriever:
        if not crash_report_text:
            crash_report_raw = getCrashReport.invoke({})
            crash_report_text = crash_report_raw if isinstance(crash_report_raw, str) else str(crash_report_raw)
        case_id = session.rag_retriever.persist_success_case(
            crash_report=crash_report_text,
            analysis_result=parsed_analyze,
            trace=analyze_trace,
            retrieved_context=rag_payload,
        )
        main_log.info(f"Stored analysis experience as {case_id}")

    return {"parsed_search": parsed_result, "parsed_analyze": parsed_analyze}


# ── CLI entry point ──────────────────────────────────────────────

def main():
    main_log.info("Starting kdump analysis tool...")

    arg = argparse.ArgumentParser()
    arg.add_argument("--config", type=str, required=True, help="the config file path")
    args = arg.parse_args()

    with catch_error("Analysis initialization"):
        session = init_analysis(args.config)

    render_config_table(session)
    if session.pageindex_status:
        render_pageindex_status(session.pageindex_status)

    if not Confirm.ask("\nProceed with this configuration?", default=True):
        console.print("[yellow]Operation cancelled by user.[/yellow]")
        sys.exit(0)

    with catch_error("Analysis pipeline"):
        results = run_full_analysis(session)

    render_search_results(results["parsed_search"])

    if results["parsed_analyze"] is not None:
        render_analyze_results(results["parsed_analyze"])


if __name__ == "__main__":
    main()
