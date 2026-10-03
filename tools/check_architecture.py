"""Architecture guard used by CI.

Fails when a testbench path is hardcoded in agent code again. That hardcoding
is why only the bundled counter task could ever be graded, so it is worth a
mechanical check rather than a review convention.

Run: py -3 tools/check_architecture.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

# A hardcoded testbench reference would look like one of these.
FORBIDDEN_PATTERNS = (
    re.compile(r"examples[/\\]counter[/\\]tb\.v", re.I),
    re.compile(r"examples[/\\]counter[/\\]answer\.v", re.I),
)


def docstring_positions(tree: ast.AST) -> set[int]:
    """Line numbers that belong to a docstring, so prose is not flagged."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                value = body[0].value
                if isinstance(value.value, str):
                    start = value.lineno
                    end = getattr(value, "end_lineno", start)
                    lines.update(range(start, end + 1))
    return lines


def check_file(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, str(path))
    skip = docstring_positions(tree)
    problems: list[str] = []
    for number, line in enumerate(source.splitlines(), start=1):
        if number in skip:
            continue
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'"):
            continue
        for pattern in FORBIDDEN_PATTERNS:
            if pattern.search(line):
                problems.append(f"{path.relative_to(ROOT)}:{number}: {stripped}")
    return problems


def main() -> int:
    if not AGENT.is_dir():
        print(f"agent/ directory not found at {AGENT}")
        return 2
    problems: list[str] = []
    for path in sorted(AGENT.rglob("*.py")):
        problems.extend(check_file(path))
    if problems:
        print("Hardcoded testbench/reference paths found in agent code:")
        for item in problems:
            print("  " + item)
        print("\nagent/ must obtain these from agent.testbench (resolve_testbench / resolve_reference_answer).")
        return 1
    print("architecture guard: no hardcoded testbench path in agent/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
