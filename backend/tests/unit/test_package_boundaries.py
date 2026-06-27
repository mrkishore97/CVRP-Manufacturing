"""Package imports and architectural boundary tests."""

import importlib
import pkgutil
from pathlib import Path

import backend.app

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_every_backend_application_module_imports() -> None:
    module_names = [
        module.name for module in pkgutil.walk_packages(backend.app.__path__, prefix="backend.app.")
    ]

    assert module_names
    for module_name in module_names:
        importlib.import_module(module_name)


def test_backend_application_does_not_import_streamlit() -> None:
    backend_files = (PROJECT_ROOT / "backend" / "app").rglob("*.py")

    violations = [
        str(path.relative_to(PROJECT_ROOT))
        for path in backend_files
        if "streamlit" in path.read_text(encoding="utf-8").casefold()
    ]

    assert violations == []


def test_frontend_has_no_solver_google_or_backend_implementation_imports() -> None:
    frontend_files = (PROJECT_ROOT / "frontend").glob("*.py")
    forbidden_tokens = ("ortools", "googlemaps", "google.maps", "backend.app")
    violations: list[str] = []
    for path in frontend_files:
        content = path.read_text(encoding="utf-8").casefold()
        if any(token in content for token in forbidden_tokens):
            violations.append(str(path.relative_to(PROJECT_ROOT)))

    assert violations == []


def test_secret_and_generated_paths_are_ignored() -> None:
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    required_patterns = {
        ".env",
        ".streamlit/secrets.toml",
        "**/.streamlit/secrets.toml",
        ".venv/",
        "*.db",
        "logs/",
        "exports/",
    }

    assert required_patterns <= set(gitignore)
