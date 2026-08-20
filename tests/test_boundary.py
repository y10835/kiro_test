"""Test architectural boundary: generator/ must not import from metrics/ (Req 11.6)."""

import ast
from pathlib import Path


def _collect_imports(source_dir: Path) -> list[tuple[str, str, int]]:
    """Collect all import statements from Python files in a directory.
    
    Returns list of (file_path, imported_module, line_number).
    """
    results = []
    for py_file in source_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    results.append((str(py_file), alias.name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    results.append((str(py_file), node.module, node.lineno))
    return results


def test_no_generator_imports_metrics():
    """generator/ must not import anything from metrics/."""
    generator_dir = Path("hr_analytics_lib/generator")
    if not generator_dir.exists():
        generator_dir = Path(__file__).parent.parent / "hr_analytics_lib" / "generator"
    
    imports = _collect_imports(generator_dir)
    violations = [
        (filepath, module, lineno)
        for filepath, module, lineno in imports
        if "metrics" in module.split(".")
    ]
    assert violations == [], f"Boundary violation! generator/ imports from metrics/: {violations}"


def test_no_metrics_imports_generator():
    """metrics/ must not import anything from generator/."""
    metrics_dir = Path("hr_analytics_lib/metrics")
    if not metrics_dir.exists():
        metrics_dir = Path(__file__).parent.parent / "hr_analytics_lib" / "metrics"
    
    imports = _collect_imports(metrics_dir)
    violations = [
        (filepath, module, lineno)
        for filepath, module, lineno in imports
        if "generator" in module.split(".")
    ]
    assert violations == [], f"Boundary violation! metrics/ imports from generator/: {violations}"
