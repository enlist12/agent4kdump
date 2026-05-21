from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Sequence

from log import get_logger
from pygdbmi.gdbcontroller import GdbController


class KdumpAnalysis:
    """Small wrapper around kdump-gdbserver and a GDB/MI session."""

    def __init__(
        self,
        *,
        linux: str,
        kdump_server: str,
        vmcore: str,
        gdb_path: str = "gdb",
        host: str = "127.0.0.1",
        port: int = 1234,
        kdump_args: Sequence[str] | None = None,
        timeout: int = 30,
    ) -> None:
        self.logger = get_logger("KdumpAnalysis")
        self.linux = Path(linux).resolve()
        self.vmlinux = self.linux / "vmlinux"
        self.gdb_script = self.linux / "scripts/gdb/vmlinux-gdb.py"
        self.kdump_server = kdump_server
        self.vmcore = Path(vmcore).resolve()
        self.gdb_path = gdb_path
        self.host = host
        self.port = port
        self.kdump_args = list(kdump_args or ["{vmcore}"])
        self.timeout = timeout
        self._server: subprocess.Popen[str] | None = None
        self._gdb: GdbController | None = None

    def loadKdump(self) -> None:
        """Start kdump-gdbserver if it is not already running."""
        if self._server and self._server.poll() is None:
            return

        server_args = [
            arg.format(
                vmcore=str(self.vmcore),
                linux=str(self.linux),
                vmlinux=str(self.vmlinux),
                host=self.host,
                port=self.port,
            )
            for arg in self.kdump_args
        ]
        command = [self.kdump_server, *server_args]
        self.logger.info("Starting kdump-gdbserver: %s", " ".join(command))
        self._server = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(0.8)
        if self._server.poll() is not None:
            stdout, stderr = self._server.communicate(timeout=2)
            raise RuntimeError(
                "kdump-gdbserver exited during startup. "
                f"stdout={stdout.strip()} stderr={stderr.strip()}"
            )

    def loadGDB(self) -> None:
        """Start GDB/MI, load vmlinux helpers, and connect to kdump-gdbserver."""
        if self._gdb is not None:
            return

        command = [self.gdb_path, "--interpreter=mi2", str(self.vmlinux)]
        self.logger.info("Starting gdb: %s", " ".join(command))
        self._gdb = GdbController(command=command)
        self._write("set pagination off")
        if self.gdb_script.exists():
            self._write(f"source {self.gdb_script}")
        else:
            self.logger.warning("Linux gdb helper script not found: %s", self.gdb_script)
        self._write(f"target remote {self.host}:{self.port}", strict=True)

    def execute(self, command: str) -> dict[str, Any]:
        """Execute one GDB command and return a stable tool-friendly payload."""
        if self._gdb is None:
            raise RuntimeError("GDB is not loaded. Call loadGDB() first.")
        try:
            response = self._gdb.write(command, timeout_sec=self.timeout)
        except Exception as exc:
            return {"result": "error", "output": [str(exc)]}

        output: list[str] = []
        for item in response:
            payload = item.get("payload")
            if isinstance(payload, str) and payload.strip():
                output.append(payload.strip())
            elif isinstance(payload, dict):
                for value in payload.values():
                    if isinstance(value, str) and value.strip():
                        output.append(value.strip())
        has_error = any(
            item.get("type") == "result" and item.get("message") == "error" for item in response
        )
        return {"result": "error" if has_error else "success", "output": output}

    def getCrashReport(self) -> tuple[bool, str]:
        """Collect the core debug facts used by the agents as a crash report."""
        commands = [
            "bt",
            "info registers",
            "x/i $pc",
            "lx-dmesg",
        ]
        sections: list[str] = []
        failures: list[str] = []

        for command in commands:
            result = self.execute(command)
            body = "\n".join(str(item) for item in result.get("output", []) if str(item).strip())
            if result.get("result") == "success" and body:
                sections.append(f"## {command}\n{body}")
            elif body:
                failures.append(f"{command}: {body}")

        if sections:
            return True, "\n\n".join(sections)
        return False, "\n".join(failures) or "No crash report output was produced."

    def stop(self) -> None:
        """Stop GDB and kdump-gdbserver. Safe to call multiple times."""
        if self._gdb is not None:
            try:
                self._gdb.exit()
            except Exception:
                pass
            self._gdb = None

        if self._server is not None:
            if self._server.poll() is None:
                self._server.terminate()
                try:
                    self._server.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._server.kill()
            self._server = None

    def _write(self, command: str, *, strict: bool = False) -> list[dict[str, Any]]:
        if self._gdb is None:
            raise RuntimeError("GDB controller is not available.")
        response = self._gdb.write(command, timeout_sec=self.timeout)
        if strict and any(
            item.get("type") == "result" and item.get("message") == "error" for item in response
        ):
            output: list[str] = []
            for item in response:
                payload = item.get("payload")
                if isinstance(payload, str) and payload.strip():
                    output.append(payload.strip())
                elif isinstance(payload, dict):
                    for value in payload.values():
                        if isinstance(value, str) and value.strip():
                            output.append(value.strip())
            raise RuntimeError(f"GDB command failed: {command}: {output}")
        return response
