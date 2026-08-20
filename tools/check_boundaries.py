#!/usr/bin/env python3
"""AST-based import boundary checker.

Verifies that generator/ does not import from metrics/ and vice versa.
Exit code 0 = pass, 1 = violations found.

Usage:
    python tools/check_boundaries.py
"""

import ast
import sys
from pathlib import Path


def check_boundary(source_dir: Path, forbidden_package: str) -> list[str]:
    """Check that no file in source_dir imports from forbidden_package."""
    violations = []
    for py_file in source_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if forbidden_package in alias.name.split("."):
                        violations.append(f"{py_file}:{node.lineno} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and forbidden_package in node.module.split("."):
                    violations.append(f"{py_file}:{node.lineno} imports from {node.module}")
    return violations


def main() -> int:
    root = Path(__file__).parent.parent / "hr_analytics_lib"
    generator_dir = root / "generator"
    metrics_dir = root / "metrics"

    all_violations = []
    all_violations.extend(check_boundary(generator_dir, "metrics"))
    all_violations.extend(check_boundary(metrics_dir, "generator"))

    if all_violations:
        print("❌ Boundary violations found:")
        for v in all_violations:
            print(f"  {v}")
        return 1
    
    print("✅ No boundary violations found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
