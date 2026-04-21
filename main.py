import argparse
import sys
from pathlib import Path

import yaml

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from log import *
from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm
from kdump_analyze.kdump import KdumpAnalysis
import os
from agent_core.tools.codeQuery.codequery import create_cq_db, set_proj_path
from agent_core.tools.gdbTools import getCrashReport, set_kdump_analysis_instance
from agent_core.tools.fileTools import set_linux_path
from contextlib import contextmanager
from agents.search_agent import runSearchAgent, parse_search_results, KnownBugAnalysisResult
from agents.analyze_agent import runAnalyzeAgent, RootCauseAnalysisResult
from agents.rag import AnalysisRAGManager

config_path = None
kdump_analysis = None
linux_path = None

main_log = get_logger("Main")


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


def render_search_results(parsed_result: dict) -> None:
    print_section("Known Bug Search Result")
    print_kv("Known Bug", parsed_result.get("is_known_bug"))

    fingerprint = parsed_result.get("crash_fingerprint") or {}
    if fingerprint:
        console.print("[cyan]Crash Fingerprint:[/cyan]")
        for key in [
            "panic_header",
            "fault_type",
            "crash_function",
            "subsystem",
            "source_path",
            "access_type",
        ]:
            if fingerprint.get(key):
                console.print(f"  - {key}: {fingerprint.get(key)}")
        if fingerprint.get("top_frames"):
            console.print(f"  - top_frames: {', '.join(fingerprint['top_frames'])}")
        if fingerprint.get("title_candidates"):
            console.print(f"  - title_candidates: {' | '.join(fingerprint['title_candidates'])}")
        if fingerprint.get("keywords"):
            console.print(f"  - keywords: {', '.join(fingerprint['keywords'])}")

    queries = parsed_result.get("queries_tried") or []
    if queries:
        console.print("[cyan]Queries Tried:[/cyan]")
        for idx, item in enumerate(queries, start=1):
            domains = ", ".join(item.get("target_domains", [])) or "all"
            console.print(
                f"  {idx}. [{domains}] {item.get('query', '')} "
                f"(purpose={item.get('purpose', '')}; observed={item.get('observed_result', '')})"
            )

    candidates = parsed_result.get("candidate_matches") or []
    if candidates:
        console.print("[cyan]Candidate Matches:[/cyan]")
        for idx, item in enumerate(candidates, start=1):
            console.print(
                f"  {idx}. [{item.get('verdict')}/{item.get('relevance')}] "
                f"{item.get('title', '')} | {item.get('url', '')} | {item.get('reason', '')}"
            )

    print_kv("Evidence", parsed_result.get("evidence"))
    print_kv("Rejection Summary", parsed_result.get("rejection_summary"))
    print_kv("Final Reasoning", parsed_result.get("final_reasoning"))
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

    root_cause_chain = parsed_analyze.get("root_cause_chain") or []
    if root_cause_chain:
        console.print("[cyan]Root Cause Chain:[/cyan]")
        for item in root_cause_chain:
            console.print(
                f"  {item.get('step')}. {item.get('file')}:{item.get('line')} "
                f"{item.get('function')}::{item.get('object')} -> {item.get('explanation')}"
            )

    source_locations = parsed_analyze.get("source_locations") or []
    if source_locations:
        console.print("[cyan]Source Locations:[/cyan]")
        for idx, item in enumerate(source_locations, start=1):
            console.print(
                f"  {idx}. [{item.get('label')}] {item.get('file')}:{item.get('line')} "
                f"{item.get('function')} | {item.get('detail')}"
            )

    fix_candidates = parsed_analyze.get("fix_candidates") or []
    if fix_candidates:
        console.print("[cyan]Fix Candidates:[/cyan]")
        for idx, item in enumerate(fix_candidates, start=1):
            console.print(
                f"  {idx}. {item.get('file')}:{item.get('line')} "
                f"{item.get('function')} | {item.get('rationale')}"
            )

    patch_sketch = parsed_analyze.get("patch_sketch")
    if patch_sketch:
        console.print("[cyan]Patch Sketch:[/cyan]")
        console.print(f"[white]{patch_sketch}[/white]")

    print_list_section("Evidence", parsed_analyze.get("evidence"))
    print_list_section("Verification TODO", parsed_analyze.get("verification_todo"))
    print_kv("Uncertainty", parsed_analyze.get("uncertainty"))

@contextmanager
def catch_error(desc):
    main_log.info(f"Starting: {desc}")
    try:
        yield
    except Exception as e:
        main_log.error(f"{desc} failed: {e}")
        sys.exit(1)
    main_log.info(f"Completed: {desc}")
        
console = Console()

main_log.info("Starting kdump analysis tool...")

arg = argparse.ArgumentParser()
arg.add_argument('--config', type=str, required=True, help='the config file path')
args = arg.parse_args()

config_path = Path(args.config)
if not config_path.exists():
    raise FileNotFoundError(f"Config file {config_path} does not exist.")

with open(config_path, 'r') as file:
    config = yaml.safe_load(file)
        
