from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.agent_core.tools.fileTools import (
    get_linux_path,
    read_file,
    read_file_by_line_number,
    set_linux_path,
)
from src.agent_core.tools.gdbTools import execute_gdb_command, set_kdump_analysis_instance


class DummyKdumpAnalysis:
    def __init__(self):
        self.commands = []

    def execute(self, command: str):
        self.commands.append(command)
        return {"result": "success", "output": [f"executed: {command}"]}


def _print_result(test_name: str, passed: bool, detail: str) -> None:
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {test_name}: {detail}")


def _expect_error(result, expected_substring: str) -> tuple[bool, str]:
    if isinstance(result, dict):
        output = " ".join(result.get("output", []))
    else:
        output = str(result)
    passed = expected_substring in output
    return passed, output


def run_security_tests() -> None:
    repo_root = REPO_ROOT
    linux_root = (repo_root / "kernel" / "linux").resolve()
    set_linux_path(str(linux_root))

    dummy = DummyKdumpAnalysis()
    set_kdump_analysis_instance(dummy)

    print("Starting security tests...")
    print(f"Linux source root: {get_linux_path()}")

    allowed_target = "README"
    result = read_file.func(allowed_target)
    passed = isinstance(result, str) and not result.startswith("❌")
    detail = "read_file can read linux source file" if passed else str(result)
    _print_result("read_file allows linux source file", passed, detail)

    result = read_file_by_line_number.func(allowed_target, 1, 2)
    passed = isinstance(result, str) and not result.startswith("❌")
    detail = "read_file_by_line_number can read linux source file" if passed else str(result)
    _print_result("read_file_by_line_number allows linux source file", passed, detail)

    blocked_file_paths = [
        "/etc/passwd",
        str((repo_root / ".env").resolve()),
        "../README.md",
        "../../etc/passwd",
    ]
    for blocked_path in blocked_file_paths:
        result = read_file.func(blocked_path)
        passed, output = _expect_error(result, "Access denied")
        _print_result(f"read_file blocks {blocked_path}", passed, output)

        result = read_file_by_line_number.func(blocked_path, 1, 1)
        passed, output = _expect_error(result, "Access denied")
        _print_result(f"read_file_by_line_number blocks {blocked_path}", passed, output)

    symlink_path = repo_root / "security_test" / "linux_escape_link"
    if not symlink_path.exists():
        symlink_path.symlink_to("/etc/passwd")
    result = read_file.func(str(symlink_path))
    passed, output = _expect_error(result, "Access denied")
    _print_result("read_file blocks symlink escape", passed, output)

    blocked_gdb_commands = [
        "quit",
        "q",
        "shell rm -rf /tmp/agent4kdump-test",
        "!rm -rf /tmp/agent4kdump-test",
        "shell ls; rm -rf /tmp/agent4kdump-test",
        "!ls && rm -rf /tmp/agent4kdump-test",
        "continue",
    ]
    for command in blocked_gdb_commands:
        before = list(dummy.commands)
        result = execute_gdb_command.func(command)
        passed, output = _expect_error(result, "Command blocked for safety")
        passed = passed and before == dummy.commands
        _print_result(f"execute_gdb_command blocks '{command}'", passed, output)

    allowed_gdb_commands = [
        "bt",
        "info registers",
    ]
    for command in allowed_gdb_commands:
        result = execute_gdb_command.func(command)
        passed = result.get("result") == "success" and dummy.commands[-1] == command
        _print_result(f"execute_gdb_command allows '{command}'", passed, str(result))

    print("Security tests completed.")


if __name__ == "__main__":
    run_security_tests()
