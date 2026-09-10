from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any


TASK_SCOPE_FORMAT = "stoe.hermes.task_scope.v1"
TASK_SCOPE_FIELDS = {
    "format", "task_id", "parent_refs", "role", "objective", "read_scope",
    "write_scope", "allowed_capabilities", "forbidden_capabilities", "invariants",
    "success_criteria", "resource_budget", "recovery_budget", "escalation_boundary",
}
ROLES = {"governor", "planner", "coder", "reviewer"}
ALLOWED_CAPABILITIES = {"read_scoped_repository", "propose_inert_text_patch"}
REQUIRED_FORBIDDEN = {
    "credentials", "dependency_change", "dynamic_execution", "filesystem_outside_scope",
    "force_push", "git_configuration", "history_rewrite", "main_merge", "network",
    "process", "protected_evaluation", "release_or_tag", "validator_change",
}
ESCALATION_REASONS = {"architecture", "trust_boundary", "unresolved_integration", "worker_disagreement", "recovery_exhausted"}
TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9:._-]{7,127}$")


class TaskScopeError(ValueError):
    pass


def task_scope_schema(*, task_id: str, objective: str, read_scope: list[str], write_scope: list[str], parent_refs: list[str], role: str) -> dict[str, Any]:
    exact = {
        "format": TASK_SCOPE_FORMAT, "task_id": task_id, "parent_refs": parent_refs,
        "role": role, "objective": objective, "read_scope": read_scope,
        "write_scope": write_scope,
    }
    return {
        "type": "object",
        "properties": {
            **{name: {"type": "string", "enum": [value]} for name, value in exact.items() if isinstance(value, str)},
            "parent_refs": {"type": "array", "enum": [parent_refs]},
            "read_scope": {"type": "array", "enum": [read_scope]},
            "write_scope": {"type": "array", "enum": [write_scope]},
            "allowed_capabilities": {"type": "array", "enum": [sorted(ALLOWED_CAPABILITIES)]},
            "forbidden_capabilities": {"type": "array", "enum": [sorted(REQUIRED_FORBIDDEN)]},
            "invariants": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 180}},
            "success_criteria": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 180}},
            "resource_budget": {"type": "object", "properties": {"input_tokens": {"type": "integer", "minimum": 1, "maximum": 6000}, "output_tokens": {"type": "integer", "minimum": 1, "maximum": 1600}, "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 420}}, "required": ["input_tokens", "output_tokens", "timeout_seconds"], "additionalProperties": False},
            "recovery_budget": {"type": "object", "properties": {"planner": {"type": "integer", "minimum": 0, "maximum": 2}, "coder": {"type": "integer", "minimum": 0, "maximum": 2}, "reviewer": {"type": "integer", "minimum": 0, "maximum": 1}}, "required": ["planner", "coder", "reviewer"], "additionalProperties": False},
            "escalation_boundary": {"type": "array", "enum": [sorted(ESCALATION_REASONS)]},
        },
        "required": sorted(TASK_SCOPE_FIELDS),
        "additionalProperties": False,
    }


def _paths(values: Any, *, field: str, maximum: int) -> list[str]:
    if not isinstance(values, list) or not 1 <= len(values) <= maximum:
        raise TaskScopeError(f"invalid {field}")
    checked = []
    for value in values:
        if not isinstance(value, str) or not value or "\\" in value:
            raise TaskScopeError(f"invalid {field}")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or any(part in {".git", ".env", "protected_evals", "research_checkpoints"} for part in path.parts):
            raise TaskScopeError(f"unsafe {field}")
        checked.append(path.as_posix())
    if len(set(checked)) != len(checked):
        raise TaskScopeError(f"duplicate {field}")
    return checked


def validate_task_scope(value: Any, *, exact: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != TASK_SCOPE_FIELDS:
        raise TaskScopeError("TaskScope fields are missing or unexpected")
    if value["format"] != TASK_SCOPE_FORMAT or not isinstance(value["task_id"], str) or not TASK_ID_RE.fullmatch(value["task_id"]):
        raise TaskScopeError("invalid TaskScope identity")
    if value["role"] not in ROLES or not isinstance(value["objective"], str) or not 1 <= len(value["objective"]) <= 600:
        raise TaskScopeError("invalid TaskScope role or objective")
    parent_refs = value["parent_refs"]
    if not isinstance(parent_refs, list) or not 1 <= len(parent_refs) <= 8 or any(not isinstance(ref, str) or not ref or len(ref) > 128 for ref in parent_refs):
        raise TaskScopeError("invalid parent refs")
    value = dict(value)
    value["read_scope"] = _paths(value["read_scope"], field="read scope", maximum=12)
    value["write_scope"] = _paths(value["write_scope"], field="write scope", maximum=4)
    if not set(value["write_scope"]).issubset(value["read_scope"]):
        raise TaskScopeError("write scope must be included in read scope")
    allowed = value["allowed_capabilities"]
    if not isinstance(allowed, list) or len(allowed) != len(set(allowed)) or not set(allowed).issubset(ALLOWED_CAPABILITIES):
        raise TaskScopeError("invalid allowed capabilities")
    forbidden = value["forbidden_capabilities"]
    if not isinstance(forbidden, list) or set(forbidden) != REQUIRED_FORBIDDEN:
        raise TaskScopeError("required forbidden capabilities changed")
    for field, maximum in (("invariants", 8), ("success_criteria", 8)):
        items = value[field]
        if not isinstance(items, list) or not items or len(items) > maximum or any(not isinstance(item, str) or not item or len(item) > 180 for item in items):
            raise TaskScopeError(f"invalid {field}")
    resource = value["resource_budget"]
    recovery = value["recovery_budget"]
    if (not isinstance(resource, dict) or set(resource) != {"input_tokens", "output_tokens", "timeout_seconds"}
            or any(type(resource[key]) is not int for key in resource)
            or not (1 <= resource["input_tokens"] <= 6000 and 1 <= resource["output_tokens"] <= 1600 and 1 <= resource["timeout_seconds"] <= 420)):
        raise TaskScopeError("invalid resource budget")
    if (not isinstance(recovery, dict) or set(recovery) != {"planner", "coder", "reviewer"}
            or any(type(recovery[key]) is not int for key in recovery)
            or not (0 <= recovery["planner"] <= 2 and 0 <= recovery["coder"] <= 2 and 0 <= recovery["reviewer"] <= 1)):
        raise TaskScopeError("invalid recovery budget")
    if set(value["escalation_boundary"]) != ESCALATION_REASONS:
        raise TaskScopeError("escalation boundary changed")
    if exact:
        for name in ("task_id", "parent_refs", "role", "objective", "read_scope", "write_scope"):
            if value[name] != exact[name]:
                raise TaskScopeError(f"TaskScope expanded or changed: {name}")
    return value


def validate_repair_scope(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    parent = validate_task_scope(parent)
    child = validate_task_scope(child)
    if parent["task_id"] not in child["parent_refs"] or not set(child["read_scope"]).issubset(parent["read_scope"]) or not set(child["write_scope"]).issubset(parent["write_scope"]) or not set(child["allowed_capabilities"]).issubset(parent["allowed_capabilities"]):
        raise TaskScopeError("repair scope does not descend from parent authority")
    for key in child["resource_budget"]:
        if child["resource_budget"][key] > parent["resource_budget"][key]:
            raise TaskScopeError("repair resource budget expanded")
    return child
