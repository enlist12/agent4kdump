import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pwn import process
from pygdbmi.gdbcontroller import GdbController

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from log import get_logger

CRASH_WORDS = [
    "BUG:",
    "Oops:",
    "Kernel panic",
    "general protection fault",
]

END_WORDS = ["---[ end"]

TEMP_REPORT_FILE = os.path.join(os.path.dirname(__file__), "temp_report.txt")


class KdumpAnalysis:
    """Wrapper around kdump-gdbserver + gdb/mi for vmcore crash analysis."""

    def __init__(
        self,
        linux: str,
        kdump_server: str,
        vmcore: str,
        port: int = 1234,
        gdb_path: str = "gdb",
    ) -> None:
        """Initialize paths, validate required tools/files, and prepare runtime state."""
        self.logger = get_logger("kdump")

        self.linux = os.path.abspath(linux)
        self.vmcore = os.path.abspath(vmcore)
        self.port = int(port)

        exists, resolved_kdump = self.checkTool(kdump_server)
        if not exists or not resolved_kdump:
            raise FileNotFoundError(f"kdump-gdbserver tool not found: {kdump_server}")
        self.kdump_server = resolved_kdump

        exists, resolved_gdb = self.checkTool(gdb_path)
        if not exists or not resolved_gdb:
            raise FileNotFoundError(f"gdb tool not found: {gdb_path}")
        self.gdb_path = resolved_gdb

        if not os.path.exists(self.vmcore):
            raise FileNotFoundError(f"vmcore file not found: {self.vmcore}")

        self.crash_word = list(CRASH_WORDS)
        self.temp_file = TEMP_REPORT_FILE

        self.crash_report: Optional[str] = None
        self.gdb: Optional[GdbController] = None
        self.kdump = None

        self.logger.info("initialize kdump analysis module")

    @staticmethod
    def checkTool(tool: str) -> Tuple[bool, Optional[str]]:
        """Check whether a tool is executable via PATH or as a direct path."""
        tool_path = shutil.which(tool)
        if tool_path:
            return True, tool_path

        if not os.path.isabs(tool):
            tool_path = os.path.join(os.path.dirname(__file__), tool)
        else:
            tool_path = tool

        if os.path.exists(tool_path) and os.access(tool_path, os.X_OK):
            return True, tool_path
        return False, None

    @staticmethod
    def _normalize_gdb_output_line(line: str) -> str:
        """Normalize one lx-dmesg line: remove gdb artifacts and noisy prefixes."""
        line = line.strip()
        if line.endswith('\\n"'):
            line = line[:-3]

        if "] " in line:
            line = line.split("] ", 1)[1]

        if line.startswith(" ?"):
            line = line[2:]

        return line

    @staticmethod
    def parseOutput(msg: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Parse gdb/mi output and return a uniform result dict."""
        output: List[str] = []
        result: Optional[str] = None

        for item in msg:
            item_type = item.get("type")
            payload = item.get("payload")

            if item_type in {"console", "output"} and payload is not None:
                output.append(str(payload))
                continue

            if item_type == "result":
                if item.get("message") == "error":
                    err_msg = payload.get("msg") if isinstance(payload, dict) else payload
                    output.append(str(err_msg))
                    result = "error"
                else:
                    result = "success"

        return {"result": result, "output": output}

    def execute(self, command: str) -> Dict[str, Any]:
        """Execute one gdb command through gdb/mi."""
        try:
            if not self.gdb:
                return {"result": "error", "output": ["gdb is not alive"]}

            self.logger.info("execute gdb command: %s", command)
            output = self.gdb.write(command, timeout_sec=5)
            return self.parseOutput(output)
        except Exception as exc:
            self.logger.error("Failed to execute gdb command: %s, error: %s", command, exc)
            return {"result": "error", "output": [str(exc)]}

    def loadKdump(self) -> None:
        """Start kdump-gdbserver and verify that remote target endpoint is ready."""
        self.logger.info("Initializing kdump server")

        ready_banner = f"target remote localhost:{self.port}".encode()
        args = [self.kdump_server, "-p", str(self.port), "-f", self.vmcore]

        try:
            self.kdump = process(args)
            output = self.kdump.recvuntil(ready_banner, timeout=30)
        except Exception as exc:
            self.logger.error("Initialize kdump-gdbserver failed: %s", exc)
            raise RuntimeError("Initialize kdump-gdbserver failed") from exc

        if ready_banner not in output:
            raise RuntimeError("kdump-gdbserver connect vmcore failed")

    def _ensure_gdb_success(self, result: Dict[str, Any], error_msg: str) -> None:
        """Raise RuntimeError when execute() returns error result."""
        if result.get("result") == "error":
            details = "\\n".join(result.get("output", []))
            if details:
                self.logger.error("%s: %s", error_msg, details)
            raise RuntimeError(error_msg)

    def loadGDB(self) -> None:
        """Initialize gdb/mi, connect to kdump server, and source kernel gdb helpers."""
        self.logger.info("Initializing GDB")

        try:
            self.gdb = GdbController([self.gdb_path, "--interpreter=mi2"])

            self._ensure_gdb_success(
                self.execute(f"target remote:{self.port}"),
                "connect to kdump-gdbserver failed",
            )

            vmlinux = os.path.join(self.linux, "vmlinux")
            if not os.path.exists(vmlinux):
                raise FileNotFoundError("vmlinux file not found")
            self._ensure_gdb_success(
                self.execute(f"file {vmlinux}"),
                "failed to load vmlinux file",
            )

            script_dir = os.path.join(self.linux, "scripts", "gdb")
            self.execute(f'python sys.path.insert(0, "{script_dir}")')

            gdb_script = os.path.join(script_dir, "vmlinux-gdb.py")
            if not os.path.exists(gdb_script):
                raise FileNotFoundError("vmlinux-gdb.py not found")
            self._ensure_gdb_success(
                self.execute(f"source {gdb_script}"),
                "failed to source vmlinux-gdb.py",
            )

            self.execute("set pagination off")
        except Exception as exc:
            self.logger.error("Initialize GDB failed: %s", exc)
            raise RuntimeError("Initialize GDB failed") from exc

    @staticmethod
    def extractAddress(text: str) -> Optional[str]:
        """Extract symbol+offset address in trace style `func+0x..../0x....`."""
        pattern = r"[a-zA-Z_][a-zA-Z0-9_]*\+0x[0-9a-fA-F]+(?=/0x[0-9a-fA-F]+)"
        match = re.search(pattern, text)
        return match.group(0) if match else None

    def _find_report_slice(self, report: Sequence[str]) -> List[str]:
        """Locate the crash segment; fallback to last 150 lines when uncertain."""
        start_idx = -1
        end_idx = -1

        for idx, line in enumerate(report):
            if start_idx == -1:
                if any(word in line for word in self.crash_word):
                    start_idx = idx
            else:
                if any(word in line for word in END_WORDS):
                    end_idx = idx

        if start_idx == -1:
            return list(report[-150:])

        if end_idx != -1:
            if end_idx - start_idx <= 20:
                return list(report[-150:])
            return list(report[start_idx : end_idx + 1])

        # Keep previous behavior: when no end marker found, trim several tail lines.
        return list(report[start_idx:-3])

    def _resolve_addr2line(self, tool: str, addr_info: str) -> Optional[str]:
        """Translate one `func+offset` symbol to relative source path:line."""
        vmlinux = os.path.join(self.linux, "vmlinux")
        cmd = [tool, "-e", vmlinux, "-i", "-a", addr_info]

        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
            )
            if not proc.stdout:
                return None

            line = proc.stdout.strip().split("\n")[-1]
            idx = line.find(":")
            if idx == -1:
                return None

            file_path = line[:idx]
            relpath = os.path.relpath(file_path, self.linux)
            return f"{relpath}{line[idx:]}"
        except Exception as exc:
            self.logger.error("Failed to run addr2line for %s: %s", addr_info, exc)
            return None

    def filterCrashReport(self, report: List[str]) -> List[str]:
        """Normalize and enrich crash report text, then return filtered lines."""
        exists, tool = self.checkTool("addr2line")
        if not exists or not tool:
            self.logger.warning("addr2line tool not found, skip address translation")

        filtered = self._find_report_slice(report)

        processed_lines: List[str] = []
        addr_tasks: List[Tuple[int, str]] = []

        for raw_line in filtered:
            line = self._normalize_gdb_output_line(raw_line)
            processed_lines.append(line)

            if exists and tool:
                addr_info = self.extractAddress(line)
                if addr_info:
                    addr_tasks.append((len(processed_lines) - 1, addr_info))

        addr_results: Dict[int, str] = {}
        if addr_tasks and exists and tool:
            max_workers = min(len(addr_tasks), 8)

            def translate(task: Tuple[int, str]) -> Tuple[int, Optional[str]]:
                line_idx, addr_info = task
                return line_idx, self._resolve_addr2line(tool, addr_info)

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(translate, task) for task in addr_tasks]
                for future in as_completed(futures):
                    line_idx, translated = future.result()
                    if translated:
                        addr_results[line_idx] = translated

        output_lines: List[str] = []
        for idx, line in enumerate(processed_lines):
            translated = addr_results.get(idx)
            if translated:
                output_lines.append(f"{line} {translated}")
            else:
                output_lines.append(line)

        return output_lines

    def _prepare_logging_file(self) -> None:
        """Ensure gdb logging file exists and is empty before lx-dmesg capture."""
        Path(self.temp_file).parent.mkdir(parents=True, exist_ok=True)
        with open(self.temp_file, "w", encoding="utf-8") as handle:
            handle.truncate(0)

    def getCrashReport(self) -> Tuple[bool, str]:
        """Capture lx-dmesg report, normalize it, cache it, and return `(status, report)`."""
        try:
            if self.crash_report:
                return True, self.crash_report

            self._prepare_logging_file()

            self.execute(f"set logging file {self.temp_file}")
            self.execute("set logging enabled on")
            self.execute("lx-dmesg")
            self.execute("set logging enabled off")

            with open(self.temp_file, "r", encoding="utf-8", errors="replace") as handle:
                report = handle.readlines()

            report = report[:-2]
            filtered = self.filterCrashReport(report)
            self.crash_report = "\n".join(filtered)
            return True, self.crash_report
        except Exception as exc:
            self.logger.error("Failed to get crash report: %s", exc)
            return False, str(exc)

    def stop(self) -> Tuple[bool, str]:
        """Best-effort teardown for gdb and kdump server processes."""
        try:
            self.logger.info("stop kdump analysis")
            if self.gdb:
                self.gdb.exit()
            if self.kdump:
                self.kdump.close()
            return True, "stop kdump analysis success"
        except Exception as exc:
            self.logger.error("stop kdump analysis failed: %s", exc)
            return False, "stop kdump analysis failed"


if __name__ == "__main__":
    linux = "/root/agent4kdump/kernel/linux-0/linux"
    vmcore = "/root/agent4kdump/case/719da9b149a931f5143f/vmcore"
    crash = "/root/agent4kdump/kdump_analyze/kdump-gdbserver/kdump-gdbserver"
    gdb_path = "gdb"

    kdump = KdumpAnalysis(linux, crash, vmcore, 1234, gdb_path)
    kdump.loadKdump()
    kdump.loadGDB()

    print(kdump.execute("! ls"))
    print(kdump.execute("x/2gx 0xffffffff81000000"))
    print(kdump.execute("info registers"))
    print(kdump.execute("x/2gx 0xzzzzzzzz"))
    print(kdump.execute("hhhhhh"))

    status, report = kdump.getCrashReport()
    print(status)
    print(report)

    status, msg = kdump.stop()
    print(status)
    print(msg)
