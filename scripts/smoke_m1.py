"""Start both M1 services and verify their health endpoints."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_URL = "http://127.0.0.1:8765/api/v1/health"
STREAMLIT_HEALTH_URL = "http://127.0.0.1:8766/_stcore/health"


def wait_for_url(url: str, timeout_seconds: float) -> tuple[int, bytes]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                return response.status, response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def start_process(arguments: list[str], environment: dict[str, str]) -> subprocess.Popen[str]:
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.Popen(
        arguments,
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=creation_flags,
    )


def stop_process(process: subprocess.Popen[str]) -> str:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    return process.stdout.read() if process.stdout else ""


def main() -> int:
    environment = os.environ.copy()
    environment.pop("GOOGLE_MAPS_API_KEY", None)
    environment["BACKEND_API_URL"] = "http://127.0.0.1:8765"

    backend = start_process(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
        ],
        environment,
    )
    frontend: subprocess.Popen[str] | None = None
    backend_output = ""
    frontend_output = ""
    try:
        status, body = wait_for_url(BACKEND_URL, 15)
        payload: dict[str, Any] = json.loads(body)
        if status != 200 or payload.get("status") != "ok":
            raise RuntimeError(f"Unexpected backend health response: {status} {payload}")

        frontend = start_process(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "frontend/streamlit_app.py",
                "--server.headless",
                "true",
                "--server.address",
                "127.0.0.1",
                "--server.port",
                "8766",
            ],
            environment,
        )
        frontend_status, frontend_body = wait_for_url(STREAMLIT_HEALTH_URL, 20)
        if frontend_status != 200 or frontend_body.strip() != b"ok":
            raise RuntimeError(
                f"Unexpected Streamlit health response: {frontend_status} {frontend_body!r}"
            )
    finally:
        if frontend is not None:
            frontend_output = stop_process(frontend)
        backend_output = stop_process(backend)

    if backend.returncode not in {0, -15, 1}:
        print(backend_output)
        raise RuntimeError(f"Backend exited unexpectedly with {backend.returncode}")
    if frontend is not None and frontend.returncode not in {0, -15, 1}:
        print(frontend_output)
        raise RuntimeError(f"Frontend exited unexpectedly with {frontend.returncode}")

    print("M1 SMOKE PASSED: backend and Streamlit started without a Google API key")
    print(f"Backend health: {BACKEND_URL}")
    print(f"Streamlit health: {STREAMLIT_HEALTH_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
