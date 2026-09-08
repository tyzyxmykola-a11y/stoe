from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .investigation import public_diagnostics
from .selection_policy import validate_policy
from .supervisor import CANDIDATE_POLICY_SCHEMA, PUBLIC_INPUT_FIELDS


PROPOSAL_MAX_TOKENS = 1000
POLICY_MAX_TOKENS = 1400
PROPOSAL_SEED = 5701
POLICY_SEED = 6701
MIN_REMAINING_TOKENS = 1024
CONDITIONS = ("ORDINARY_OBSERVABLE", "BOUNDED_TYPED_STOE")

MECHANISM_IDS = (
    *PUBLIC_INPUT_FIELDS,
    "token_similarity",
    "conditional_similarity",
    "constant_if",
    "deterministic_sort",
    "budget.greedy_skip_oversize",
)


def _string(max_length: int) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": max_length}


QUALIFIED_PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "hypothesis": _string(180),
        "observed_evidence": {
            "type": "array", "minItems": 1, "maxItems": 3,
            "items": _string(140),
        },
        "diagnostic_findings": {
            "type": "array", "minItems": 1, "maxItems": 3,
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "case": {"type": "string", "maxLength": 64, "enum": [c.name for c in public_diagnostics()]},
                    "observed_selection": {
                        "type": "array", "maxItems": 3, "items": _string(64),
                    },
                    "missed_required": {
                        "type": "array", "maxItems": 3, "items": _string(64),
                    },
                    "mechanism_ids": {
                        "type": "array", "minItems": 1, "maxItems": 6,
                        "uniqueItems": True,
                        "items": {"type": "string", "maxLength": 64, "enum": list(MECHANISM_IDS)},
                    },
                    "rationale": _string(140),
                },
                "required": [
                    "case", "observed_selection", "missed_required", "mechanism_ids", "rationale"
                ],
            },
        },
        "source_diagnosis": _string(180),
        "proposed_change": _string(220),
        "implementation_inputs": {
            "type": "array", "minItems": 1, "maxItems": len(PUBLIC_INPUT_FIELDS),
            "uniqueItems": True,
            "items": {"type": "string", "maxLength": 64, "enum": list(PUBLIC_INPUT_FIELDS)},
        },
        "input_feasibility": _string(140),
        "expected_benefit": _string(140),
        "risks": {
            "type": "array", "minItems": 1, "maxItems": 3,
            "items": _string(120),
        },
    },
    "required": [
        "hypothesis", "observed_evidence", "diagnostic_findings", "source_diagnosis",
        "proposed_change", "implementation_inputs", "input_feasibility",
        "expected_benefit", "risks",
    ],
}


def _validate_schema(value: Any, schema: dict[str, Any], path: str = "proposal") -> None:
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            raise RuntimeError(f"{path} must be an object")
        required = set(schema.get("required", []))
        if not required.issubset(value):
            raise RuntimeError(f"{path} is missing required fields")
        if schema.get("additionalProperties") is False and set(value) - set(schema["properties"]):
            raise RuntimeError(f"{path} contains additional fields")
        for key, item in value.items():
            _validate_schema(item, schema["properties"][key], f"{path}.{key}")
    elif kind == "array":
        if not isinstance(value, list):
            raise RuntimeError(f"{path} must be an array")
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 10**9):
            raise RuntimeError(f"{path} violates item bounds")
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise RuntimeError(f"{path} must contain unique items")
        for index, item in enumerate(value):
            _validate_schema(item, schema["items"], f"{path}[{index}]")
    elif kind == "string":
        if not isinstance(value, str):
            raise RuntimeError(f"{path} must be a string")
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 10**9):
            raise RuntimeError(f"{path} violates length bounds")
        if "enum" in schema and value not in schema["enum"]:
            raise RuntimeError(f"{path} is not an allowed identifier")


def validate_qualified_proposal(proposal: dict[str, Any], investigation: dict[str, Any]) -> None:
    _validate_schema(proposal, QUALIFIED_PROPOSAL_SCHEMA)
    failed = {d["case"]: d for d in investigation["diagnostics"] if not d["selector_passed"]}
    findings = {d["case"]: d for d in proposal["diagnostic_findings"]}
    if set(findings) != set(failed):
        raise RuntimeError("diagnostic_findings must correspond exactly to observed failures")
    for case, observed in failed.items():
        finding = findings[case]
        if finding["observed_selection"] != observed["selector_selected"]:
            raise RuntimeError(f"proposal misstates observed selection for {case}")
        if finding["missed_required"] != observed["missed_refs"]:
            raise RuntimeError(f"proposal misstates missed refs for {case}")
        field_ids = {m for m in finding["mechanism_ids"] if m in PUBLIC_INPUT_FIELDS}
        if not field_ids.intersection(proposal["implementation_inputs"]):
            raise RuntimeError(f"mechanism identifiers are disconnected from implementation inputs for {case}")


def largest_gate_valid_proposal(investigation: dict[str, Any]) -> dict[str, Any]:
    fill = lambda n: "x" * n
    mechanisms = ["item.kind", "item.outcome", "item.failure_condition", "token_similarity", "conditional_similarity", "constant_if"]
    findings = []
    for observed in investigation["diagnostics"]:
        if observed["selector_passed"]:
            continue
        findings.append(
            {
                "case": observed["case"],
                "observed_selection": list(observed["selector_selected"]),
                "missed_required": list(observed["missed_refs"]),
                "mechanism_ids": mechanisms,
                "rationale": fill(140),
            }
        )
    proposal = {
        "hypothesis": fill(180),
        "observed_evidence": [fill(140)] * 3,
        "diagnostic_findings": findings,
        "source_diagnosis": fill(180),
        "proposed_change": fill(220),
        "implementation_inputs": list(PUBLIC_INPUT_FIELDS),
        "input_feasibility": fill(140),
        "expected_benefit": fill(140),
        "risks": [fill(120)] * 3,
    }
    validate_qualified_proposal(proposal, investigation)
    return proposal


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


