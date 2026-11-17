"""Package imports and architectural boundary tests."""

import ast
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


FRONTEND_FORBIDDEN_TOKENS = ("ortools", "googlemaps", "google.maps", "backend.app")
FRONTEND_FORBIDDEN_IMPORT_ROOTS = ("backend", "ortools", "googlemaps", "google.maps")


def _python_files(root: Path) -> list[Path]:
    """Every Python file under ``root``, including sub-packages (finding F16)."""
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def _frontend_boundary_violations(frontend_root: Path) -> list[str]:
    violations: list[str] = []
    for path in _python_files(frontend_root):
        content = path.read_text(encoding="utf-8").casefold()
        forbidden_import = any(
            module == root or module.startswith(f"{root}.")
            for module in _imported_modules(path)
            for root in FRONTEND_FORBIDDEN_IMPORT_ROOTS
        )
        if forbidden_import or any(token in content for token in FRONTEND_FORBIDDEN_TOKENS):
            violations.append(path.relative_to(frontend_root).as_posix())
    return violations


def test_frontend_has_no_solver_google_or_backend_implementation_imports() -> None:
    assert _frontend_boundary_violations(PROJECT_ROOT / "frontend") == []


def test_frontend_boundary_scan_reaches_sub_packages(tmp_path: Path) -> None:
    (tmp_path / "views").mkdir()
    (tmp_path / "views" / "results.py").write_text("from backend import __version__\n")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "store.py").write_text("import ortools.constraint_solver\n")
    (tmp_path / "ok.py").write_text("import httpx\n")

    assert _frontend_boundary_violations(tmp_path) == ["state/store.py", "views/results.py"]


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
