import subprocess
from typing import List, Optional, Annotated
from langchain.tools import tool

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
}

@tool
def safe_shell_command(
    command_alias: Annotated[str, "The alias of the command to execute (must be in ALLOWED_COMMANDS)"],
    cmd_args: Annotated[Optional[List[str]], "Additional arguments for the command"] = None
) -> Annotated[str, "Output of the shell command"]:
    """
    Execute allowed shell commands safely
    
    Args:
        command_alias (str): The alias of the command to execute (must be in ALLOWED_COMMANDS)
        cmd_args (List[str], optional): Additional arguments for the command
        
    Returns:
        str: The output of the command or error message
    """
    if command_alias not in ALLOWED_COMMANDS:
        return f"Error: Command '{command_alias}' is not allowed. Allowed commands: {list(ALLOWED_COMMANDS.keys())}"
    
    try:
        full_command = ALLOWED_COMMANDS[command_alias].copy()
        if cmd_args:
            full_command.extend(cmd_args)
    
        result = subprocess.run(
            full_command,
            capture_output=True,
            text=True,
            timeout=60,
            check=False
        )
        
        output = result.stdout.strip()
        if result.stderr:
            output += f"\n[stderr] {result.stderr.strip()}"
        if result.returncode != 0 and not output:
            output = f"Command failed with exit code {result.returncode}"
            
        return output
        
    except subprocess.TimeoutExpired:
        return "Error: Command timed out."
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
    print("\n[Test] Disallowed command: ls (assuming not in list)")
    output = safe_shell_command.func("ls", ["-la"])
    print(f"Result: {output}")

    # 4. Test error handling (non-existent file for cat)
    print("\n[Test] Error handling: cat non-existent")
    output = safe_shell_command.func("cat", ["/path/to/nothing"])
    print(f"Result: {output}")

    print("\ncommandTools tests completed.")
