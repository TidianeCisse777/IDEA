"""Docker-backed local IDEA workspace for hosts without KVM.

One named container is retained per authenticated user. Python kernels remain
scoped by ``kernel_id`` inside that container, matching the production guest
daemon while using Docker Desktop as the isolation boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import shlex
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable


DEFAULT_IMAGE = os.getenv("DOCKER_SANDBOX_IMAGE", "idea-oi-kernel-local:dev")
CLIENT_PATH = os.getenv("OI_KERNEL_CLIENT_PATH", "/opt/oi_kernel/client.py")
RUNTIME_VENV = "/opt/idea-venv"
RUNTIME_PATH = f"{RUNTIME_VENV}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# Docker-backed sandboxes are created by the sandbox service through the
# Docker socket, so they need the volume name (not the service container's
# /srv/idea_shared_data path) to access administrator-managed data.
SHARED_DATA_DOCKER_VOLUME = os.getenv("SHARED_DATA_DOCKER_VOLUME", "").strip()


class DockerTerminal:
    """Persistent Docker container with IDEA's Jupyter-backed kernel daemon."""

    def __init__(self, session_id: str, image: str | None = None) -> None:
        self.session_id = session_id
        self.image = image or DEFAULT_IMAGE
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
        self.container_name = f"idea-local-{digest}"
        self._stream_lock = threading.Lock()
        self._stream_processes: dict[str, subprocess.Popen] = {}
        self._ensure_container()

    @staticmethod
    def _docker(*args: str, input_bytes: bytes | None = None, timeout: float = 1800) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["docker", *args], input=input_bytes, capture_output=True,
            timeout=timeout, check=False,
        )

    def _ensure_container(self) -> None:
        inspect = self._docker("inspect", "-f", "{{.State.Running}}", self.container_name, timeout=20)
        if inspect.returncode == 0:
            if inspect.stdout.decode().strip() != "true":
                started = self._docker("start", self.container_name, timeout=60)
                if started.returncode:
                    raise RuntimeError(started.stderr.decode(errors="replace"))
            return
        run_args = [
            "run", "-d", "--name", self.container_name,
            "--label", "idea.local-sandbox=true",
            "--label", f"idea.session-sha256={hashlib.sha256(self.session_id.encode()).hexdigest()}",
        ]
        if SHARED_DATA_DOCKER_VOLUME:
            run_args.extend([
                "--mount",
                f"type=volume,source={SHARED_DATA_DOCKER_VOLUME},target=/app/data,readonly",
            ])
        run_args.append(self.image)
        created = self._docker(*run_args, timeout=180)
        if created.returncode:
            raise RuntimeError(
                f"Could not create local IDEA container from {self.image}: "
                f"{created.stderr.decode(errors='replace').strip()}"
            )

    def _exec(self, *args: str, input_bytes: bytes | None = None, timeout: float = 1800) -> subprocess.CompletedProcess:
        self._ensure_container()
        exec_args = [
            "exec",
            *( ["-i"] if input_bytes is not None else []),
            "-e", f"VIRTUAL_ENV={RUNTIME_VENV}",
            "-e", f"PATH={RUNTIME_PATH}",
            self.container_name,
            *args,
        ]
        return self._docker(*exec_args, input_bytes=input_bytes, timeout=timeout)

    def run(self, command: str) -> tuple[bool, str, float]:
        started = time.time()
        result = self._exec("bash", "-lc", command)
        text = result.stdout.decode(errors="replace")
        error = result.stderr.decode(errors="replace")
        output = f"{text}\n{error}".strip() if error else text.strip()
        return result.returncode == 0, output, time.time() - started

    def _write_bytes(self, filepath: str, data: bytes, *, append: bool = False) -> None:
        parent = os.path.dirname(filepath) or "/workspace"
        mode = ">>" if append else ">"
        command = f"mkdir -p -- {shlex.quote(parent)} && cat {mode} {shlex.quote(filepath)}"
        result = self._exec("bash", "-lc", command, input_bytes=data)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace"))

    def write_file(self, filepath: str, content: str, append: bool = False) -> None:
        self._write_bytes(filepath, content.encode("utf-8"), append=append)

    def write_file_bytes(self, filepath: str, source) -> None:
        temporary = f"{filepath}.idea-upload-{uuid.uuid4().hex}"
        with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as spool:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                spool.write(chunk)
            spool.seek(0)
            self._write_bytes(temporary, spool.read())
        result = self._exec("mv", "--", temporary, filepath)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace"))

    def read_file(self, filepath: str) -> bytes:
        result = self._exec("cat", "--", filepath)
        if result.returncode:
            raise FileNotFoundError(filepath)
        return result.stdout

    def file_exists(self, filepath: str) -> bool:
        return self._exec("test", "-f", filepath, timeout=20).returncode == 0

    def _run_client(self, option: str, code: str, kernel_id: str, run_id: str) -> subprocess.CompletedProcess:
        path = f"/tmp/.oi_kernel_code_{uuid.uuid4().hex}.py"
        try:
            self._write_bytes(path, code.encode("utf-8"))
            return self._exec(
                "python3", CLIENT_PATH, option, path,
                "--kernel-id", kernel_id, "--run-id", run_id,
            )
        finally:
            self._exec("rm", "-f", "--", path, timeout=20)

    def run_python(self, code: str, kernel_id: str = "default", run_id: str = "") -> dict:
        result = self._run_client("--run-file", code, kernel_id, run_id)
        text = result.stdout.decode(errors="replace").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            error = result.stderr.decode(errors="replace").strip()
            return {"chunks": [{"type": "console", "format": "error", "content": text or error or "Kernel returned no output"}]}

    def run_python_stream(self, code: str, kernel_id: str = "default", run_id: str = "", cancelled: Callable[[], bool] | None = None):
        path = f"/tmp/.oi_kernel_code_{uuid.uuid4().hex}.py"
        self._write_bytes(path, code.encode("utf-8"))
        process = subprocess.Popen(
            ["docker", "exec", self.container_name, "python3", CLIENT_PATH,
             "--run-stream-file", path, "--kernel-id", kernel_id, "--run-id", run_id],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if run_id:
            with self._stream_lock:
                self._stream_processes[run_id] = process
        try:
            assert process.stdout is not None
            for raw in iter(process.stdout.readline, b""):
                if cancelled is not None and cancelled():
                    self.interrupt_python(kernel_id)
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    item = {"type": "console", "format": "error", "content": raw.decode(errors="replace")}
                if isinstance(item, dict) and item.get("event") == "chunk":
                    item = item.get("chunk")
                elif isinstance(item, dict) and item.get("event") == "error":
                    item = {
                        "type": "console", "format": "error",
                        "content": str(item.get("error") or "Unknown kernel error"),
                    }
                if isinstance(item, dict):
                    yield item
            process.wait()
            if process.returncode:
                error = (process.stderr.read() if process.stderr else b"").decode(errors="replace").strip()
                if error:
                    yield {"type": "console", "format": "error", "content": error}
        finally:
            if run_id:
                with self._stream_lock:
                    self._stream_processes.pop(run_id, None)
            self._exec("rm", "-f", "--", path, timeout=20)

    def _control(self, option: str, kernel_id: str) -> dict:
        result = self._exec("python3", CLIENT_PATH, option, "--kernel-id", kernel_id, timeout=30)
        try:
            return json.loads(result.stdout.decode().strip())
        except json.JSONDecodeError:
            return {}

    def interrupt_python(self, kernel_id: str) -> bool:
        return bool(self._control("--interrupt", kernel_id).get("interrupted"))

    def python_kernel_status(self, kernel_id: str) -> dict | None:
        return self._control("--kernel-status", kernel_id) or None

    def restart_python_kernel(self, kernel_id: str) -> bool:
        return bool(self._control("--restart-kernel", kernel_id).get("restarted"))

    def signal_python_run(self, run_id: str, sig: signal.Signals) -> bool:
        with self._stream_lock:
            process = self._stream_processes.get(run_id)
        if process is None:
            return False
        if sig == signal.SIGINT:
            process.send_signal(signal.SIGINT)
        else:
            process.kill()
        return True

    def recover_sandbox(self, run_id: str = "") -> bool:
        result = self._docker("restart", self.container_name, timeout=90)
        return result.returncode == 0

    def close(self) -> None:
        self._docker("stop", "-t", "10", self.container_name, timeout=30)

    def destroy(self) -> None:
        self._docker("rm", "-f", self.container_name, timeout=30)
