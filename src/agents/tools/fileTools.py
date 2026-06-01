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


configMap = {}
MAX_FULL_READ_LINES = 200


def _resolve_linux_source_path(file_path: str) -> str:
    linux_root = path.realpath(get_linux_path())
    candidate_path = file_path
    if not path.isabs(candidate_path):
        candidate_path = path.join(linux_root, candidate_path)
    real_candidate_path = path.realpath(candidate_path)
    if real_candidate_path != linux_root and not real_candidate_path.startswith(
        linux_root + os.sep
    ):
        raise PermissionError(
            f"Access denied: '{file_path}' is outside linux source tree '{linux_root}'"
        )
    return real_candidate_path


@timed_tool(timeout_seconds=10, timeout_factory=lambda _name, _sec: False)
def read_config(
    config_name: Annotated[str, "The config name, e.g., CONFIG_KASAN"],
) -> Annotated[bool, "whether the config is enabled"]:
    """
    Used to make sure whether the config is enabled
    """
    if not configMap:
        with open(path.join(get_linux_path(), ".config"), "r") as file:
            for line in file:
                line = line.strip()
                if line.startswith("# CONFIG_"):
                    key = line.split()[1]
                    configMap[key] = False
                elif line.startswith("CONFIG_"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        if value == "y":
                            configMap[key] = True
                        else:
                            configMap[key] = False
    if config_name not in configMap:
        return False
    return configMap[config_name]


@timed_tool(timeout_seconds=10)
def read_source(
    file_path: Annotated[str, "The path of the file"],
    line_number: Annotated[int | None, "Optional 1-based line number for contextual snippet"] = None,
    line_range: Annotated[int, "Context range around line_number when reading a snippet"] = 10,
    mode: Annotated[str, "Use 'snippet' for contextual lines or 'full' for the entire file"] = "snippet",
) -> Annotated[str, "Source content from the specified file"]:
    """
    Read kernel source content from a file.
    Prefer snippet mode with a line number for focused context. Use full mode only when necessary.
    """
    try:
        file_path = _resolve_linux_source_path(file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            if mode == "full":
                lines = f.readlines()
                if len(lines) > MAX_FULL_READ_LINES:
                    return (
                        f"❌ File is too large to read in full mode "
                        f"({len(lines)} lines > {MAX_FULL_READ_LINES} lines). "
                        "Please use mode='snippet' with line_number and line_range to read focused context."
                    )
                return "".join(lines)
            lines = f.readlines()

        if mode != "snippet":
            return f"❌ Unsupported mode: {mode}"
        if line_number is None:
            return "❌ line_number is required when mode='snippet'"

        total_lines = len(lines)
        if line_number < 1 or line_number > total_lines:
            return f"❌ Line number out of range (total lines: {total_lines})"
        start = max(0, line_number - line_range - 1)
        end = min(total_lines, line_number + line_range)

        context_lines = []
        for i in range(start, end):
            prefix = " => " if i == line_number - 1 else "    "
            cur = lines[i].rstrip("\n")
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

    # 2. Test read_source snippet mode
    print("\n[Test] read_source snippet")
    # Normal case: Read Makefile first few lines
    if os.path.exists(MAKEFILE_PATH):
        content = read_source.func(MAKEFILE_PATH, 1, 5, "snippet")
        print(f"read_source('{MAKEFILE_PATH}', 1, 5, 'snippet'):\n{content}")
    else:
        print(f"⚠️ {MAKEFILE_PATH} not found, skipping normal read test")

    # Error case: Out of range
    if os.path.exists(README_PATH):
        content = read_source.func(README_PATH, 100000, 10, "snippet")
        print(f"read_source (Out of range): {content}")

    # Error case: File not found
    content = read_source.func("/root/non_existent_file.txt", 1, 10, "snippet")
    print(f"read_source (File not found): {content}")

    # 3. Test read_source full mode
    print("\n[Test] read_source full")
    if os.path.exists(README_PATH):
        content = read_source.func(README_PATH, mode="full")
        if hasattr(content, "startswith") and content.startswith("❌"):
            print(f"read_source('{README_PATH}', mode='full') Failed: {content}")
        else:
            print(f"read_source('{README_PATH}', mode='full') Success, length: {len(content)} chars")
            print(f"Snippet: {content[:100]}...")
    else:
        print(f"⚠️ {README_PATH} not found, skipping read_source full test")

    # Error case: File not found
    content = read_source.func("/root/non_existent_file.txt", mode="full")
    print(f"read_source full (File not found): {content}")

    print("\nfileTools tests completed.")
