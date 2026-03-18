import argparse
import yaml  
from pathlib import Path
import sys
from log import *
from agent_core.embedding import EmbeddingModel
from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm
from kdump_analyze.kdump import KdumpAnalysis
import os
from agent_core.tools.codeQuery.codequery import create_cq_db, set_proj_path
from agent_core.tools.gdbTools import set_kdump_analysis_instance
from agent_core.tools.fileTools import set_linux_path
from contextlib import contextmanager
from agents.search_agent import runSearchAgent,parse_search_results, KnownBugAnalysisResult
from agents.analyze_agent import runAnalyzeAgent, parse_analyze_results, RootCauseAnalysisResult

config_path = None
kdump_analysis = None
linux_path = None

main_log = get_logger("Main")

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
    if not syzbot_data:
        #console.print("[red]Error: RAG is enabled but syzbot_data path is not provided.[/red]")
        main_log.error("RAG enabled but syzbot_data path missing")
        sys.exit(1)
    
    try:
        main_log.info("Initializing RAG retrieval system...")
        #console.print("[cyan]Initializing RAG retrieval system...[/cyan]")
        rag_retriever = EmbeddingModel(data_dir=syzbot_data)
        
        if not hasattr(rag_retriever, 'client') or rag_retriever.client is None:
            raise ValueError("Failed to initialize OpenAI client, please check your API key")
        
        #console.print("[cyan]Building RAG index...[/cyan]")
        rag_retriever.build_index()
        #console.print("[green]✓ RAG system initialized successfully[/green]")
        main_log.info("RAG system initialized successfully")
    except Exception as e:
        #console.print(f"[red]Error initializing RAG system: {e}[/red]")
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
        
    console.print(f"[blue]Evidence: {parsed_result['evidence']}[/blue]")
    
    if parsed_result['extra_info']:
        console.print(f"[red]Extra Info: {parsed_result['extra_info']}[/red]")
    
else:
    main_log.error("Unexpected result type from search agent")
    exit(1)

if not parsed_result['is_known_bug']:
    main_log.info("No known bug found, proceeding with root cause analysis...")

    with catch_error("Running analyze agent"):
        analyze_result = runAnalyzeAgent()

    if analyze_result is None:
        main_log.error("Failed to get output from analyze agent")
        sys.exit(1)

    if isinstance(analyze_result, RootCauseAnalysisResult):
        parsed_analyze = parse_analyze_results(analyze_result)

        main_log.info("Root cause analysis completed")
        console.print("\n[bold green]Root Cause Analysis Result[/bold green]")
        console.print(f"[cyan]Root Cause:[/cyan] {parsed_analyze['root_cause']}")
        console.print(f"[cyan]Trigger Path:[/cyan] {parsed_analyze['trigger_path']}")
        console.print(f"[cyan]Fix Suggestion:[/cyan] {parsed_analyze['fix_suggestion']}")
        console.print(f"[cyan]Confidence:[/cyan] {parsed_analyze['confidence']}")

        if parsed_analyze['uncertainty']:
            console.print(f"[yellow]Uncertainty:[/yellow] {parsed_analyze['uncertainty']}")

        if parsed_analyze['evidence']:
            console.print("[cyan]Evidence:[/cyan]")
            for idx, item in enumerate(parsed_analyze['evidence'], start=1):
                console.print(f"  {idx}. {item}")
    else:
        main_log.error("Unexpected result type from analyze agent")
        sys.exit(1)