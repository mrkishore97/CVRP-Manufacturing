"""V1.1-M5: the solver worker process never outlives the backend.

Solves run in a separate worker process (OR-Tools holds Python's interpreter lock for
the whole search). A backend that is killed cannot shut the worker down, so the worker
watches its parent and exits with it. Found in the M5 manual run.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CHILD = """
import os, sys
from backend.app.application.planning_service import solver_process_pool
print(solver_process_pool().submit(os.getpid).result(), flush=True)
os._exit(0)  # die like a killed backend: no shutdown of the pool
"""


def _alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        synchronize, wait_timeout = 0x00100000, 0x00000102
        kernel32 = getattr(ctypes, "windll").kernel32  # noqa: B009
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return False
        try:
            return bool(kernel32.WaitForSingleObject(handle, 0) == wait_timeout)
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_the_solver_worker_exits_when_the_backend_is_killed() -> None:
    result = subprocess.run(
        [sys.executable, "-c", CHILD],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    worker_pid = int(result.stdout.strip().splitlines()[-1])

    deadline = time.monotonic() + 15
    while _alive(worker_pid) and time.monotonic() < deadline:
        time.sleep(0.2)

    assert not _alive(worker_pid), "the solver worker outlived the backend"
