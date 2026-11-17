"""The release version has one source of truth: the root VERSION file (V1.1-M0, finding F15)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import backend

PROJECT_ROOT = Path(__file__).resolve().parents[3]
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[a-z]+\d+)?$")


def _version_file() -> str:
    return (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_version_file_holds_a_release_number() -> None:
    assert VERSION_PATTERN.match(_version_file())


def test_backend_reports_the_version_file() -> None:
    assert backend.__version__ == _version_file()


def test_pyproject_derives_its_version_from_the_version_file() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "version" not in pyproject["project"]
    assert "version" in pyproject["project"]["dynamic"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {"file": "VERSION"}


def test_tzdata_is_an_explicit_runtime_dependency() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    names = {
        re.split(r"[<>=!~\[ ]", dependency, maxsplit=1)[0]
        for dependency in pyproject["project"]["dependencies"]
    }
    assert "tzdata" in names
