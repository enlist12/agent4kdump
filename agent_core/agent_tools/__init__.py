from .commandTools import safe_shell_command
from .gdbTools import execute_gdb_command
from .fileTools import read_file, read_file_by_line_number
from .WebSearch import web_search, fetch_webpage_content
from .codeQuery import CODEQUERY_TOOLS

CUSTOM_AGENT_TOOLS = {
    safe_shell_command:"Execute allowed shell commands safely",
    execute_gdb_command:"Execute a GDB command to analyze kernel dump (vmcore) via kdump-gdbserver",
    read_file:"Read the content of a file at the specified path",
    read_file_by_line_number:"Read the context content of a specified line number in a file",
    web_search:"Search the web for information related to kernel bugs, CVEs, patches, and technical documentation",
    fetch_webpage_content:"Fetch and extract the main text content from a webpage",
}


if __name__ == "__main__":
    print("This is the agent_tools package. It provides various tools for the agent core.")