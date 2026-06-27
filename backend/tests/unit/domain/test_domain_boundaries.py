"""M2 domain-layer infrastructure boundary tests."""

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", maxsplit=1)[0])
    return roots


def test_domain_and_task_expansion_have_no_infrastructure_imports() -> None:
    files = list((PROJECT_ROOT / "backend" / "app" / "domain").glob("*.py"))
    files.append(PROJECT_ROOT / "backend" / "app" / "optimization" / "task_expander.py")
    forbidden_roots = {"fastapi", "streamlit", "sqlite3", "httpx", "requests", "urllib"}
    violations: list[str] = []
    for path in files:
        if imported_roots(path) & forbidden_roots:
            violations.append(str(path.relative_to(PROJECT_ROOT)))

    assert violations == []


def test_domain_tests_do_not_import_transport_or_persistence_packages() -> None:
    test_files = (PROJECT_ROOT / "backend" / "tests" / "unit" / "domain").glob("test_*.py")
    forbidden_roots = {"fastapi", "streamlit", "sqlite3", "httpx", "requests", "urllib"}
    violations: list[str] = []
    for path in test_files:
        if imported_roots(path) & forbidden_roots:
            violations.append(str(path.relative_to(PROJECT_ROOT)))

    assert violations == []
