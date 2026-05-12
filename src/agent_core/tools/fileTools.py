import json
from typing import Annotated
from os import path
import os
from .tool_timeout import timed_tool
# Global variable to hold the config path
LINUX_PATH = None

def set_linux_path(path):
    """Set the global linux path."""
    global LINUX_PATH
    LINUX_PATH = path

def get_linux_path():
    """Get the global linux path."""
    if LINUX_PATH is None:
        raise RuntimeError("linux_path not set. Call set_linux_path() first.")
    return LINUX_PATH


def _resolve_linux_source_path(file_path: str) -> str:
    """
    Resolve a file path and ensure it stays within the configured linux source tree.
    """
    linux_root = path.realpath(get_linux_path())
    candidate_path = file_path
    if not path.isabs(candidate_path):
        candidate_path = path.join(linux_root, candidate_path)

    real_candidate_path = path.realpath(candidate_path)

    if real_candidate_path != linux_root and not real_candidate_path.startswith(linux_root + os.sep):
        raise PermissionError(
            f"Access denied: '{file_path}' is outside linux source tree '{linux_root}'"
        )

    return real_candidate_path

configMap = {}

@timed_tool(timeout_seconds=10, timeout_factory=lambda _name, _sec: False)
def read_config(
    config_name: Annotated[str, "The config name, e.g., CONFIG_KASAN"]
) -> Annotated[bool, "whether the config is enabled"]:
    """
    Used to make sure whether the config is enabled
    """
    if not configMap:
        with open(path.join(get_linux_path(), ".config"), 'r') as file:
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
    if config_name not in configMap:
        return False
    return configMap[config_name]

@timed_tool(timeout_seconds=10)
def read_file_by_line_number(
    file_path: Annotated[str, "The path of the file"],
    line_number: Annotated[int, "The line number to read (starting from 1)"],
    line_range: Annotated[int, "The context range of the line number, default is 10 lines"] = 10
) -> Annotated[str, "Context content of the specified line"]:
    """
    Used to read the context content of a specified line number in a file.
    """
    try:
        file_path = _resolve_linux_source_path(file_path)
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
    except PermissionError as e:
        return f"❌ {e}"
    except json.JSONDecodeError:
        return "❌ Input is not a valid JSON string"
    except Exception as e:
        return f"❌ Failed to read file: {e}"
    
@timed_tool(timeout_seconds=10)
def read_file(
    file_path: Annotated[str, "The path of the file"]
) -> Annotated[str, "Complete content of the file"]:
    """
    Used to read the content of a file at the specified path.
    If there is an error reading the file, please make sure the path is absolute.
    """
    try:
        file_path = _resolve_linux_source_path(file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return content
    except PermissionError as e:
        return f"❌ {e}"
    except Exception as e:
        return f"❌ Failed to read file: {e}"

def test_file_tools():
    """
    Test suite for fileTools functions.
    Targets kernel source in /root/agent4kdump/kernel/linux
    """
    print("Starting fileTools tests...")
    import os
    
    KERNEL_DIR = "/root/agent4kdump/kernel/linux"
    CONFIG_PATH = os.path.join(KERNEL_DIR, ".config")
    README_PATH = os.path.join(KERNEL_DIR, "README")
    MAKEFILE_PATH = os.path.join(KERNEL_DIR, "Makefile")
    
    # 1. Test read_config
    print("\n[Test] read_config")
    # Setup config path
    try:
        set_linux_path(KERNEL_DIR)
        print(f"Linux path set to: {KERNEL_DIR}")
    except Exception as e:
        print(f"❌ Failed to set linux path: {e}")

    # Test reading a likely existing config
    # Use .func to bypass StructuredTool and test logic directly
    result = read_config.func("CONFIG_64BIT")
    print(f"read_config('CONFIG_64BIT'): {result}")
    
    # Test reading a non-existent config
    result = read_config.func("CONFIG_NON_EXISTENT_FEATURE_XYZ")
    print(f"read_config('CONFIG_NON_EXISTENT_FEATURE_XYZ'): {result} (Expected: False)")

    # 2. Test read_file_by_line_number
    print("\n[Test] read_file_by_line_number")
    # Normal case: Read Makefile first few lines
    if os.path.exists(MAKEFILE_PATH):
        content = read_file_by_line_number.func(MAKEFILE_PATH, 1, 5)
        print(f"read_file_by_line_number('{MAKEFILE_PATH}', 1, 5):\n{content}")
    else:
        print(f"⚠️ {MAKEFILE_PATH} not found, skipping normal read test")

    # Error case: Out of range
    if os.path.exists(README_PATH):
        content = read_file_by_line_number.func(README_PATH, 100000)
        print(f"read_file_by_line_number (Out of range): {content}")
    
    # Error case: File not found
    content = read_file_by_line_number.func("/root/non_existent_file.txt", 1)
    print(f"read_file_by_line_number (File not found): {content}")

    # 3. Test read_file
    print("\n[Test] read_file")
    if os.path.exists(README_PATH):
        content = read_file.func(README_PATH)
        if hasattr(content, 'startswith') and content.startswith("❌"):
             print(f"read_file('{README_PATH}') Failed: {content}")
        else:
             print(f"read_file('{README_PATH}') Success, length: {len(content)} chars")
             print(f"Snippet: {content[:100]}...")
    else:
        print(f"⚠️ {README_PATH} not found, skipping read_file test")
    
    # Error case: File not found
    content = read_file.func("/root/non_existent_file.txt")
    print(f"read_file (File not found): {content}")

    print("\nfileTools tests completed.")