PROPOSAL_SYSTEM = "Formulate one bounded, falsifiable selector-policy hypothesis from supplied evidence. Return JSON only."
POLICY_SYSTEM = "Generate one inert stoe.selection_policy version 1 JSON policy. Return JSON only; never emit code."


def proposal_prompt(active_source: str, bundle: dict[str, Any], *, structural: bool) -> str:
    payload = {
        "allowed_mechanism_ids": MECHANISM_IDS,
        "active_source": active_source,
        "observable_diagnostics": bundle["observable_diagnostics"],
        "unstructured_memory": bundle["unstructured_memory"],
    }
    base = "Identify mechanisms by allowed IDs; do not infer hidden cases. INPUT=" + _compact(payload)
    if structural:
        base += "\nTYPED_RELATIONAL_OVERLAY=" + _compact(bundle["typed_relational_overlay"])
    return base


def policy_prompt(
    active_source: str, bundle: dict[str, Any], proposal: dict[str, Any], *, structural: bool
) -> str:
    payload = {
        "allowed_policy_operations": [
            "token_similarity", "conditional_similarity", "constant_if", "deterministic_sort",
            "budget.greedy_skip_oversize",
        ],
        "public_input_fields": PUBLIC_INPUT_FIELDS,
        "proposal": proposal,
        "active_source": active_source,
        "observable_diagnostics": bundle["observable_diagnostics"],
        "unstructured_memory": bundle["unstructured_memory"],
    }
    base = "Generalize; do not encode diagnostic refs or case phrases. INPUT=" + _compact(payload)
    if structural:
        base += "\nTYPED_RELATIONAL_OVERLAY=" + _compact(bundle["typed_relational_overlay"])
    return base


def qualify_context_budget(model_client: Any, active_source: str, bundle: dict[str, Any]) -> dict[str, Any]:
    proposal = largest_gate_valid_proposal(bundle["investigation"])
    results: dict[str, Any] = {}
    for condition in CONDITIONS:
        structural = condition == "BOUNDED_TYPED_STOE"
        stages = {
            "proposal": model_client.budget_manager.plan(
                system=PROPOSAL_SYSTEM,
                prompt=proposal_prompt(active_source, bundle, structural=structural),
                reserved_generation_tokens=PROPOSAL_MAX_TOKENS,
            ),
            "policy": model_client.budget_manager.plan(
                system=POLICY_SYSTEM,
                prompt=policy_prompt(active_source, bundle, proposal, structural=structural),
                reserved_generation_tokens=POLICY_MAX_TOKENS,
            ),
        }
        for stage, plan in stages.items():
            if not plan["fits"] or plan["estimated"]["remaining"] < MIN_REMAINING_TOKENS:
                raise RuntimeError(
                    f"{condition} {stage} lacks qualified reserve: {plan['estimated']['remaining']}"
                )
        results[condition] = stages
    return {
        "qualified": True,
        "model_calls": 0,
        "largest_gate_valid_proposal": proposal,
        "conditions": results,
        "minimum_required_remaining_tokens": MIN_REMAINING_TOKENS,
        "minimum_observed_remaining_tokens": min(
            stage["estimated"]["remaining"]
            for condition in results.values()
            for stage in condition.values()
        ),
    }


def exercise_mock_pipelines(model_client: Any, active_source: str, bundle: dict[str, Any]) -> dict[str, Any]:
    """Exercise both complete pipelines; caller supplies a non-provider mock client."""
    results: dict[str, Any] = {}
    for condition in CONDITIONS:
        structural = condition == "BOUNDED_TYPED_STOE"
        proposal, proposal_trace = model_client.generate_json(
            system=PROPOSAL_SYSTEM,
            prompt=proposal_prompt(active_source, bundle, structural=structural),
            schema=QUALIFIED_PROPOSAL_SCHEMA,
            max_output_tokens=PROPOSAL_MAX_TOKENS,
            seed=PROPOSAL_SEED,
        )
        validate_qualified_proposal(proposal, bundle["investigation"])
        generated, policy_trace = model_client.generate_json(
            system=POLICY_SYSTEM,
            prompt=policy_prompt(active_source, bundle, proposal, structural=structural),
            schema=CANDIDATE_POLICY_SCHEMA,
            max_output_tokens=POLICY_MAX_TOKENS,
            seed=POLICY_SEED,
        )
        gate = validate_policy(generated.get("policy"))
        if not gate.passed:
            raise RuntimeError("mock policy failed inert-policy validation: " + "; ".join(gate.errors))
        results[condition] = {
            "proposal_trace": proposal_trace,
            "policy_trace": policy_trace,
            "policy_operations": gate.estimated_operations,
        }
    return {"completed": True, "model_calls": 4, "conditions": results}


def unevaluated_metrics(case_count: int, targeted_count: int, control_count: int) -> dict[str, Any]:
    return {
        "evaluable": False,
        "targeted_pass_count": None,
        "targeted_case_count": targeted_count,
        "control_pass_count": None,
        "control_case_count": control_count,
        "total_pass_count": None,
        "case_count": case_count,
        "by_family": None,
    }
