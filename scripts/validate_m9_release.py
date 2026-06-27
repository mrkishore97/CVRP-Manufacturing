"""Validate Version 1 release documentation and secret-safety invariants."""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = PROJECT_ROOT / "docs"

REQUIRED_FILES = (
    "README.md",
    "VERSION",
    "docs/deployment.md",
    "docs/google_api_setup.md",
    "docs/backup_restore.md",
    "docs/troubleshooting.md",
    "docs/version_1_release_checklist.md",
    "build_log.md",
    "project_plan.md",
)

REQUIRED_README_LINKS = (
    "docs/deployment.md",
    "docs/google_api_setup.md",
    "docs/backup_restore.md",
    "docs/troubleshooting.md",
    "docs/version_1_release_checklist.md",
)

REQUIRED_GOOGLE_LINKS = (
    "https://developers.google.com/maps/api-security-best-practices",
    "https://developers.google.com/maps/documentation/routes",
    "https://developers.google.com/maps/documentation/routes/compute_route_matrix",
    "https://developers.google.com/maps/documentation/geocoding/guides-v3/get-api-key",
)

SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(
        r"^GOOGLE_MAPS_API_KEY[ \t]*=[ \t]*"
        r"(?!(?:replace|backend_only_secret|$))[A-Za-z0-9_\-]{20,}",
        re.MULTILINE,
    ),
)


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def main() -> int:
    failures: list[str] = []

    for relative_path in REQUIRED_FILES:
        if not (PROJECT_ROOT / relative_path).exists():
            failures.append(f"Missing required release file: {relative_path}")

    version = _read("VERSION").strip() if (PROJECT_ROOT / "VERSION").exists() else ""
    if version != "1.0.0":
        failures.append(f"VERSION must be 1.0.0, got {version!r}")
    pyproject = _read("pyproject.toml")
    if 'version = "1.0.0"' not in pyproject:
        failures.append("pyproject.toml project version must be 1.0.0")

    readme = _read("README.md")
    for required_link in REQUIRED_README_LINKS:
        if required_link not in readme:
            failures.append(f"README does not link {required_link}")

    google_setup = _read("docs/google_api_setup.md")
    for required_link in REQUIRED_GOOGLE_LINKS:
        if required_link not in google_setup:
            failures.append(f"Google setup guide missing official link: {required_link}")

    checklist = _read("docs/version_1_release_checklist.md")
    for criterion_number in range(1, 21):
        if f"| {criterion_number} |" not in checklist:
            failures.append(f"Release checklist missing criterion {criterion_number}")

    scanned_files = [
        path
        for path in PROJECT_ROOT.rglob("*")
        if path.is_file()
        and ".venv" not in path.parts
        and "__pycache__" not in path.parts
        and path.suffix.lower()
        in {
            ".env",
            ".example",
            ".json",
            ".md",
            ".ps1",
            ".py",
            ".toml",
            ".txt",
        }
    ]
    for path in scanned_files:
        if path.name == ".env":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                failures.append(f"Potential secret in {path.relative_to(PROJECT_ROOT)}")

    gitignore = _read(".gitignore")
    for required_pattern in (".env", "*.db", "logs/", "exports/", ".streamlit/secrets.toml"):
        if required_pattern not in gitignore:
            failures.append(f".gitignore missing {required_pattern}")

    if failures:
        for failure in failures:
            print(f"M9 RELEASE VALIDATION FAILED: {failure}")
        return 1

    print("M9 RELEASE VALIDATION PASSED")
    print("Release baseline: v1.0.0")
    print("Required docs, links, checklist, and secret-safety guards are present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
