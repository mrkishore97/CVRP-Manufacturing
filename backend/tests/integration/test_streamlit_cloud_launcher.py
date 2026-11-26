"""The Streamlit Community Cloud launcher (root ``streamlit_app.py``) and the local startup.

Cloud runs one ``streamlit run`` process, so the launcher starts the FastAPI backend in
it on a loopback port and then shows the unchanged frontend, which calls the backend over
HTTP. These tests start real servers on free ports with scratch databases, in a scratch
folder without ``.env``.

- The API starts once: on repeated calls, from concurrent sessions, and even when the
  cache that normally serializes the start is bypassed.
- After a cache clear, the running API is reused only once it answers as this app's own
  API. Another program on the port is refused, even one that imitates the API.
- The entry file solves the sample over HTTP, with the solver in its worker process,
  started with ``spawn`` from the multithreaded app. The worker imports the entry file
  again, which has no side effects.
- Imports work where the project is not installed, through Streamlit's own path setup.
- The backend runs as its own process with Streamlit blocked, and ``run_app.ps1`` still
  starts the two processes that the frontend expects.
"""

from __future__ import annotations

import json
import os
import runpy
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
import streamlit as st
import uvicorn
from fastapi import FastAPI
from streamlit.testing.v1 import AppTest

import streamlit_app as launcher
from backend import __version__
from backend.app.application import planning_service
from backend.app.config import get_settings
from frontend.api_client import BackendClient
from frontend.state.results import STATUS_TEXT
from frontend.tests.form_driver import click, go, ok

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENTRY = PROJECT_ROOT / "streamlit_app.py"
SESSIONS = 8


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _api_threads() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name == launcher.API_THREAD_NAME]


def _health(environment: str = "test") -> dict[str, str]:
    return {
        "status": "ok",
        "service": launcher.API_SERVICE,
        "version": __version__,
        "environment": environment,
    }


@pytest.fixture
def servers(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[uvicorn.Server]]:
    """Every API server run during the test; all are stopped afterwards."""
    started: list[uvicorn.Server] = []
    real_run = uvicorn.Server.run

    def run(self: uvicorn.Server, sockets: list[socket.socket] | None = None) -> None:
        started.append(self)
        real_run(self, sockets=sockets)

    monkeypatch.setattr(uvicorn.Server, "run", run)
    yield started
    for server in started:
        server.should_exit = True
    for thread in _api_threads():
        thread.join(timeout=15)
    assert not _api_threads(), "an API thread outlived its test"


@pytest.fixture
def port(
    servers: list[uvicorn.Server], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[int]:
    """A free port, a scratch database, and no ``.env``: never the real key or data."""
    free = _free_port()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BACKEND_PORT", str(free))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "launcher.db"))
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    # Set so that the launcher's own setting is undone afterwards.
    monkeypatch.setenv("BACKEND_API_URL", "http://unused.invalid")
    get_settings.cache_clear()
    st.cache_resource.clear()
    yield free
    st.cache_resource.clear()
    get_settings.cache_clear()


def test_the_api_starts_once_on_a_private_loopback_port(
    port: int, servers: list[uvicorn.Server]
) -> None:
    url = launcher.planning_api_url()
    assert url == f"http://127.0.0.1:{port}"
    assert launcher.planning_api_url() == url

    assert len(servers) == 1
    assert len(_api_threads()) == 1
    listening = [sock.getsockname() for server in servers[0].servers for sock in server.sockets]
    assert listening == [("127.0.0.1", port)]
    assert httpx.get(f"{url}/api/v1/health", trust_env=False).json() == _health()


def test_concurrent_sessions_start_one_api(port: int, servers: list[uvicorn.Server]) -> None:
    barrier = threading.Barrier(SESSIONS)

    def first_page_load(_: int) -> str:
        barrier.wait()
        return launcher.planning_api_url()

    with ThreadPoolExecutor(SESSIONS) as sessions:
        urls = set(sessions.map(first_page_load, range(SESSIONS)))

    assert urls == {f"http://127.0.0.1:{port}"}
    assert len(servers) == 1
    assert len(_api_threads()) == 1


def test_racing_starts_run_one_api_even_without_the_cache(
    port: int, servers: list[uvicorn.Server]
) -> None:
    # A start racing a "Clear cache" is not serialized by the cache. The socket, bound
    # before the API starts, still lets only one start win; the others reuse it.
    uncached = getattr(launcher.planning_api_url, "__wrapped__")  # noqa: B009
    barrier = threading.Barrier(SESSIONS)

    def start(_: int) -> str:
        barrier.wait()
        return str(uncached())

    with ThreadPoolExecutor(SESSIONS) as sessions:
        urls = set(sessions.map(start, range(SESSIONS)))

    assert urls == {f"http://127.0.0.1:{port}"}
    assert len(servers) == 1
    assert len(_api_threads()) == 1


@pytest.mark.parametrize("changed", ["version", "environment"])
def test_after_a_cache_clear_only_this_apps_own_api_is_reused(
    changed: str, port: int, servers: list[uvicorn.Server], monkeypatch: pytest.MonkeyPatch
) -> None:
    url = launcher.planning_api_url()
    st.cache_resource.clear()
    assert launcher.planning_api_url() == url
    assert len(servers) == 1

    # The API on the port no longer matches what this app expects.
    st.cache_resource.clear()
    if changed == "version":
        monkeypatch.setattr(launcher, "__version__", "0.0.0")
    else:
        monkeypatch.setenv("APP_ENV", "production")
        get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="is not this app's planning API"):
        launcher.planning_api_url()
    assert len(servers) == 1


