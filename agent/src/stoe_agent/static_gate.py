from __future__ import annotations

import ast
from dataclasses import dataclass


ALLOWED_IMPORT_ROOTS = {"__future__", "collections", "math", "re", "typing"}
BANNED_CALLS = {
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "globals",
    "input",
    "locals",
    "open",
    "vars",
    "__import__",
}
BANNED_NAMES = {
    "asyncio",
    "builtins",
    "ctypes",
    "importlib",
    "os",
    "pathlib",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "sys",
    "urllib",
}


@dataclass(frozen=True)
class GateResult:
    passed: bool
    errors: tuple[str, ...]


def validate_candidate_source(source: str, *, max_bytes: int = 30_000) -> GateResult:
    errors: list[str] = []
    if len(source.encode("utf-8")) > max_bytes:
        errors.append(f"source exceeds {max_bytes} bytes")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return GateResult(False, (f"syntax error: {exc}",))

    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    selectors = [node for node in functions if node.name == "select_context"]
    if len(selectors) != 1 or isinstance(selectors[0], ast.AsyncFunctionDef):
        errors.append("source must define exactly one synchronous select_context function")
    elif [arg.arg for arg in selectors[0].args.args] != ["observer_state", "items", "max_items", "max_chars"]:
        errors.append(
            "select_context positional arguments must be observer_state, items, max_items, max_chars"
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] not in ALLOWED_IMPORT_ROOTS:
                    errors.append(f"import is outside the allowlist: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root not in ALLOWED_IMPORT_ROOTS:
                errors.append(f"import is outside the allowlist: {node.module}")
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            errors.append(f"name is outside the component boundary: {node.id}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BANNED_CALLS:
            errors.append(f"call is forbidden: {node.func.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            errors.append(f"dunder attribute access is forbidden: {node.attr}")

    return GateResult(not errors, tuple(sorted(set(errors))))
