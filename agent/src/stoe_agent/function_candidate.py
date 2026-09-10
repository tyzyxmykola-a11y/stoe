from __future__ import annotations

import ast
import hashlib
from typing import Any


FORMAT = "stoe.function_replacement"
MAX_REPLACEMENT_BYTES = 8_192
MAX_REPLACEMENT_LINES = 100
FIELDS = {"format", "path", "function", "parent_function_sha256", "replacement_source"}


class FunctionCandidateError(ValueError):
    pass


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _tree(source: str) -> ast.Module:
    try:
        return ast.parse(source)
    except (SyntaxError, TypeError, ValueError) as exc:
        raise FunctionCandidateError(f"invalid Python source: {exc}") from exc


def target_function(source: str, name: str) -> tuple[ast.FunctionDef, str]:
    tree = _tree(source)
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(matches) != 1 or matches[0].end_lineno is None:
        raise FunctionCandidateError("parent must contain exactly one matching top-level function")
    node = matches[0]
    lines = source.splitlines()
    segment = "\n".join(lines[node.lineno - 1 : node.end_lineno]) + "\n"
    return node, segment


def function_artifact_schema(*, path: str, function: str, parent_function_sha256: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "format": {"type": "string", "enum": [FORMAT]},
            "path": {"type": "string", "enum": [path]},
            "function": {"type": "string", "enum": [function]},
            "parent_function_sha256": {"type": "string", "enum": [parent_function_sha256]},
            "replacement_source": {"type": "string", "maxLength": MAX_REPLACEMENT_BYTES},
        },
        "required": sorted(FIELDS),
        "additionalProperties": False,
    }


def validate_function_artifact(
    value: Any,
    *,
    expected_path: str,
    expected_function: str,
    parent_source: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise FunctionCandidateError("function artifact fields are missing or unexpected")
    if value["format"] != FORMAT or value["path"] != expected_path or value["function"] != expected_function:
        raise FunctionCandidateError("function artifact identity mismatch")
    parent_node, parent_function = target_function(parent_source, expected_function)
    if value["parent_function_sha256"] != sha256_text(parent_function):
        raise FunctionCandidateError("stale parent function hash")
    replacement = value["replacement_source"]
    if not isinstance(replacement, str) or not replacement.strip() or "\x00" in replacement:
        raise FunctionCandidateError("replacement source is empty or non-text")
    if len(replacement.encode("utf-8")) > MAX_REPLACEMENT_BYTES or len(replacement.splitlines()) > MAX_REPLACEMENT_LINES:
        raise FunctionCandidateError("replacement source exceeds fixed bounds")
    tree = _tree(replacement)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise FunctionCandidateError("replacement must parse as exactly one FunctionDef")
    node = tree.body[0]
    if node.name != expected_function:
        raise FunctionCandidateError("replacement function name mismatch")
    if node.decorator_list:
        raise FunctionCandidateError("function decorators are unauthorized")
    if ast.dump(node.args, include_attributes=False) != ast.dump(parent_node.args, include_attributes=False):
        raise FunctionCandidateError("function signature or scope changed")
    if any(isinstance(item, (ast.Import, ast.ImportFrom)) for item in ast.walk(tree)):
        raise FunctionCandidateError("imports are forbidden in function replacement")
    functions = [item for item in ast.walk(tree) if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(functions) != 1 or any(isinstance(item, (ast.ClassDef, ast.Global, ast.Nonlocal)) for item in ast.walk(tree)):
        raise FunctionCandidateError("replacement expands function or module scope")
    return dict(value)


def reconstruct_module(parent_source: str, artifact: dict[str, Any], *, expected_path: str, expected_function: str) -> str:
    checked = validate_function_artifact(artifact, expected_path=expected_path, expected_function=expected_function, parent_source=parent_source)
    parent_node, _ = target_function(parent_source, expected_function)
    lines = parent_source.splitlines()
    replacement = checked["replacement_source"].rstrip("\n").splitlines()
    result = lines[: parent_node.lineno - 1] + replacement + lines[parent_node.end_lineno :]
    candidate = "\n".join(result) + "\n"
    compile(_tree(candidate), expected_path, "exec", dont_inherit=True)
    return candidate
