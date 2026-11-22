"""Validate a release against the version in ``VERSION`` (replaces ``validate_m9_release.py``).

Nothing here is hard-coded to one release: the version, its checklist, its plan, and its
traceability matrix are all found from ``VERSION``. For version ``X.Y.Z`` the script checks:

- ``VERSION`` is ``X.Y.Z``; ``pyproject.toml`` reads it; the backend, the health endpoint,
  and the OpenAPI document report it.
- ``CHANGELOG.md`` has a section for ``X.Y.Z``.
- ``docs/version_X_Y_release_checklist.md`` names ``vX.Y.Z`` and has one row per acceptance
  criterion of ``project_plan_vX.Y.md`` (§16), none marked as failing.
- ``docs/requirements_traceability_vX_Y.md`` covers every criterion, and every test it
  cites exists.
- The README links every operating guide; the Google setup guide keeps its official links.
- No Google key appears in tracked files, logs, exports, or the database; ``.gitignore``
  keeps secrets and local data out of source control.

It never reads ``.env``, never calls Google, and starts the backend on a temporary
database. Run it from the project root:

    & .\\.venv\\Scripts\\python.exe scripts/validate_release.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

VERSION_PATTERN = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
REQUIRED_README_LINKS = (
    "docs/user_guide.md",
    "docs/addresses_and_costs.md",
    "docs/objectives_and_priorities.md",
    "docs/deployment.md",
    "docs/google_api_setup.md",
    "docs/backup_restore.md",
    "docs/troubleshooting.md",
    "CHANGELOG.md",
)
REQUIRED_GOOGLE_LINKS = (
    "https://developers.google.com/maps/api-security-best-practices",
    "https://developers.google.com/maps/documentation/routes",
    "https://developers.google.com/maps/documentation/routes/compute_route_matrix",
    "https://developers.google.com/maps/documentation/geocoding/guides-v3/get-api-key",
    "https://developers.google.com/maps/documentation/geocoding/policies",
    "https://developers.google.com/maps/documentation/routes/policies",
)
REQUIRED_GITIGNORE = (".env", "*.db", "logs/", "exports/", ".streamlit/secrets.toml")
SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(
        r"^GOOGLE_MAPS_API_KEY[ \t]*=[ \t]*"
        r"(?!(?:replace|backend_only_secret|$))[A-Za-z0-9_\-]{20,}",
        re.MULTILINE,
    ),
)
TEXT_SUFFIXES = {".cfg", ".csv", ".example", ".ini", ".json", ".md", ".ps1", ".py", ".toml"}
TEXT_SUFFIXES |= {".txt", ".yaml", ".yml"}
RUNTIME_DIRECTORIES = ("logs", "exports")
FAILING_STATUSES = re.compile(r"\|\s*(fail|failed|open|blocked)\s*\|", re.IGNORECASE)
TEST_REFERENCE = re.compile(r"`(test_[a-z0-9_]+)`")


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def _exists(relative_path: str) -> bool:
    return (PROJECT_ROOT / relative_path).is_file()


def check_version(failures: list[str]) -> re.Match[str] | None:
    version = _read("VERSION").strip() if _exists("VERSION") else ""
    match = VERSION_PATTERN.match(version)
    if match is None:
        failures.append(f"VERSION must look like 1.2.3, got {version!r}")
        return None
    pyproject = _read("pyproject.toml")
    if 'dynamic = ["version"]' not in pyproject or 'version = { file = "VERSION" }' not in (
        pyproject
    ):
        failures.append("pyproject.toml must read its version from VERSION")

    import backend

    if backend.__version__ != version:
        failures.append(f"backend reports {backend.__version__!r}, VERSION says {version!r}")
    for label, reported in _served_versions().items():
        if reported != version:
            failures.append(f"{label} reports {reported!r}, VERSION says {version!r}")
    return match


def _served_versions() -> dict[str, str]:
    """The version the running backend reports, on a temporary database, without ``.env``."""
    from fastapi.testclient import TestClient

    from backend.app.api.main import create_app
    from backend.app.config import Settings

    with tempfile.TemporaryDirectory(prefix="release-check-") as folder:
        settings = Settings(  # type: ignore[call-arg]
            _env_file=None,
            app_environment="test",
            database_path=Path(folder) / "release.db",
            google_maps_api_key=None,
            solver_in_subprocess=False,
        )
        with TestClient(create_app(settings)) as client:
            health = client.get("/api/v1/health").json()
            openapi = client.get("/openapi.json").json()
    return {
        "GET /api/v1/health": str(health.get("version")),
        "OpenAPI": str(openapi.get("info", {}).get("version")),
    }


def acceptance_criteria(plan_text: str) -> list[int]:
    """The numbers of the acceptance criteria in a plan's "Acceptance criteria" section."""
    section = re.search(
        r"^## \d+\. Acceptance criteria\n(?P<body>.*?)(?=^## )", plan_text, re.M | re.S
    )
    if section is None:
        return []
    return [int(number) for number in re.findall(r"^(\d+)\. ", section["body"], re.M)]


