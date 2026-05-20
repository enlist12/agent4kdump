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
read_file = _load(
    "read_file",
    lambda: __import__("agents.tools.fileTools", fromlist=["read_file"]).read_file,
)
read_file_by_line_number = _load(
    "read_file_by_line_number",
    lambda: __import__(
        "agents.tools.fileTools", fromlist=["read_file_by_line_number"]
    ).read_file_by_line_number,
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
create_sub_agent = _load(
    "create_sub_agent",
    lambda: __import__("agents.tools.agent", fromlist=["create_sub_agent"]).create_sub_agent,
)
chat_with_sub_agent = _load(
    "chat_with_sub_agent",
    lambda: __import__("agents.tools.agent", fromlist=["chat_with_sub_agent"]).chat_with_sub_agent,
)
list_sub_agents = _load(
    "list_sub_agents",
    lambda: __import__("agents.tools.agent", fromlist=["list_sub_agents"]).list_sub_agents,
)
remove_sub_agent = _load(
    "remove_sub_agent",
    lambda: __import__("agents.tools.agent", fromlist=["remove_sub_agent"]).remove_sub_agent,
)

try:
    from .codeQuery import CODEQUERY_TOOLS
except Exception:
    CODEQUERY_TOOLS = {}

CUSTOM_AGENT_TOOLS = {
    "Execute a GDB command to analyze kernel dump (vmcore) via kdump-gdbserver": execute_gdb_command,
    "Read the content of a file at the specified path": read_file,
    "Read the context content of a specified line number in a file": read_file_by_line_number,
    "Search the web for information related to kernel bugs, CVEs, patches, and technical documentation": web_search,
    "Fetch and extract the main text content from a webpage": fetch_webpage_content,
    "Check whether a specific kernel configuration option is enabled in the kernel config file": read_config,
    "Get the crash report from kdump-gdbserver": getCrashReport,
    "Create a new sub-agent with a specific system prompt and name": create_sub_agent,
    "Instruct an existing sub-agent by its ID": chat_with_sub_agent,
    "List all existing sub-agents with their IDs and names": list_sub_agents,
    "Remove an existing sub-agent by its ID": remove_sub_agent,
}
