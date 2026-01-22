from .commandTools import safe_shell_command
from .gdbTools import execute_gdb_command, getCrashReport
from .fileTools import read_file, read_file_by_line_number, read_config
from .WebSearch import web_search, fetch_webpage_content
from .agent import create_sub_agent, chat_with_sub_agent, list_sub_agents, remove_sub_agent
from .codeQuery import CODEQUERY_TOOLS

CUSTOM_AGENT_TOOLS = {
    "Execute allowed shell commands safely": safe_shell_command,
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
    "Remove an existing sub-agent by its ID": remove_sub_agent
}


if __name__ == "__main__":
    print("This is the agent_tools package. It provides various tools for the agent core.")
    """
    test tools here
    """
    #TODO: add test code
    pass