def check_release_documents(version: re.Match[str], failures: list[str]) -> None:
    release = version.group(0)
    major_minor = f"{version['major']}_{version['minor']}"
    changelog = _read("CHANGELOG.md") if _exists("CHANGELOG.md") else ""
    if not re.search(rf"^## \[?{re.escape(release)}\]?", changelog, re.M):
        failures.append(f"CHANGELOG.md has no section for {release}")

    plan_path = f"project_plan_v{version['major']}.{version['minor']}.md"
    if not _exists(plan_path):
        failures.append(f"Missing the release plan {plan_path}")
        return
    criteria = acceptance_criteria(_read(plan_path))
    if not criteria or criteria != list(range(1, len(criteria) + 1)):
        failures.append(f"{plan_path} has no numbered acceptance criteria in §16")
        return

    checklist_path = f"docs/version_{major_minor}_release_checklist.md"
    if not _exists(checklist_path):
        failures.append(f"Missing the release checklist {checklist_path}")
    else:
        checklist = _read(checklist_path)
        if f"v{release}" not in checklist:
            failures.append(f"{checklist_path} does not name v{release}")
        for number in criteria:
            if not re.search(rf"^\| {number} \|", checklist, re.M):
                failures.append(f"{checklist_path} is missing criterion {number}")
        for line in checklist.splitlines():
            if line.startswith("| ") and FAILING_STATUSES.search(line):
                failures.append(f"{checklist_path} has a failing row: {line[:80]}")

    trace_path = f"docs/requirements_traceability_v{major_minor}.md"
    if not _exists(trace_path):
        failures.append(f"Missing the traceability matrix {trace_path}")
        return
    trace = _read(trace_path)
    for number in criteria:
        if not re.search(rf"^\| AC-{number:02d} \|", trace, re.M):
            failures.append(f"{trace_path} does not trace criterion {number} (AC-{number:02d})")
    defined = _defined_tests()
    for name in sorted(set(TEST_REFERENCE.findall(trace))):
        if name not in defined:
            failures.append(f"{trace_path} cites {name}, which no test defines")


def _defined_tests() -> set[str]:
    names: set[str] = set()
    for folder in ("backend/tests", "frontend/tests"):
        for path in (PROJECT_ROOT / folder).rglob("test_*.py"):
            names.update(re.findall(r"^def (test_\w+)\(", path.read_text(encoding="utf-8"), re.M))
    return names


def check_guides(failures: list[str]) -> None:
    readme = _read("README.md")
    for link in REQUIRED_README_LINKS:
        if not _exists(link):
            failures.append(f"Missing {link}")
        if link not in readme:
            failures.append(f"README does not link {link}")
    google_setup = _read("docs/google_api_setup.md")
    for link in REQUIRED_GOOGLE_LINKS:
        if link not in google_setup:
            failures.append(f"Google setup guide is missing the official link {link}")


def scanned_files() -> list[Path]:
    """Tracked and not-ignored files, plus the runtime folders source control ignores."""
    try:
        listed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8")
        files = [PROJECT_ROOT / name for name in listed.split("\0") if name]
    except (OSError, subprocess.CalledProcessError):
        files = [
            path
            for path in PROJECT_ROOT.rglob("*")
            if ".venv" not in path.parts and ".git" not in path.parts
        ]
    files = [path for path in files if path.suffix.lower() in TEXT_SUFFIXES]
    for folder in RUNTIME_DIRECTORIES:
        files.extend(path for path in (PROJECT_ROOT / folder).rglob("*") if path.is_file())
    files.extend((PROJECT_ROOT / "data").glob("*.db"))
    return [path for path in files if path.is_file() and path.name != ".env"]


def check_secrets(failures: list[str]) -> int:
    files = scanned_files()
    for path in files:
        text = path.read_bytes().decode("utf-8", errors="ignore")
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            failures.append(f"Possible Google key in {path.relative_to(PROJECT_ROOT)}")
    gitignore = _read(".gitignore")
    for pattern in REQUIRED_GITIGNORE:
        if pattern not in gitignore:
            failures.append(f".gitignore is missing {pattern}")
    return len(files)


def main() -> int:
    failures: list[str] = []
    version = check_version(failures)
    if version is not None:
        check_release_documents(version, failures)
    check_guides(failures)
    scanned = check_secrets(failures)

    if failures:
        for failure in failures:
            print(f"RELEASE VALIDATION FAILED: {failure}")
        return 1
    assert version is not None
    print(f"RELEASE VALIDATION PASSED for v{version.group(0)}")
    print(
        "Version sources agree; changelog, checklist, plan criteria, and traceability match; "
        f"guides are linked; no key found in {scanned} scanned files."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
