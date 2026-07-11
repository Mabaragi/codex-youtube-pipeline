from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

SOURCE_ROOT = Path("src/codex_sdk_cli")
MAX_MODULE_LINES = 2_000
MAX_ENTRY_MODULE_LINES = 700
MAX_FUNCTION_LINES = 300
MAX_ENTRY_FUNCTION_LINES = 120
ENTRY_LAYERS = frozenset({"api", "application", "bootstrap", "workers"})


@dataclass(frozen=True, slots=True)
class BudgetViolation:
    path: Path
    symbol: str
    actual: int
    limit: int

    def render(self) -> str:
        return f"{self.path}:{self.symbol} is {self.actual} lines (limit {self.limit})"


def find_violations(source_root: Path = SOURCE_ROOT) -> list[BudgetViolation]:
    violations: list[BudgetViolation] = []
    for path in sorted(source_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8-sig")
        module_limit, function_limit = _limits(path, source_root)
        line_count = len(text.splitlines())
        if line_count > module_limit:
            violations.append(BudgetViolation(path, "<module>", line_count, module_limit))
        tree = ast.parse(text, filename=str(path))
        violations.extend(_function_violations(path, tree, function_limit))
    return violations


def _limits(path: Path, source_root: Path) -> tuple[int, int]:
    relative = path.relative_to(source_root)
    if relative.parts and relative.parts[0] in ENTRY_LAYERS:
        return MAX_ENTRY_MODULE_LINES, MAX_ENTRY_FUNCTION_LINES
    return MAX_MODULE_LINES, MAX_FUNCTION_LINES


def _function_violations(
    path: Path,
    tree: ast.AST,
    limit: int,
) -> list[BudgetViolation]:
    violations: list[BudgetViolation] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end_lineno = node.end_lineno or node.lineno
        size = end_lineno - node.lineno + 1
        if size > limit:
            violations.append(BudgetViolation(path, node.name, size, limit))
    return violations
