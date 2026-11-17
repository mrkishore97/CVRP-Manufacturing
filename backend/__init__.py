"""Backend package for the Manufacturing PO Route Optimizer."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

DISTRIBUTION_NAME = "manufacturing-po-route-optimizer"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read_version() -> str:
    """Return the release version from the single source of truth, the root ``VERSION`` file.

    In a source checkout the file is read directly, so a version bump never depends on
    reinstalling the package. An installed copy has no ``VERSION`` file beside it and falls
    back to the distribution metadata, which ``pyproject.toml`` derives from the same file.
    """
    version_file = _PROJECT_ROOT / "VERSION"
    if version_file.is_file() and (_PROJECT_ROOT / "pyproject.toml").is_file():
        version = version_file.read_text(encoding="utf-8").strip()
        if version:
            return version
    try:
        return metadata.version(DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        return "0+unknown"


__version__ = _read_version()
