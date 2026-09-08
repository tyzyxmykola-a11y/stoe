from __future__ import annotations

import json
from typing import Any, Callable

from .split_cycle import code_schema, review_schema
from .succession import EDITABLE_PATH, SuccessionError


ACTION_ID = "self-code-cycle:hermes-ab-v2-1:split-model-deduplicate-context"
PLAN_OUTPUT_TOKENS = 1_200
MAX_FORMAT_REPAIRS_PER_PLAN_STAGE = 1
REPAIRABLE_FORMAT_DIAGNOSES = {"OUTPUT_TRUNCATION", "SCHEMA_NONCOMPLIANCE"}

FIXED_PLAN = {
    "format": "stoe.fixed_development_plan",
    "version": 1,
    "limitation_id": "ambiguous_deduplication_metrics",
    "behavior_id": "one_canonical_payload_many_semantic_connections",
    "target_path": EDITABLE_PATH,
    "interface_id": "render_retrieved_context_items_max_chars",
    "connection_invariant_id": "preserve_all_typed_connections_and_provenance",
    "budget_invariant_id": "complete_lines_within_max_chars",
    "payload_test_id": "one_payload_for_duplicate_sha256",
    "connection_test_id": "all_connection_records_retained",
    "report_test_id": "explicit_canonical_and_collapsed_counts",
    "risk_id": "header_compatibility",
    "patch_scope_id": "single_function_small",
}


def fixed_plan_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for key, value in FIXED_PLAN.items():
        properties[key] = {"type": "integer", "enum": [value]} if isinstance(value, int) else {"type": "string", "enum": [value]}
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def validate_fixed_plan(value: Any) -> dict[str, Any]:
    if value != FIXED_PLAN:
        raise SuccessionError("fixed planning identifiers do not match the qualified table")
    return value


def compact_review_schema() -> dict[str, Any]:
    properties = {
        "format": {"type": "string", "enum": ["stoe.compact_candidate_review"]},
        "version": {"type": "integer", "enum": [1]},
        "plan_match": {"type": "string", "enum": ["pass", "fail"]},
        "connection_conservation": {"type": "string", "enum": ["pass", "fail"]},
        "regression_id": {"type": "string", "enum": ["none_observed", "header_compatibility", "behavior_regression"]},
        "complexity_id": {"type": "string", "enum": ["necessary", "unnecessary"]},
        "suspicious_change": {"type": "boolean"},
        "verdict": {"type": "string", "enum": ["approve", "reject"]},
    }
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def validate_compact_review(value: Any) -> dict[str, Any]:
    required = set(compact_review_schema()["required"])
    if not isinstance(value, dict) or set(value) != required:
        raise SuccessionError("invalid compact review envelope")
    if value.get("format") != "stoe.compact_candidate_review" or value.get("version") != 1:
        raise SuccessionError("invalid compact review identity")
    return value


def plan_from_result(result: dict[str, Any]) -> dict[str, Any]:
    diagnosis = result.get("diagnosis")
    if diagnosis != "COMPLETE_STRUCTURED_OUTPUT":
        raise SuccessionError(f"plan format failure: {diagnosis}")
    return validate_fixed_plan(result.get("parsed"))


def plan_with_one_repair(
    call: Callable[[str, str], dict[str, Any]],
    *,
    primary_id: str,
    primary_prompt: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Accept a fixed plan or autoinject one diagnosed correction into one child."""
    attempts: list[dict[str, Any]] = []
    first = call(primary_id, primary_prompt)
    attempts.append(first)
    try:
        return plan_from_result(first), attempts
    except SuccessionError as first_error:
        diagnosis = str(first.get("diagnosis", "VALIDATION_FAILURE"))
        if diagnosis not in REPAIRABLE_FORMAT_DIAGNOSES and diagnosis != "COMPLETE_STRUCTURED_OUTPUT":
            raise
        correction = (
            f"PARENT_FAILURE_ID={diagnosis}. CORRECTION_ID=emit_exact_fixed_table. "
            "Return one JSON object only; use every schema enum exactly once; no prose, repetition, code, or extra keys."
        )
        child = call(f"{primary_id}_repair_1", correction)
        attempts.append(child)
        try:
            return plan_from_result(child), attempts
        except SuccessionError as child_error:
            raise SuccessionError(
                f"fixed plan failed after {MAX_FORMAT_REPAIRS_PER_PLAN_STAGE} repair: {child_error}"
            ) from first_error


__all__ = [
    "ACTION_ID",
    "FIXED_PLAN",
    "MAX_FORMAT_REPAIRS_PER_PLAN_STAGE",
    "PLAN_OUTPUT_TOKENS",
    "code_schema",
    "compact_review_schema",
    "fixed_plan_schema",
    "plan_with_one_repair",
    "review_schema",
    "validate_compact_review",
    "validate_fixed_plan",
]
