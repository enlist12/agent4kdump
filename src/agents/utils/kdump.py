from __future__ import annotations

import os
import signal
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
        self.kdump_args = list(kdump_args or ["-f", "{vmcore}","-p","{port}"])
        self.timeout = timeout
        self._server: subprocess.Popen[str] | None = None
        self._gdb: GdbController | None = None

    def _kdump_env(self) -> dict[str, str]:
        env = dict(os.environ)
        server_path = Path(self.kdump_server).expanduser()
        kdump_root: Path | None = None
        if server_path.name == "kdump-gdbserver":
            candidate = server_path.resolve().parents[1]
            if candidate.name == "kdump_analyze":
                kdump_root = candidate

        if not kdump_root:
            return env

        pykdump = kdump_root / "pykdumpfile"
        pybuilds = sorted(pykdump.glob("build/lib.*"))
        python_paths = [str(path) for path in [pykdump, *pybuilds] if path.exists()]
        lib_paths = [
            kdump_root / "libkdumpfile/src/addrxlat/.libs",
            kdump_root / "libkdumpfile/src/kdumpfile/.libs",
        ]
        if python_paths:
            env["PYTHONPATH"] = ":".join([*python_paths, env.get("PYTHONPATH", "")]).rstrip(":")
        existing_libs = [str(path) for path in lib_paths if path.exists()]
        if existing_libs:
            env["LD_LIBRARY_PATH"] = ":".join(
                [*existing_libs, env.get("LD_LIBRARY_PATH", "")]
            ).rstrip(":")
            env["PATH"] = ":".join([*existing_libs, env.get("PATH", "")]).rstrip(":")
        return env

    @staticmethod
    def _free_port(port: int) -> None:
        """Kill any process holding *port* by scanning /proc."""
        import re
        for pid_dir in Path("/proc").iterdir():
            if not pid_dir.name.isdigit():
                continue
            try:
                for entry in (pid_dir / "fd").iterdir():
                    link = os.readlink(str(entry))
                    m = re.search(r"socket:\[(\d+)\]", link)
                    if not m:
                        continue
                    inode = m.group(1)
                    with open(f"/proc/net/tcp") as f:
                        for line in f:
                            parts = line.split()
                            if len(parts) < 10:
                                continue
                            if parts[9] == inode:
                                local = parts[1]
                                port_hex = local.split(":")[1]
                                if int(port_hex, 16) == port:
                                    os.kill(int(pid_dir.name), signal.SIGKILL)
                                    return
            except (OSError, FileNotFoundError):
                continue

    def loadKdump(self) -> None:
        """Start kdump-gdbserver if it is not already running."""
        if self._server and self._server.poll() is None:
            return

        self._free_port(self.port)
        time.sleep(0.1)

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
            env=self._kdump_env(),
            start_new_session=True,
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
            gdb_py_dir = self.gdb_script.parent
            self._write(f'python import sys; sys.path.insert(0, "{gdb_py_dir}")')
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
        """Stop GDB and kdump-gdbserver gracefully. Safe to call multiple times."""
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
                    try:
                        os.killpg(self._server.pid, signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        self._server.kill()
            self._server = None

    def force_stop(self) -> None:
        """Kill GDB and kdump-gdbserver immediately (SIGKILL), then wait for port release."""
        if self._gdb is not None:
            try:
                self._gdb.exit()
            except Exception:
                pass
            self._gdb = None

        if self._server is not None and self._server.poll() is None:
            # Kill the entire process group to ensure no orphans keep the port
            try:
                os.killpg(self._server.pid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                self._server.kill()
            try:
                self._server.wait(timeout=2)
            except Exception:
                pass
            self._server = None
            time.sleep(0.3)

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
