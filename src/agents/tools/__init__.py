from __future__ import annotations

from typing import Callable

from langchain_core.tools import tool


def _load(name: str, loader: Callable):
    try:
        return loader()
    except Exception as exc:
        reason = str(exc)

        @tool(name, description=f"Unavailable tool placeholder for {name}.")
        def unavailable() -> str:
            """Report that an optional tool dependency is unavailable."""
            return f"Tool '{name}' is unavailable: {reason}"

        return unavailable


execute_gdb_command = _load(
    "execute_gdb_command",
    lambda: __import__(
        "agents.tools.gdbTools", fromlist=["execute_gdb_command"]
    ).execute_gdb_command,
)
getCrashReport = _load(
    "getCrashReport",
    lambda: __import__("agents.tools.gdbTools", fromlist=["getCrashReport"]).getCrashReport,
)
read_source = _load(
    "read_source",
    lambda: __import__("agents.tools.fileTools", fromlist=["read_source"]).read_source,
)
read_config = _load(
    "read_config",
    lambda: __import__("agents.tools.fileTools", fromlist=["read_config"]).read_config,
)
web_search = _load(
    "web_search",
    lambda: __import__("agents.tools.WebSearch", fromlist=["web_search"]).web_search,
)
fetch_webpage_content = _load(
    "fetch_webpage_content",
    lambda: __import__(
        "agents.tools.WebSearch", fromlist=["fetch_webpage_content"]
    ).fetch_webpage_content,
)
manage_sub_agent = _load(
    "manage_sub_agent",
    lambda: __import__("agents.tools.agent", fromlist=["manage_sub_agent"]).manage_sub_agent,
)
message_sub_agent = _load(
    "message_sub_agent",
    lambda: __import__("agents.tools.agent", fromlist=["message_sub_agent"]).message_sub_agent,
)

try:
    from .codeQuery import CODEQUERY_TOOLS
except Exception:
    CODEQUERY_TOOLS = {}

CUSTOM_AGENT_TOOLS = {
    "Execute a GDB command to analyze kernel dump (vmcore) via kdump-gdbserver": execute_gdb_command,
    "Read kernel source as a focused snippet or full file when necessary": read_source,
    "Search the web for information related to kernel bugs, CVEs, patches, and technical documentation": web_search,
    "Fetch and extract the main text content from a webpage": fetch_webpage_content,
    "Check whether a specific kernel configuration option is enabled in the kernel config file": read_config,
    "Get the crash report from kdump-gdbserver": getCrashReport,
    "Manage sub-agents by creating, listing, or removing them": manage_sub_agent,
    "Send a message to an existing sub-agent by ID": message_sub_agent,
}
