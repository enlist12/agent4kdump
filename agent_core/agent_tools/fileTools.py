from langchain_core.tools import tool
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))) 
import json
from typing import Annotated
from main import config_path

configMap = {}

@tool
def read_config(
    config: Annotated[str, "The config name, e.g., CONFIG_KASAN"]
) -> Annotated[bool, "whether the config is enabled"]:
    """
    this tool is used to make sure whether the config is enabled
    
    Args:
        config: the config name,e.g., CONFIG_KASAN
        
    Returns:
        whether the config is enabled
    """
    if not configMap:
        with open(config_path, 'r') as file:
            for line in file:
                line = line.strip()
                if line.startswith("# CONFIG_"):
                    key = line.split()[1]
                    configMap[key] = False
                elif line.startswith("CONFIG_"):
                    if '=' in line:
                        key,value = line.split('=',1)
                        if value == 'y':
                            configMap[key] = True
                        else:
                            configMap[key] = False
    if config not in configMap:
        return False
    return configMap[config]

@tool
def read_file_by_line_number(
    file_path: Annotated[str, "The path of the file (absolute path required)"],
    line_number: Annotated[int, "The line number to read (starting from 1)"],
    line_range: Annotated[int, "The context range of the line number, default is 10 lines"] = 10
) -> Annotated[str, "Context content of the specified line"]:
    """
    This tool is used to read the context content of a specified line number in a file.

    Args:
        file_path (str): The path of the file (absolute path required)
        line_number (int): The line number to read (starting from 1)
        line_range (int): The context range of the line number, default is 10 lines

    Returns:
        str: The context content of the specified line, or error message if line number is out of range.

    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        total_lines = len(lines)
        if line_number < 1 or line_number > total_lines:
            return f"❌ Line number out of range (total lines: {total_lines})"

        start = max(0, line_number - line_range - 1)
        end = min(total_lines, line_number + line_range)

        context_lines = []
        for i in range(start, end):
            prefix = " => " if i == line_number - 1 else "    "
            cur = lines[i].rstrip('\n')
            context_lines.append(f"{prefix}{cur}")

        return "\n".join(context_lines)

    except FileNotFoundError:
        return f"❌ File not found: {file_path}"
    except PermissionError:
        return f"❌ Permission denied: {file_path}"
    except json.JSONDecodeError:
        return "❌ Input is not a valid JSON string"
    except Exception as e:
        return f"❌ Failed to read file: {e}"
    
@tool
def read_file(
    file_path: Annotated[str, "The path of the file (absolute path required)"]
) -> Annotated[str, "Complete content of the file"]:
    """
    This tool is used to read the content of a file at the specified path.
    If there is an error reading the file, please make sure the path is absolute.
    
    Args:
        file_path (str): The path of the file
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return content
    except Exception as e:
        return f"❌ Failed to read file: {e}"