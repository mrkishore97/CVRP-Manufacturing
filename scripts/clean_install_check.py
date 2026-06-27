"""Create a temporary virtual environment and verify the package installs.

This is intentionally separate from the normal test suite because it downloads
or reuses packages and can take longer than unit tests.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], *, cwd: Path) -> None:
    print(f"RUN: {' '.join(command)}")
    subprocess.run(command, cwd=cwd, check=True)


def _python_path(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def main() -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="route-optimizer-clean-install-"))
    try:
        venv_dir = temp_root / ".venv"
        _run([sys.executable, "-m", "venv", str(venv_dir)], cwd=PROJECT_ROOT)
        python = _python_path(venv_dir)
        _run([str(python), "-m", "pip", "install", "--upgrade", "pip"], cwd=PROJECT_ROOT)
        _run([str(python), "-m", "pip", "install", "-e", ".[dev]"], cwd=PROJECT_ROOT)
        _run([str(python), "-m", "pip", "check"], cwd=PROJECT_ROOT)
        _run(
            [
                str(python),
                "-c",
                (
                    "import backend.app.api.main, frontend.api_client; "
                    "print('clean install imports passed')"
                ),
            ],
            cwd=PROJECT_ROOT,
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    print("M9 CLEAN INSTALL CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