linux = config.get('linux_path', './linux')
gdb = config.get('gdb_path', 'gdb')
vmcore = config.get('vmcore', './vmcore')
kdump_server = config.get('kdump_server', './kdump_server')
syzbot_data = config.get('syzbot_data', './syzbot_data')
enable_rag = config.get('enable_rag', False)
linux_path = os.path.abspath(linux)
vmcore = os.path.abspath(vmcore)
kdump_server = os.path.abspath(kdump_server)
syzbot_data = os.path.abspath(syzbot_data)

# Normalize gdb path
if '/' in gdb:
    gdb = os.path.abspath(gdb)

# Display configuration table
table = Table(title="Configuration Summary", show_header=True, header_style="bold magenta")
table.add_column("Setting", style="cyan", width=20)
table.add_column("Value", style="green")

table.add_row("Linux Path", linux_path)
table.add_row("GDB Path", gdb)
table.add_row("VMCore", vmcore)
table.add_row("Kdump Server", kdump_server)
table.add_row("Syzbot Data", syzbot_data)
table.add_row("RAG Enabled", "Yes" if enable_rag else "No")

console.print(table)

if not Confirm.ask("\nProceed with this configuration?", default=True):
    console.print("[yellow]Operation cancelled by user.[/yellow]")
    sys.exit(0)

# initialize rag
if enable_rag:
    try:
        main_log.info("Initializing analysis RAG system...")
        rag_retriever = AnalysisRAGManager(base_dir="./cache/rag", use_pageindex=True)
        main_log.info("RAG system initialized successfully")
    except Exception as e:
        main_log.error(f"Failed to initialize RAG system: {e}")
        if Confirm.ask("\nContinue without RAG?", default=False):
            enable_rag = False
            rag_retriever = None
            console.print("[yellow]Continuing without RAG support[/yellow]")
        else:
            console.print("[red]Exiting...[/red]")
            sys.exit(1)
else:
    rag_retriever = None
    
main_log.info("Initializing kdump-gdbserver...")

# initialize kdump analysis
with catch_error("kdump analysis initialization"):
    kdump_analysis = KdumpAnalysis(
        linux=linux_path,
        kdump_server=kdump_server,
        vmcore=vmcore,
        gdb_path=gdb,
    )
    set_kdump_analysis_instance(kdump_analysis)
    
with catch_error("Loading kdump-gdbserver"):
    kdump_analysis.loadKdump()

with catch_error("Loading GDB"):
    kdump_analysis.loadGDB()
    
set_linux_path(linux_path)

# we need config to extract kernel function and macros
if not os.path.exists(config_path):
    raise FileNotFoundError(f".config file not found in linux path: {linux_path}")

with catch_error("Initializing code query tool"):
    set_proj_path(linux_path)
    create_cq_db(linux_path)
    
with catch_error("Running search agent"):    
    result = runSearchAgent()

if result is None:
    main_log.error("Failed to get output from search agent")
    exit(1)

if isinstance(result, KnownBugAnalysisResult):
    # Parse the structured result
    parsed_result = parse_search_results(result)
    
    if parsed_result['is_known_bug']:
        main_log.info(f"Known bug found: {parsed_result['matched_url']}")
    else:
        main_log.info("No known bug found")
    render_search_results(parsed_result)
    
else:
    main_log.error("Unexpected result type from search agent")
    exit(1)

if not parsed_result['is_known_bug']:
    main_log.info("No known bug found, proceeding with root cause analysis...")
    rag_context_text = None
    rag_payload = None
    crash_report_text = ""

    if enable_rag and rag_retriever:
        with catch_error("Building RAG context"):
            crash_report_raw = getCrashReport.invoke({})
            crash_report_text = crash_report_raw if isinstance(crash_report_raw, str) else str(crash_report_raw)
            rag_payload = rag_retriever.build_pre_analysis_context(crash_report_text, top_k=3)
            rag_context_text = rag_payload.get("context")
            main_log.info("Built pre-analysis RAG context")

    with catch_error("Running analyze agent"):
        analyze_output = runAnalyzeAgent(
            rag_context=rag_context_text,
            return_trace=bool(enable_rag and rag_retriever),
        )

    analyze_trace = {}
    if isinstance(analyze_output, tuple):
        analyze_result, analyze_trace = analyze_output
    else:
        analyze_result = analyze_output

    if analyze_result is None:
        main_log.error("Failed to get output from analyze agent")
        sys.exit(1)

    if isinstance(analyze_result, RootCauseAnalysisResult):
        parsed_analyze = analyze_result.model_dump()

        main_log.info("Root cause analysis completed")
        render_analyze_results(parsed_analyze)

        if enable_rag and rag_retriever:
            with catch_error("Persisting successful analysis experience"):
                if not crash_report_text:
                    crash_report_raw = getCrashReport.invoke({})
                    crash_report_text = crash_report_raw if isinstance(crash_report_raw, str) else str(crash_report_raw)
                case_id = rag_retriever.persist_success_case(
                    crash_report=crash_report_text,
                    analysis_result=parsed_analyze,
                    trace=analyze_trace,
                    retrieved_context=rag_payload,
                )
                main_log.info(f"Stored analysis experience as {case_id}")
    else:
        main_log.error("Unexpected result type from analyze agent")
        sys.exit(1)
