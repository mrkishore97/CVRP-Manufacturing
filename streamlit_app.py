"""Single-process launcher for Streamlit Community Cloud: the planning API and the app.

Streamlit Community Cloud runs one ``streamlit run`` process, so this file starts the
FastAPI backend inside it, on a private loopback port, and then shows the unchanged
frontend, which reaches the backend over HTTP through ``BACKEND_API_URL`` as it does
with ``run_app.ps1``. Everything specific to this kind of hosting lives here; the
backend knows nothing about Streamlit.

- **Once per process.** Concurrent first sessions wait on Streamlit's resource cache
  for one start. The listening socket is bound before the API starts, so not even a
  start racing a "Clear cache" can run a second API: only one socket can listen on the
  port.
- **Only our own API is reused.** After a cache clear, the running API is reused only
  when this process started it and its health check names this service, version, and
  environment. Anything else on the port is refused with a clear message.
- **Imports.** Streamlit puts this file's folder, the repository root, first on the
  import path, so ``backend`` and ``frontend`` import without installing the project.
- **Solver worker.** The backend starts its worker with ``spawn``, which imports this
  file again as ``__mp_main__``. Nothing here runs on import.

Run it locally with ``streamlit run streamlit_app.py``. ``run_app.ps1`` still starts
the backend and the frontend as two processes.
"""

from __future__ import annotations

import os
import socket
import threading
import time

import httpx
import streamlit as st
import uvicorn

from backend import __version__
from backend.app.api.main import create_app
from backend.app.config import get_settings
from frontend.streamlit_app import render_app

LOOPBACK = "127.0.0.1"
API_THREAD_NAME = "planning-api"
API_SERVICE = "manufacturing-po-route-optimizer-backend"
START_TIMEOUT_SECONDS = 30.0
RACE_WAIT_SECONDS = 2.0


def _api_thread(wait_seconds: float = 0.0) -> threading.Thread | None:
    """The thread serving the API that this process started, while it runs."""
    deadline = time.monotonic() + wait_seconds
    while True:
        for thread in threading.enumerate():
            if thread.name == API_THREAD_NAME and thread.is_alive():
                return thread
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.05)


def _start_api(port: int) -> threading.Thread | None:
    """Serve the API on the loopback port; ``None`` when something already listens there."""
    server = uvicorn.Server(uvicorn.Config(create_app(), host=LOOPBACK, port=port))
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "posix":
        # As asyncio does on POSIX: allows a restart while old connections close. It
        # never lets two sockets listen on one port.
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind((LOOPBACK, port))
        listener.listen()
    except OSError:
        listener.close()
        return None
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, name=API_THREAD_NAME, daemon=True
    )
    thread.start()
    return thread


def _wait_until_serving(url: str, thread: threading.Thread, environment: str) -> None:
    """Return once the API on ``url`` answers as this app's own API, or raise."""
    expected = {
        "status": "ok",
        "service": API_SERVICE,
        "version": __version__,
        "environment": environment,
    }
    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    while thread.is_alive() and time.monotonic() < deadline:
        try:
            response = httpx.get(f"{url}/api/v1/health", timeout=2.0, trust_env=False)
            answer = response.json() if response.status_code == 200 else None
        except httpx.TransportError:
            time.sleep(0.2)
            continue
        except ValueError:
            answer = None
        if answer == expected:
            return
        raise RuntimeError(
            f"The service on {url} is not this app's planning API {__version__}, "
            "so it is not used. Restart the app."
        )
    if thread.is_alive():
        raise RuntimeError(
            f"The planning API did not answer on {url} within "
            f"{START_TIMEOUT_SECONDS:.0f} s. Restart the app; its log has the details."
        )
    raise RuntimeError("The planning API stopped while starting. The app's log has the reason.")


@st.cache_resource(show_spinner=False)
def planning_api_url() -> str:
    """Start the planning API once per process, or reuse the one this process started."""
    settings = get_settings()
    port = settings.backend_port
    thread = _api_thread() or _start_api(port) or _api_thread(RACE_WAIT_SECONDS)
    if thread is None:
        raise RuntimeError(
            f"Port {port} on {LOOPBACK} is in use by another program, so the planning "
            "API cannot start. Stop that program, or set BACKEND_PORT to a free port."
        )
    url = f"http://{LOOPBACK}:{port}"
    _wait_until_serving(url, thread, settings.app_environment)
    return url


def main() -> None:
    """Show the planning app, with its API running in this process."""
    try:
        url = planning_api_url()
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()
    os.environ["BACKEND_API_URL"] = url
    render_app()


if __name__ == "__main__":
    main()
