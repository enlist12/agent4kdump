import subprocess
from typing import List, Optional
from langchain.tools import tool
from typing import Annotated

#extend in future if needed
ALLOWED_COMMANDS = {
    # "ls": ["ls", "-la"],
    # "echo": ["echo"],
    # "pwd": ["pwd"],
    "find": ["find"],
    "cat": ["cat"],
    "grep": ["grep"],
    "nm": ["nm"],
}

@tool
def safe_shell_command(
    command_alias: str,
    cmd_args: Optional[List[str]] = None
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
