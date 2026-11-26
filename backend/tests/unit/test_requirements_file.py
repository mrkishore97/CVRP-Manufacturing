"""``requirements.txt`` mirrors the runtime dependencies in ``pyproject.toml``.

Streamlit Community Cloud installs from ``requirements.txt``; ``pyproject.toml`` stays the
source of truth. The file lists exactly the same pinned runtime dependencies: nothing
missing, nothing extra (no development tools), no other version, and not the project
itself, which the root ``streamlit_app.py`` makes importable without installing it.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PINNED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==[0-9][^\s=;]*$")


def _pyproject() -> dict[str, object]:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def _runtime_dependencies() -> list[str]:
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    return [str(dependency) for dependency in project["dependencies"]]


def _requirement_lines(text: str) -> list[str]:
    lines = (line.split("#", 1)[0].strip() for line in text.splitlines())
    return [line for line in lines if line]


def _differences(source: list[str], copy: list[str]) -> dict[str, list[str]]:
    return {
        "missing from requirements.txt": sorted(set(source) - set(copy)),
        "not in pyproject.toml": sorted(set(copy) - set(source)),
    }


def test_requirements_list_exactly_the_runtime_dependencies_of_pyproject() -> None:
    copy = _requirement_lines((PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8"))
    source = _runtime_dependencies()

    assert len(copy) == len(set(copy)), "requirements.txt lists a package twice"
    assert _differences(source, copy) == {
        "missing from requirements.txt": [],
        "not in pyproject.toml": [],
    }, "Copy the dependencies from pyproject.toml [project] into requirements.txt."


def test_requirements_pin_packages_only_and_never_install_the_project() -> None:
    copy = _requirement_lines((PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8"))

    assert copy, "requirements.txt is empty"
    assert [line for line in copy if not PINNED.match(line)] == []
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    development = {line.split("==")[0] for line in project["optional-dependencies"]["dev"]}
    assert {line.split("==")[0] for line in copy} & development == set()


def test_the_comparison_reports_a_changed_version_and_a_missing_package() -> None:
    source = ["fastapi==0.115.6", "uvicorn==0.34.0"]
    copy = _requirement_lines("# a comment\nfastapi==0.115.7  # newer\n\n")

    assert _differences(source, copy) == {
        "missing from requirements.txt": ["fastapi==0.115.6", "uvicorn==0.34.0"],
        "not in pyproject.toml": ["fastapi==0.115.7"],
    }
    assert not PINNED.match("-e .")
    assert not PINNED.match(".")
    assert not PINNED.match("fastapi>=0.115")
