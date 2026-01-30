import subprocess
from typing import List, Optional, Annotated
from langchain.tools import tool
try:
    from langchain_community.tools import ShellTool
except ImportError:
    # Fallback/Placeholder if dependency is missing, though user said usage is direct.
    ShellTool = None

#extend in future if needed
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
    "nm": ["nm"],                    # List symbols from object files
    "addr2line": ["addr2line"],      # Convert addresses to file/line
    "objdump": ["objdump"],          # Display object file information
    "readelf": ["readelf"],          # Display ELF file information
    "strings": ["strings"],          # Extract printable strings
    "file": ["file"],                # Determine file type
    
    # Debugging and analysis
    "hexdump": ["hexdump"],          # Hexadecimal dump
    "xxd": ["xxd"],                  # Make a hexdump or reverse
    
    # System info
    "uname": ["uname"],              # System information
    "which": ["which"],              # Locate a command
    "ls": ["ls"],           
}

@tool
def safe_shell_command(
    command_alias: Annotated[str, "The alias of the command to execute (must be in ALLOWED_COMMANDS)"],
    cmd_args: Annotated[Optional[List[str]], "Additional arguments for the command"] = None
) -> Annotated[str, "Output of the shell command"]:
    """
    Execute allowed shell commands safely
    """
    if command_alias not in ALLOWED_COMMANDS:
        return f"Error: Command '{command_alias}' is not allowed. Allowed commands: {list(ALLOWED_COMMANDS.keys())}"
    
    # Construct the command string from alias and args
    full_command_parts = ALLOWED_COMMANDS[command_alias].copy()
    if cmd_args:
        full_command_parts.extend(cmd_args)
    
    # Clean up arguments to form a string command for ShellTool
    # Note: ShellTool executes string in shell. 
    # We reconstruct the command line string.
    # Simple join might be risky with spaces, but ShellTool expects a string.
    # For better safety/correctness, we should quote arguments if they contain spaces, 
    # but here we trust the split logic or just join safely.
    import shlex
    full_command_str = shlex.join(full_command_parts)

    try:
        shell_tool = ShellTool()
        return shell_tool.run(full_command_str)
    except Exception as e:
        return f"Error executing command: {str(e)}"

def test_command_tools():
    """
    Test suite for commandTools functions.
    """
    print("Starting commandTools tests...")
    
    # 1. Test allowed command: uname
    print("\n[Test] Allowed command: uname")
    output = safe_shell_command.func("uname", ["-a"])
    print(f"Result: {output}")

    # 2. Test allowed command with args: cat specific file
    print("\n[Test] Allowed command: cat /root/agent4kdump/kernel/linux/README")
    readme_path = "/root/agent4kdump/kernel/linux/README"
    output = safe_shell_command.func("cat", [readme_path])
    
    if "Error" in output or "failed" in output.lower():
        print(f"Command failed: {output}")
    else:
        print(f"Command success. Output length: {len(output)}")
        print(f"Snippet: {output[:100]}...")

    # 3. Test disallowed command
    print("\n[Test] Disallowed command: lsmod (assuming not in list)")
    output = safe_shell_command.func("lsmod", [])
    print(f"Result: {output}")

    # 4. Test error handling (non-existent file for cat)
    print("\n[Test] Error handling: cat non-existent")
    output = safe_shell_command.func("cat", ["/path/to/nothing"])
    print(f"Result: {output}")

    print("\ncommandTools tests completed.")
