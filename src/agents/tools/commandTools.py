import os
from typing import Any, List

try:
    from langchain.agents.middleware import HostExecutionPolicy, ShellToolMiddleware
except ImportError:
    HostExecutionPolicy = None
    ShellToolMiddleware = None

# Global workspace root for ShellToolMiddleware.
SHELL_WORKSPACE_ROOT = os.getenv("SHELL_TOOL_WORKSPACE_ROOT") or os.getcwd()

# extend in future if needed
ALLOWED_COMMANDS = {
    # Basic file operations
    "find": ["find"],
    "cat": ["cat"],
    "grep": ["grep"],
    "head": ["head"],
    "tail": ["tail"],
    "wc": ["wc"],
    "sort": ["sort"],
    "uniq": ["uniq"],
    # Binary analysis tools
    "nm": ["nm"],  # List symbols from object files
    "addr2line": ["addr2line"],  # Convert addresses to file/line
    "objdump": ["objdump"],  # Display object file information
    "readelf": ["readelf"],  # Display ELF file information
    "strings": ["strings"],  # Extract printable strings
    "file": ["file"],  # Determine file type
    # Debugging and analysis
    "hexdump": ["hexdump"],  # Hexadecimal dump
    "xxd": ["xxd"],  # Make a hexdump or reverse
    # System info
    "uname": ["uname"],  # System information
    "which": ["which"],  # Locate a command
    "ls": ["ls"],
}


def build_shell_middleware() -> List[Any]:
    """
    Build middleware list that enables ShellToolMiddleware for agents.
    """
    if HostExecutionPolicy is None or ShellToolMiddleware is None:
        return []
    return [
        ShellToolMiddleware(
            workspace_root=SHELL_WORKSPACE_ROOT,
            execution_policy=HostExecutionPolicy(),
        )
    ]


def test_command_tools():
    """
    Smoke test for ShellToolMiddleware configuration.
    """
    print("Starting commandTools tests...")

    middleware = build_shell_middleware()
    print(f"Middleware count: {len(middleware)}")
    print(f"Middleware type: {type(middleware[0]).__name__}")
    print(f"Workspace root: {SHELL_WORKSPACE_ROOT}")

    print("\ncommandTools tests completed.")
