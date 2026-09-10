from __future__ import annotations

from typing import Any


FORMAT = "stoe.report_dedup_ir"
FIELDS = {
    "format", "path", "function", "parent_function_sha256", "identity_field",
    "connection_fields", "count_fields", "unhashed_policy", "order_policy", "budget_policy",
}
CONNECTION_FIELDS = ["ref", "origin", "kind", "outcome", "path"]
COUNT_FIELDS = ["canonical_payload_count", "collapsed_duplicate_count"]


def report_ir_schema(*, path: str, function: str, parent_function_sha256: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "format": {"type": "string", "enum": [FORMAT]},
            "path": {"type": "string", "enum": [path]},
            "function": {"type": "string", "enum": [function]},
            "parent_function_sha256": {"type": "string", "enum": [parent_function_sha256]},
            "identity_field": {"type": "string", "enum": ["payload_sha256"]},
            "connection_fields": {"type": "object", "properties": {name: {"type": "boolean", "enum": [True]} for name in CONNECTION_FIELDS}, "required": CONNECTION_FIELDS, "additionalProperties": False},
            "count_fields": {"type": "object", "properties": {name: {"type": "boolean", "enum": [True]} for name in COUNT_FIELDS}, "required": COUNT_FIELDS, "additionalProperties": False},
            "unhashed_policy": {"type": "string", "enum": ["distinct"]},
            "order_policy": {"type": "string", "enum": ["preserve_input"]},
            "budget_policy": {"type": "string", "enum": ["complete_lines"]},
        },
        "required": sorted(FIELDS),
        "additionalProperties": False,
    }


def validate_report_ir(value: Any, *, path: str, function: str, parent_function_sha256: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("report IR fields are missing or unexpected")
    expected = {
        "format": FORMAT, "path": path, "function": function,
        "parent_function_sha256": parent_function_sha256,
        "identity_field": "payload_sha256", "connection_fields": {name: True for name in CONNECTION_FIELDS},
        "count_fields": {name: True for name in COUNT_FIELDS}, "unhashed_policy": "distinct",
        "order_policy": "preserve_input", "budget_policy": "complete_lines",
    }
    if value != expected:
        raise ValueError("report IR does not exactly preserve required semantics")
    return dict(value)


def render_report_function(_: dict[str, Any]) -> str:
    return '''def render_retrieved_context(items: list[dict[str, Any]], max_chars: int) -> str:
    """Render canonical payloads once while preserving every connection."""
    if max_chars < 0:
        raise ValueError("max_chars must be non-negative")
    seen: set[str] = set()
    logical_lines: list[str] = []
    collapsed_duplicate_count = 0
    for index, item in enumerate(items):
        declared = str(item.get("payload_sha256", ""))
        identity = declared if declared else "unhashed:" + str(index)
        content = str(item.get("content", "")).replace("\\n", " ")
        if identity not in seen:
            seen.add(identity)
            logical_lines.append("PAYLOAD | " + identity + " | " + content)
        else:
            collapsed_duplicate_count += 1
        logical_lines.append(
            "CONNECTION | " + " | ".join((
                str(item.get("ref", "unknown")),
                str(item.get("origin", "unknown")),
                str(item.get("kind", "unknown")),
                str(item.get("outcome", "unknown")),
                str(item.get("path", "unknown")),
            ))
        )
    header = "canonical_payload_count=" + str(len(seen)) + " | collapsed_duplicate_count=" + str(collapsed_duplicate_count)
    output: list[str] = []
    used = 0
    for line in [header] + logical_lines:
        addition = line if not output else "\\n" + line
        if used + len(addition) > max_chars:
            continue
        output.append(line)
        used += len(addition)
    return "\\n".join(output)
'''
