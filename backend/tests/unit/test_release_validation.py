"""V1.1-M7: the release script follows ``VERSION`` and catches what it is meant to catch.

It replaces ``validate_m9_release.py``, which hard-coded 1.0.0 (finding F15). Each check
is shown to fail on a broken input, so a passing run means something.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def release() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "validate_release", PROJECT_ROOT / "scripts" / "validate_release.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_release"] = module
    spec.loader.exec_module(module)
    return module


def _with_file(monkeypatch: pytest.MonkeyPatch, release: ModuleType, name: str, text: str) -> None:
    original = release._read
    monkeypatch.setattr(release, "_read", lambda path: text if path == name else original(path))


def test_the_plan_has_28_acceptance_criteria(release: ModuleType) -> None:
    plan = (PROJECT_ROOT / "project_plan_v1.1.md").read_text(encoding="utf-8")
    assert release.acceptance_criteria(plan) == list(range(1, 29))


def test_this_checkout_passes(release: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    assert release.main() == 0
    assert "RELEASE VALIDATION PASSED for v" in capsys.readouterr().out


def test_a_version_the_backend_does_not_report_fails(
    release: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_file(monkeypatch, release, "VERSION", "9.9.9\n")
    failures: list[str] = []
    release.check_version(failures)
    assert any("backend reports" in failure for failure in failures)
    assert any("GET /api/v1/health reports" in failure for failure in failures)


def test_a_malformed_version_fails(release: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    _with_file(monkeypatch, release, "VERSION", "1.1\n")
    failures: list[str] = []
    assert release.check_version(failures) is None
    assert failures == ["VERSION must look like 1.2.3, got '1.1'"]


def test_a_cited_test_that_does_not_exist_and_a_missing_criterion_fail(
    release: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = "docs/requirements_traceability_v1_1.md"
    text = (PROJECT_ROOT / path).read_text(encoding="utf-8")
    broken = text.replace("| AC-28 |", "| AC-99 |") + "\nSee `test_that_was_never_written`.\n"
    _with_file(monkeypatch, release, path, broken)
    version = release.VERSION_PATTERN.match("1.1.0")
    failures: list[str] = []
    release.check_release_documents(version, failures)
    assert f"{path} does not trace criterion 28 (AC-28)" in failures
    assert f"{path} cites test_that_was_never_written, which no test defines" in failures


def test_a_failing_checklist_row_and_a_missing_changelog_section_fail(
    release: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    checklist = "docs/version_1_1_release_checklist.md"
    text = (PROJECT_ROOT / checklist).read_text(encoding="utf-8")
    _with_file(
        monkeypatch, release, checklist, text.replace("| Pass | AC-05 |", "| Fail | AC-05 |")
    )
    version = release.VERSION_PATTERN.match("1.2.0")
    failures: list[str] = []
    release.check_release_documents(version, failures)
    assert "CHANGELOG.md has no section for 1.2.0" in failures
    assert "Missing the release plan project_plan_v1.2.md" in failures

    failures = []
    release.check_release_documents(release.VERSION_PATTERN.match("1.1.0"), failures)
    assert any(failure.startswith(f"{checklist} has a failing row: | 5 |") for failure in failures)


def test_a_key_shaped_value_is_found(release: ModuleType, tmp_path: Path) -> None:
    leaked = tmp_path / "notes.md"
    leaked.write_text("key: AIza" + "x" * 35 + "\n", encoding="utf-8")
    text = leaked.read_text(encoding="utf-8")
    assert any(pattern.search(text) for pattern in release.SECRET_PATTERNS)
    example = "GOOGLE_MAPS_API_KEY=replace_with_backend_only_secret\n"
    assert not any(pattern.search(example) for pattern in release.SECRET_PATTERNS)