def test_another_program_on_the_port_is_refused_even_when_it_imitates_the_api(
    port: int, servers: list[uvicorn.Server]
) -> None:
    body = json.dumps(_health()).encode()

    class Imitation(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    class ExclusiveServer(ThreadingHTTPServer):
        allow_reuse_address = False

    imitation = ExclusiveServer(("127.0.0.1", port), Imitation)
    threading.Thread(target=imitation.serve_forever, daemon=True).start()
    try:
        answer = httpx.get(f"http://127.0.0.1:{port}/api/v1/health", trust_env=False).json()
        assert answer == _health()
        with pytest.raises(RuntimeError, match=f"Port {port} .* in use by another program"):
            launcher.planning_api_url()
    finally:
        imitation.shutdown()
        imitation.server_close()
    assert servers == []
    assert not _api_threads()


def test_the_entry_solves_the_sample_over_http_with_the_solver_worker(
    port: int, servers: list[uvicorn.Server]
) -> None:
    # The worker must start from this app, so that it imports the entry file again.
    planning_service._discard_process_pool()
    try:
        app = AppTest.from_file(str(ENTRY), default_timeout=120)
        app.run()
        ok(app)
        assert os.environ["BACKEND_API_URL"] == f"http://127.0.0.1:{port}"
        go(app, "optimize")
        click(app, "Solve route plan")
        assert app.session_state["current_page"] == "results"
        assert STATUS_TEXT["FEASIBLE"][1] in [success.value for success in app.success]

        pool = planning_service._POOL
        assert pool is not None and pool._mp_context is not None
        # spawn: the worker never inherits the app's threads (Linux defaults to fork).
        assert pool._mp_context.get_start_method() == "spawn"
        workers = list(pool._processes)
        assert workers and os.getpid() not in workers
    finally:
        planning_service._discard_process_pool()
    assert len(servers) == 1


def test_the_solver_worker_can_import_the_entry_without_side_effects(
    port: int, servers: list[uvicorn.Server]
) -> None:
    namespace = runpy.run_path(str(ENTRY), run_name="__mp_main__")
    assert callable(namespace["planning_api_url"])
    assert servers == []
    assert not _api_threads()
    assert os.environ["BACKEND_API_URL"] == "http://unused.invalid"


CLEAN_IMPORT = """
import sys

# Forget the development install: Streamlit Community Cloud does not install the project.
sys.meta_path[:] = [f for f in sys.meta_path if "__editable__" not in getattr(f, "__module__", "")]
sys.path_hooks[:] = [
    h for h in sys.path_hooks if "__editable__" not in getattr(h, "__module__", "")
]
sys.path_importer_cache.clear()
try:
    import backend
except ImportError:
    pass
else:
    raise SystemExit("backend imports without the entry folder: the check proves nothing")

from streamlit.web import bootstrap

bootstrap._fix_sys_path(sys.argv[1])  # what `streamlit run` does with the entry file
import streamlit_app, backend, frontend

print(streamlit_app.__file__, backend.__file__, frontend.__file__, sep="\\n")
"""


def test_imports_work_where_the_project_is_not_installed(tmp_path: Path) -> None:
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, "-c", CLEAN_IMPORT, str(ENTRY)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    files = [Path(line) for line in result.stdout.strip().splitlines()[-3:]]
    assert files == [
        ENTRY,
        PROJECT_ROOT / "backend" / "__init__.py",
        PROJECT_ROOT / "frontend" / "__init__.py",
    ]


STANDALONE_BACKEND = """
import sys

sys.modules["streamlit"] = None  # any import of Streamlit now fails
import uvicorn

uvicorn.run("backend.app.api.main:app", host="127.0.0.1", port=int(sys.argv[1]))
"""


def test_the_backend_runs_as_its_own_process_without_streamlit(tmp_path: Path) -> None:
    free = _free_port()
    environment = {
        **{key: value for key, value in os.environ.items() if key != "GOOGLE_MAPS_API_KEY"},
        "DATABASE_PATH": str(tmp_path / "standalone.db"),
        "APP_ENV": "test",
    }
    backend = subprocess.Popen(
        [sys.executable, "-c", STANDALONE_BACKEND, str(free)],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 60
        answer: dict[str, str] | None = None
        while answer is None and backend.poll() is None and time.monotonic() < deadline:
            try:
                answer = httpx.get(
                    f"http://127.0.0.1:{free}/api/v1/health", timeout=2.0, trust_env=False
                ).json()
            except httpx.TransportError:
                time.sleep(0.2)
    finally:
        backend.terminate()
        _, errors = backend.communicate(timeout=15)
    assert answer == _health(), errors[-2000:]


def test_run_app_still_starts_the_backend_and_the_frontend_as_two_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = (PROJECT_ROOT / "run_app.ps1").read_text(encoding="utf-8")
    assert '"backend.app.api.main:app"' in script
    assert '"127.0.0.1"' in script and '"8000"' in script
    assert "streamlit run frontend/streamlit_app.py" in script

    from backend.app.api.main import app

    assert isinstance(app, FastAPI)
    frontend_entry = (PROJECT_ROOT / "frontend" / "streamlit_app.py").read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":\n    render_app()' in frontend_entry
    monkeypatch.delenv("BACKEND_API_URL", raising=False)
    assert BackendClient.from_environment()._base_url == "http://127.0.0.1:8000"
